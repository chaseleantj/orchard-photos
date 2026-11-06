"""Find the image and video files under one folder, and index them by content: metadata and thumbnails.

Originals are only ever read. Identical files share one image, so thumbnails and vectors survive renames and moves.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
import errno
import hashlib
from io import BytesIO
import logging
import os
from pathlib import Path
import sys
import threading
import time
import warnings

from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError

from server.cache import connect, frame_path, preview_path, thumbnail_path, while_open, write_image

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

IMAGES = {'.jpg', '.jpeg', '.jpe', '.png', '.gif', '.webp', '.bmp', '.tif', '.tiff', '.heic', '.heif', '.avif'}
# Videos, by the type each is served as. Browsers play only some of them; the rest are still shown and searched.
VIDEOS = {'.3gp': 'video/3gpp', '.avi': 'video/x-msvideo', '.flv': 'video/x-flv', '.m2ts': 'video/mp2t',
          '.m4v': 'video/x-m4v', '.mkv': 'video/x-matroska', '.mov': 'video/quicktime', '.mp4': 'video/mp4',
          '.mpeg': 'video/mpeg', '.mpg': 'video/mpeg', '.mts': 'video/mp2t', '.webm': 'video/webm',
          '.wmv': 'video/x-ms-wmv'}
# Camera RAW photos, read by the full-size JPEG preview nearly every camera stores inside them.
RAW = {'.3fr', '.arw', '.cr2', '.cr3', '.crw', '.dcr', '.dng', '.erf', '.fff', '.iiq', '.kdc', '.mef', '.mos', '.mrw',
       '.nef', '.nrw', '.orf', '.pef', '.raf', '.raw', '.rw2', '.rwl', '.sr2', '.srf', '.srw', '.x3f'}
EXTENSIONS = IMAGES | RAW | VIDEOS.keys()
# An embedded JPEG starts with these bytes: the start-of-image marker and the first segment's marker.
JPEG_START = b'\xff\xd8\xff'
THUMBNAIL_SIZE = 720
# Where in a video, as shares of its length, the frames visual search reads are taken, and their size. Search sees
# the video as the average of those frames. The model reads 256 pixels square.
SEARCH_FRAMES = (.25, .5, .75)
FRAME_SIZE = 384
# How many frames past a seek's keyframe are decoded to reach the moment asked for, before the keyframe stands in.
SEEK_FRAMES = 90
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


class OnlyInCloud(OSError):
    """A photo whose original is in iCloud, not on this computer."""


class UnreadableVideo(ValueError):
    """A video FFmpeg can't open or decode."""


def walk(root: Path, skip=frozenset(), found=None):
    """Every image and video file below root as (relative posix path, stat), the folders that could not be listed, and
    the Photos libraries passed over. `found` hears the running count of files.

    Hidden entries are skipped, and so are Photos libraries, which macOS keeps closed to other apps. Symlinked folders
    are followed once each, after the real folders, so a link loop ends and a folder reached both ways keeps its real
    path.
    """
    files, unreadable, libraries, visited = [], [], [], set()
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
                    except OSError:
                        continue
        except OSError as error:
            if not relative and blocked_by_macos(error):
                raise blocked(root) from None
            unreadable.append(relative)
    return files, unreadable, libraries


class Folder:
    """Images and videos as files under a folder: the source a scan reads from, unless it is a Photos library."""

    def __init__(self, root: Path, skip=frozenset()):
        self.root = Path(root)
        self.skip = skip

    def check(self):
        if not self.root.is_dir():
            raise FolderUnavailable(f'{self.root} is not available. Reconnect its drive, or choose another folder.')

    def list(self, found=None):
        """Every image and video as (path, folder, size, mtime_ns), with walk's unreadable folders and Photos libraries."""
        files, unreadable, libraries = walk(self.root, self.skip, found)
        if '' in unreadable:
            raise FolderUnavailable(f'{self.root} could not be read. Check its permissions, or choose another folder.')
        entries = [(path, path.rpartition('/')[0], status.st_size, status.st_mtime_ns) for path, status in files]
        return entries, unreadable, libraries

    def open(self, path: str):
        return (self.root / path).open('rb')

    def file(self, path: str) -> Path:
        return self.root / path


