"""Find the image files under one folder, and index them by content: metadata and thumbnails.

Originals are only ever read. Identical files share one image, so thumbnails and vectors survive renames and moves.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
import errno
import hashlib
import logging
import os
from pathlib import Path
import sys
import threading
import time
import warnings

from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError

from server.cache import connect, preview_path, thumbnail_path, while_open

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

EXTENSIONS = {'.jpg', '.jpeg', '.jpe', '.png', '.gif', '.webp', '.bmp', '.tif', '.tiff', '.heic', '.heif', '.avif'}
# Photos and videos in formats the scanner can't read. They are only counted, so a folder of them doesn't look empty
# for no reason.
RAW = {'.3fr', '.arw', '.cr2', '.cr3', '.crw', '.dcr', '.dng', '.erf', '.fff', '.iiq', '.kdc', '.mef', '.mos', '.mrw',
       '.nef', '.nrw', '.orf', '.pef', '.raf', '.raw', '.rw2', '.rwl', '.sr2', '.srf', '.srw', '.x3f'}
VIDEO = {'.3gp', '.avi', '.flv', '.m2ts', '.m4v', '.mkv', '.mov', '.mp4', '.mpeg', '.mpg', '.mts', '.webm', '.wmv'}
SKIPPED = {**dict.fromkeys(RAW, 'raw'), **dict.fromkeys(VIDEO, 'video')}
THUMBNAIL_SIZE = 720
# Anything larger is refused as a possible decompression bomb, by refuse_oversized.
Image.MAX_IMAGE_PIXELS = 300_000_000
warnings.filterwarnings('ignore', category=Image.DecompressionBombWarning)
BATCH = 48
BLOCKED = 'Blocked by macOS'
# How often the count of files found so far is reported while a folder is listed.
FOUND_EVERY = 500
WORKERS = min(8, os.cpu_count() or 2)
# The most bytes of decoded pixels held at once, so huge PNGs and TIFFs, which unlike JPEG can't decode straight to a
# smaller scale, decode in turn rather than all together. Pillow keeps most modes at 4 bytes a pixel.
DECODE_BYTES = 1 << 30
PIXEL_BYTES = 4
EXIF_TAKEN, EXIF_DIGITIZED, EXIF_OFFSET = 36867, 36868, 36881
EXIF_MAKE, EXIF_MODEL = 271, 272
logger = logging.getLogger(__name__)


class FolderUnavailable(RuntimeError):
    pass


def blocked_by_macos(error: Exception) -> bool:
    """Whether macOS's privacy settings kept this app out, as they do from Desktop and Documents until the user allows
    it. They refuse with EPERM, where a file's own permissions give EACCES."""
    return sys.platform == 'darwin' and isinstance(error, PermissionError) and error.errno == errno.EPERM


def blocked(folder: Path) -> FolderUnavailable:
    return FolderUnavailable(f'macOS is blocking access to {folder}. Allow it in System Settings › Privacy & Security › '
                             'Files & Folders, or Full Disk Access, then rescan.')


class ScanCancelled(Exception):
    pass


def walk(root: Path, skip=frozenset(), found=None):
    """Every image file below root as (relative posix path, stat), the folders that could not be listed, the Photos
    libraries passed over, and how many RAW and video files were skipped. `found` hears the running count of image
    files.

    Hidden entries are skipped, and so are Photos libraries, which macOS keeps closed to other apps. Symlinked folders
    are followed once each, after the real folders, so a link loop ends and a folder reached both ways keeps its real
    path.
    """
    files, unreadable, libraries, visited = [], [], [], set()
    skipped = dict.fromkeys(('raw', 'video'), 0)
    stack, links = [('', str(root))], []
    while stack or links:
        relative, directory = stack.pop() if stack else links.pop()
        try:
            status = os.stat(directory)
            key = (status.st_dev, status.st_ino)
            if key in visited or key in skip:
                continue
            visited.add(key)
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.name.startswith('.'):
                        continue
                    child = f'{relative}/{entry.name}' if relative else entry.name
                    try:
                        if entry.name.endswith('.photoslibrary'):
                            libraries.append(child)
                        elif entry.is_dir():
                            (links if entry.is_symlink() else stack).append((child, entry.path))
                        elif entry.is_file():
                            extension = os.path.splitext(entry.name)[1].lower()
                            if extension in EXTENSIONS:
                                files.append((child, entry.stat()))
                                if found and len(files) % FOUND_EVERY == 0:
                                    found(len(files))
                            elif extension in SKIPPED:
                                skipped[SKIPPED[extension]] += 1
                    except OSError:
                        continue
        except OSError as error:
            if not relative and blocked_by_macos(error):
                raise blocked(root) from None
            unreadable.append(relative)
    return files, unreadable, libraries, skipped


def utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def exif_details(image):
    """When the photo was taken, and the camera, from EXIF. Either may be None."""
    try:
        exif = image.getexif()
        detail = exif.get_ifd(ExifTags.IFD.Exif)
    except Exception:
        return None, None
    taken = None
    value = detail.get(EXIF_TAKEN) or detail.get(EXIF_DIGITIZED)
    if isinstance(value, str):
        try:
            moment = datetime.strptime(value.strip('\x00 ')[:19], '%Y:%m:%d %H:%M:%S')
            offset = str(detail.get(EXIF_OFFSET) or '').strip('\x00 ')
            if offset:
                moment = datetime.fromisoformat(moment.isoformat() + offset)
            # Without an offset, EXIF time is the camera's local time, read as this computer's zone.
            taken = utc(moment)
        except ValueError:
            pass
    make, model = (str(exif.get(tag) or '').strip('\x00 ') for tag in (EXIF_MAKE, EXIF_MODEL))
    camera = model if model.lower().startswith(make.lower()) else f'{make} {model}'.strip()
    return taken, camera or None


def displayable(image):
    """Convert to a mode WebP and JPEG can store, scaling 16-bit and float images instead of clipping them."""
    if image.mode in ('RGB', 'RGBA', 'L'):
        return image
    if image.mode.startswith('I;16') or image.mode in ('I', 'F'):
        image = image.convert('I') if image.mode.startswith('I;16') else image
        extent = image.getextrema()[1] or 1
        return image.point(lambda value: value * 255 / extent).convert('L')
    has_alpha = image.mode in ('LA', 'PA', 'RGBa', 'La') or 'transparency' in image.info
    return image.convert('RGBA' if has_alpha else 'RGB')


def refuse_oversized(image):
    """Raise DecompressionBombError for an image past the limit, which Pillow only warns about up to twice the limit."""
    width, height = image.size
    if width * height > Image.MAX_IMAGE_PIXELS:
        raise Image.DecompressionBombError(f'{width} x {height} pixels')


class Budget:
    """Room shared by threads that each hold some amount for a while. One amount larger than all of it waits to be
    held alone."""

    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0
        self._changed = threading.Condition()

    @contextmanager
    def hold(self, amount: int):
        amount = min(amount, self.limit)
        with self._changed:
            self._changed.wait_for(lambda: self.used + amount <= self.limit)
            self.used += amount
        try:
            yield
        finally:
            with self._changed:
                self.used -= amount
                self._changed.notify_all()


DECODING = Budget(DECODE_BYTES)


def scaled(image, edge: int):
    """An open image decoded to fit within edge pixels each way and turned upright, in a mode WebP and JPEG can
    store. It is shrunk before it is turned, so the full-size pixels are only ever held once."""
    # JPEG can decode straight to a smaller scale, which is much faster for large photos.
    image.draft('RGB', (edge, edge))
    with DECODING.hold(image.width * image.height * PIXEL_BYTES):
        image.thumbnail((edge, edge))
    return displayable(ImageOps.exif_transpose(image))


def failure(error: Exception) -> str:
    if isinstance(error, Image.DecompressionBombError):
        return 'Too large to open'
    if isinstance(error, UnidentifiedImageError):
        return 'Not a readable image'
    if blocked_by_macos(error):
        return BLOCKED
    if isinstance(error, PermissionError):
        return 'Permission denied'
    if isinstance(error, OSError) and 'truncated' in str(error):
        return 'Damaged or incomplete'
    return 'Not a readable image'