def video_type(path: str) -> str | None:
    """The type a video file is served as, or None for any other file."""
    return VIDEOS.get(os.path.splitext(path)[1].lower())


def raw_preview(data: bytes):
    """The largest JPEG inside a RAW file, as an open image, carrying the RAW's orientation so scaled() turns it
    upright, and the RAW itself opened as a TIFF for its EXIF, or None when it isn't one. Raises UnidentifiedImageError
    when there is no preview."""
    best, at = None, 0
    while (at := data.find(JPEG_START, at)) >= 0:
        try:
            # Pillow reads only the header here, and ignores whatever follows the JPEG.
            candidate = Image.open(BytesIO(data[at:]))
            if candidate.format == 'JPEG' and (best is None or candidate.width * candidate.height > best.width * best.height):
                best = candidate
        except (OSError, ValueError, Image.DecompressionBombError):
            pass
        at += len(JPEG_START)
    if best is None:
        raise UnidentifiedImageError('No preview inside this RAW file')
    try:
        container = Image.open(BytesIO(data))
    except (OSError, ValueError, Image.DecompressionBombError):
        container = None
    orientation = container and container.getexif().get(ExifTags.Base.Orientation)
    if orientation:
        best.getexif()[ExifTags.Base.Orientation] = orientation
    return best, container


def utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def camera_name(make: str, model: str) -> str | None:
    """The camera as people name it. Many models already start with their make."""
    camera = model if model.lower().startswith(make.lower()) else f'{make} {model}'.strip()
    return camera or None


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
    return taken, camera_name(make, model)


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


def save(image, target: Path):
    """Write a thumbnail or a search frame as WebP. Method 0 encodes about 5x faster than the default for files about a
    sixth larger, which matters most on slow computers scanning many photos."""
    write_image(image, target, 'WEBP', quality=82, method=0)


def upright(frame):
    """A decoded video frame as an RGB image, turned the way the video is meant to be seen."""
    image = frame.to_image()
    return image.rotate(frame.rotation, expand=True) if frame.rotation else image


def frame_at(container, video, seconds: float):
    """The first frame at or after `seconds`, decoding on from the keyframe before it, or that keyframe if the moment is
    more than SEEK_FRAMES further on."""
    container.seek(int(seconds / video.time_base), stream=video)
    found = None
    for count, frame in enumerate(container.decode(video)):
        found = found or frame
        if frame.time is None or frame.time >= seconds:
            return frame
        if count >= SEEK_FRAMES:
            return found
    if found is None:
        raise UnreadableVideo('No frame at that time')
    return found


def video_details(metadata: dict):
    """When a video was recorded, and the camera, from its container's tags. Either may be None."""
    taken = None
    # Apple's tag keeps the local offset; creation_time is UTC.
    for key in ('com.apple.quicktime.creationdate', 'creation_time'):
        value = metadata.get(key, '').strip()
        try:
            moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            continue
        # A camera without a clock writes the epoch of its format.
        if moment.year > 1971:
            taken = utc(moment if moment.tzinfo else moment.replace(tzinfo=UTC))
            break
    make, model = (metadata.get(f'com.apple.quicktime.{tag}', '').strip() for tag in ('make', 'model'))
    return taken, camera_name(make, model)


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


def unreached(error: Exception) -> bool:
    """Whether a read failed on the way to the file, as when a network drive drops, rather than on the file itself.
    Those failures carry the system's error number; Pillow's, for a file it can't decode, don't. A file's own
    permissions are a failure of the file."""
    return isinstance(error, OSError) and error.errno is not None and not isinstance(error, PermissionError)


def failure(error: Exception) -> str:
    if isinstance(error, OnlyInCloud):
        return 'Only in iCloud'
    if isinstance(error, Image.DecompressionBombError):
        return 'Too large to open'
    if isinstance(error, UnidentifiedImageError):
        return 'Not a readable image'
    if isinstance(error, UnreadableVideo):
        return 'Not a readable video'
    if blocked_by_macos(error):
        return BLOCKED
    if isinstance(error, PermissionError):
        return 'Permission denied'
    if isinstance(error, OSError) and 'truncated' in str(error):
        return 'Damaged or incomplete'
    return 'Not a readable image'


class Scanner:
    def __init__(self, folder: Path, directory: Path, source=None):
        self.folder = Path(folder)
        self.directory = Path(directory)
        (self.directory / 'thumbnails').mkdir(parents=True, exist_ok=True)
        if source is None:
            # The cache may sit inside the folder, and isn't scanned.
            status = self.directory.stat()
            source = Folder(self.folder, {(status.st_dev, status.st_ino)})
        self.source = source
        with connect(self.directory, rows=True) as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS images (
                    id TEXT PRIMARY KEY, width INTEGER NOT NULL, height INTEGER NOT NULL, mime TEXT NOT NULL,
                    size INTEGER NOT NULL, taken TEXT, camera TEXT, duration REAL
                );
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY, folder TEXT NOT NULL, image_id TEXT REFERENCES images(id),
                    size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, modified TEXT NOT NULL, error TEXT
                );
                CREATE INDEX IF NOT EXISTS file_image ON files(image_id);
                CREATE INDEX IF NOT EXISTS file_folder ON files(folder);
            ''')
            # Caches from before videos were read have no duration.
            if 'duration' not in {row['name'] for row in db.execute('PRAGMA table_info(images)')}:
                db.execute('ALTER TABLE images ADD COLUMN duration REAL')

    def scan(self, progress=None, committed=None, cancelled=lambda: False, retry=False):
        """Bring the index in line with the source. Unchanged files are recognised by size and modification time,
        and so are files that could not be read, unless `retry` asks to try them again.

        A file that could not be reached is left out, so the next scan reads it. If the source is gone, or a whole
        batch could not be reached, the scan stops, and the next one carries on once the source is back."""
        self.source.check()
        started = time.monotonic()
        found, unreadable, libraries = self.source.list(progress and (lambda count: progress({'found': count, 'done': 0, 'changed': 0})))
        listed = time.monotonic() - started
        with connect(self.directory, rows=True) as db:
            known = {row['path']: (row['size'], row['mtime_ns']) for row in db.execute(
                'SELECT path, size, mtime_ns FROM files' + (' WHERE error IS NULL' if retry else ''))}
            self._seen = {row[0] for row in db.execute('SELECT id FROM images')}
        changed = [entry for entry in found if known.get(entry[0]) != (entry[2], entry[3])]
        stats = {'found': len(found), 'done': 0, 'changed': len(changed)}
        if progress:
            progress(dict(stats))
        missed = 0
        with ThreadPoolExecutor(WORKERS) as pool:
            for start in range(0, len(changed), BATCH):
                if cancelled():
                    raise ScanCancelled
                batch = changed[start:start + BATCH]
                results = list(pool.map(self._examine, batch))
                if any(result.get('error') == BLOCKED for result in results):
                    raise blocked(self.folder)
                lost = sum(1 for result in results if result.get('unreached'))
                if lost:
                    self.source.check()
                    # A network drive that stops answering can still be listed, so a whole batch failing stops it too.
                    # One file alone may just be damaged, and is left to the next scan.
                    if lost == len(batch) > 1:
                        raise FolderUnavailable(f'{self.folder} stopped answering partway through the scan. Reconnect it, then rescan to carry on.')
                    missed += lost
                with connect(self.directory, rows=True) as db:
                    for (path, folder, size, mtime_ns), result in zip(batch, results):
                        if result.get('unreached'):
                            continue
                        if 'width' in result:
                            db.execute('INSERT OR IGNORE INTO images (id, width, height, mime, size, taken, camera, duration) '
                                       'VALUES (?,?,?,?,?,?,?,?)',
                                       (result['id'], result['width'], result['height'], result['mime'],
                                        size, result['taken'], result['camera'], result.get('duration')))
                        modified = utc(datetime.fromtimestamp(mtime_ns / 1e9, UTC))
                        db.execute('INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?)',
                                   (path, folder, result.get('id') if 'error' not in result else None,
                                    size, mtime_ns, modified, result.get('error')))
                self._seen.update(result['id'] for result in results if 'width' in result)
                stats['done'] += len(batch)
                if committed:
                    committed()
                if progress:
                    progress(dict(stats))
        removed = self._remove_missing({entry[0] for entry in found}, unreadable)
        if removed and committed:
            committed()
        with connect(self.directory, rows=True) as db:
            stats['images'] = db.execute('SELECT count(*) FROM images').fetchone()[0]
            stats['files'] = db.execute('SELECT count(*) FROM files WHERE image_id IS NOT NULL').fetchone()[0]
            stats['unreadable'] = db.execute('SELECT count(*) FROM files WHERE error IS NOT NULL').fetchone()[0]
        stats['removed'] = removed
        stats['unreached'] = missed
        stats['listed_seconds'] = round(listed, 3)
        stats['unlisted_folders'] = len(unreadable)
        stats['photo_libraries'] = libraries
        return stats

    def _examine(self, entry) -> dict:
        """Hash one file and, if its content is new, read its metadata and draw its thumbnail, and a video's frames for
        search."""
        relative, _, size, _ = entry
        try:
            if size == 0:
                return {'error': 'Empty file'}
            with self.source.open(relative) as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                if digest in self._seen:
                    return {'id': digest}
                stream.seek(0)
                mime = video_type(relative)
                return self._describe_video(stream, digest, mime) if mime else self._describe(stream, digest, relative)
        except Exception as error:
            logger.info('Could not read %s: %s', relative, error)
            return {'unreached': True} if unreached(error) else {'error': failure(error)}

    def _describe(self, stream, digest: str, relative: str) -> dict:
        """Read a new image's metadata and draw its thumbnail. A RAW photo is read by its preview, and its EXIF from the
        RAW itself when that can be opened."""
        extension = os.path.splitext(relative)[1].lower()
        image, container = raw_preview(stream.read()) if extension in RAW else (Image.open(stream), None)
        with image:
            mime = f'image/x-{extension[1:]}' if extension in RAW else Image.MIME.get(image.format or '', 'application/octet-stream')
            refuse_oversized(image)
            width, height = image.size
            # Drawn before the EXIF is read, since reading a PNG's EXIF decodes the whole image.
            display = scaled(image, THUMBNAIL_SIZE)
            if image.getexif().get(ExifTags.Base.Orientation) in (5, 6, 7, 8):
                width, height = height, width
            taken, camera = exif_details(container or image)
            save(display, thumbnail_path(self.directory, digest))
        return {'id': digest, 'width': width, 'height': height, 'mime': mime, 'taken': taken, 'camera': camera}

    def _describe_video(self, stream, digest: str, mime: str) -> dict:
        """Read a new video's metadata, and draw its first frame as the thumbnail and SEARCH_FRAMES for search."""
        import av
        try:
            with av.open(stream) as container:
                if not container.streams.video:
                    raise UnreadableVideo('No video stream')
                video = container.streams.video[0]
                video.thread_type = 'AUTO'
                duration = container.duration / av.time_base if container.duration else (
                    float(video.duration * video.time_base) if video.duration else 0.0)
                first = upright(next(container.decode(video)))
                frames = [upright(frame_at(container, video, duration * share)) for share in SEARCH_FRAMES] if duration else [first]
                metadata = {**video.metadata, **container.metadata}
        except (av.FFmpegError, StopIteration) as error:
            raise UnreadableVideo(str(error)) from None
        width, height = first.size
        poster = first.copy()
        poster.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        save(poster, thumbnail_path(self.directory, digest))
        for place, frame in enumerate(frames):
            frame.thumbnail((FRAME_SIZE, FRAME_SIZE))
            save(frame, frame_path(self.directory, digest, place))
        taken, camera = video_details(metadata)
        return {'id': digest, 'width': width, 'height': height, 'mime': mime, 'taken': taken, 'camera': camera,
                'duration': round(duration, 3) or None}

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
            frames = [frame_path(self.directory, image_id, place) for place in range(len(SEARCH_FRAMES))]
            for path in (thumbnail_path(self.directory, image_id), preview_path(self.directory, image_id), *frames):
                while_open(path.unlink, missing_ok=True)
        return len(gone)