class Scanner:
    def __init__(self, folder: Path, directory: Path):
        self.folder = Path(folder)
        self.directory = Path(directory)
        (self.directory / 'thumbnails').mkdir(parents=True, exist_ok=True)
        with connect(self.directory, rows=True) as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS images (
                    id TEXT PRIMARY KEY, width INTEGER NOT NULL, height INTEGER NOT NULL, mime TEXT NOT NULL,
                    size INTEGER NOT NULL, taken TEXT, camera TEXT
                );
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY, folder TEXT NOT NULL, image_id TEXT REFERENCES images(id),
                    size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, modified TEXT NOT NULL, error TEXT
                );
                CREATE INDEX IF NOT EXISTS file_image ON files(image_id);
                CREATE INDEX IF NOT EXISTS file_folder ON files(folder);
            ''')

    def scan(self, progress=None, committed=None, cancelled=lambda: False):
        """Bring the index in line with the folder. Unchanged files are recognised by size and modification time."""
        if not self.folder.is_dir():
            raise FolderUnavailable(f'{self.folder} is not available. Reconnect its drive, or choose another folder.')
        skip = set()
        if self.directory.exists():
            status = self.directory.stat()
            skip.add((status.st_dev, status.st_ino))
        started = time.monotonic()
        found, unreadable, libraries, skipped = walk(self.folder, skip, progress and (lambda count: progress({'found': count, 'done': 0, 'changed': 0})))
        listed = time.monotonic() - started
        if '' in unreadable:
            raise FolderUnavailable(f'{self.folder} could not be read. Check its permissions, or choose another folder.')
        with connect(self.directory, rows=True) as db:
            known = {row['path']: (row['size'], row['mtime_ns']) for row in db.execute('SELECT path, size, mtime_ns FROM files')}
            self._seen = {row[0] for row in db.execute('SELECT id FROM images')}
        changed = [(path, status) for path, status in found if known.get(path) != (status.st_size, status.st_mtime_ns)]
        stats = {'found': len(found), 'done': 0, 'changed': len(changed)}
        if progress:
            progress(dict(stats))
        with ThreadPoolExecutor(WORKERS) as pool:
            for start in range(0, len(changed), BATCH):
                if cancelled():
                    raise ScanCancelled
                batch = changed[start:start + BATCH]
                results = list(pool.map(self._examine, [path for path, _ in batch]))
                if any(result.get('error') == BLOCKED for result in results):
                    raise blocked(self.folder)
                with connect(self.directory, rows=True) as db:
                    for (path, status), result in zip(batch, results):
                        if 'width' in result:
                            db.execute('INSERT OR IGNORE INTO images VALUES (?,?,?,?,?,?,?)',
                                       (result['id'], result['width'], result['height'], result['mime'],
                                        status.st_size, result['taken'], result['camera']))
                        modified = utc(datetime.fromtimestamp(status.st_mtime_ns / 1e9, UTC))
                        db.execute('INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?)',
                                   (path, path.rpartition('/')[0], result.get('id') if 'error' not in result else None,
                                    status.st_size, status.st_mtime_ns, modified, result.get('error')))
                self._seen.update(result['id'] for result in results if 'width' in result)
                stats['done'] += len(batch)
                if committed:
                    committed()
                if progress:
                    progress(dict(stats))
        removed = self._remove_missing({path for path, _ in found}, unreadable)
        if removed and committed:
            committed()
        with connect(self.directory, rows=True) as db:
            stats['images'] = db.execute('SELECT count(*) FROM images').fetchone()[0]
            stats['files'] = db.execute('SELECT count(*) FROM files WHERE image_id IS NOT NULL').fetchone()[0]
            stats['unreadable'] = db.execute('SELECT count(*) FROM files WHERE error IS NOT NULL').fetchone()[0]
        stats['removed'] = removed
        stats['listed_seconds'] = round(listed, 3)
        stats['unlisted_folders'] = len(unreadable)
        stats['photo_libraries'] = libraries
        stats['skipped'] = skipped
        return stats

    def _examine(self, relative: str) -> dict:
        """Hash one file and, if its content is new, read its metadata and draw its thumbnail."""
        path = self.folder / relative
        try:
            if path.stat().st_size == 0:
                return {'error': 'Empty file'}
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest in self._seen:
                return {'id': digest}
            with Image.open(path) as image:
                mime = Image.MIME.get(image.format or '', 'application/octet-stream')
                refuse_oversized(image)
                width, height = image.size
                # Drawn before the EXIF is read, since reading a PNG's EXIF decodes the whole image.
                display = scaled(image, THUMBNAIL_SIZE)
                if image.getexif().get(ExifTags.Base.Orientation) in (5, 6, 7, 8):
                    width, height = height, width
                taken, camera = exif_details(image)
                target = thumbnail_path(self.directory, digest)
                temporary = target.with_suffix(f'.{os.getpid()}-{id(display)}.tmp')
                display.save(temporary, 'WEBP', quality=82)
                while_open(temporary.replace, target)
            return {'id': digest, 'width': width, 'height': height, 'mime': mime, 'taken': taken, 'camera': camera}
        except Exception as error:
            logger.info('Could not read %s: %s', relative, error)
            return {'error': failure(error)}

    def _remove_missing(self, present: set, unreadable: list) -> int:
        """Forget files that are gone, and the images and thumbnails nothing refers to. Files inside a folder that
        could not be listed are kept, since it may only be locked for now."""
        blocked = tuple(f'{folder}/' for folder in unreadable if folder)
        with connect(self.directory, rows=True) as db:
            gone = [path for (path,) in db.execute('SELECT path FROM files')
                    if path not in present and not path.startswith(blocked)]
            db.executemany('DELETE FROM files WHERE path=?', [(path,) for path in gone])
            orphans = [image_id for (image_id,) in db.execute(
                'SELECT id FROM images WHERE id NOT IN (SELECT image_id FROM files WHERE image_id IS NOT NULL)')]
            db.executemany('DELETE FROM images WHERE id=?', [(image_id,) for image_id in orphans])
        for image_id in orphans:
            for path in (thumbnail_path(self.directory, image_id), preview_path(self.directory, image_id)):
                while_open(path.unlink, missing_ok=True)
        return len(gone)
