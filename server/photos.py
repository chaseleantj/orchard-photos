"""The Mac's Photos library as a source of images, read through PhotoKit with the user's permission.

macOS keeps the library's files closed to other apps, so they are never read from disk. Photos hands over each photo's
current version, with any edits, and the scanner treats it like a file in a folder. PhotoKit reads only the System
Photo Library, wherever it is, so that is the one library Orchard opens.
"""
from io import BytesIO
import logging
from pathlib import Path
import shutil
import subprocess
import sys
import threading

from server.cache import connect
from server.scanner import FolderUnavailable, OnlyInCloud

# How Orchard names the System Photo Library, as a folder it can remember. The path is only a name: PhotoKit finds the
# library wherever it is.
LIBRARY = Path.home() / 'Pictures' / 'Photos Library.photoslibrary'
NAME = 'Photos'
EXTENSIONS = {'public.jpeg': '.jpg', 'public.heic': '.heic', 'public.png': '.png', 'public.tiff': '.tiff',
              'com.compuserve.gif': '.gif', 'org.webmproject.webp': '.webp', 'public.avif': '.avif'}
# Opens Photos at one photo. The id comes as an argument, so it is never read as script.
SHOW = ['osascript', '-e', 'on run argv', '-e', 'tell application "Photos"', '-e', 'activate', '-e',
        'spotlight media item id (item 1 of argv)', '-e', 'end tell', '-e', 'end run']
# What osascript says when macOS doesn't let it control Photos, and when Photos has no such photo.
NOT_ALLOWED, NOT_FOUND = '-1743', '-1728'
# PhotoKit's values, so they can be compared before it is imported.
NOT_DETERMINED, RESTRICTED, DENIED, AUTHORIZED = 0, 1, 2, 3
logger = logging.getLogger(__name__)


def available() -> bool:
    """Whether this computer can read a Photos library: a Mac with PhotoKit's bindings installed."""
    if sys.platform != 'darwin':
        return False
    try:
        import Photos  # noqa: F401
    except ImportError:
        return False
    return True


def is_library(path: Path) -> bool:
    return Path(path).suffix == '.photoslibrary'


def identifier(path: str) -> str:
    """The asset id at the start of a photo's path."""
    return path.rpartition('/')[0]


def show(path: str):
    """Open Photos at a photo. The first time, macOS asks whether Orchard may control Photos."""
    try:
        result = subprocess.run([*SHOW, identifier(path)], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('Photos didn’t open. Try again.') from None
    if result.returncode:
        if NOT_ALLOWED in result.stderr:
            raise ValueError('macOS hasn’t allowed Orchard to control Photos. Allow it in System Settings › Privacy & Security › '
                             'Automation, then try again.')
        if NOT_FOUND in result.stderr:
            raise ValueError('Photos no longer has this photo. Rescan to refresh.')
        logger.info('Show in Photos failed: %s', result.stderr.strip())
        raise ValueError('Photos couldn’t show this photo.')


class PhotosLibrary:
    """A source for the scanner, like scanner.Folder. A photo's path is its asset's id and its original file name,
    so searching file names finds it, and its folder is empty, since Photos has no folders on disk."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.exports = self.directory / 'exports'

    def check(self):
        """Ask for access the first time. macOS shows its prompt once; after that, only System Settings changes it."""
        import Photos

        level = Photos.PHAccessLevelReadWrite
        status = Photos.PHPhotoLibrary.authorizationStatusForAccessLevel_(level)
        if status == NOT_DETERMINED:
            answered = threading.Event()
            Photos.PHPhotoLibrary.requestAuthorizationForAccessLevel_handler_(level, lambda _: answered.set())
            answered.wait()
            status = Photos.PHPhotoLibrary.authorizationStatusForAccessLevel_(level)
        if status != AUTHORIZED:
            raise FolderUnavailable('macOS hasn’t allowed Orchard to read your Photos library. Allow it in System Settings › '
                                    'Privacy & Security › Photos, then rescan. Started from Terminal, Orchard can’t ask, so '
                                    'open it from its app, or the one scripts/install-app makes.')

    def list(self, found=None):
        """Every photo as (path, folder, size, mtime_ns), with no unreadable folders or libraries, and the videos
        skipped. A photo whose modification date hasn't changed keeps its path and size, so only new and edited
        photos are asked about."""
        import Photos

        with connect(self.directory, rows=True) as db:
            known = {identifier(row['path']): (row['path'], row['size'], row['mtime_ns'])
                     for row in db.execute('SELECT path, size, mtime_ns FROM files')}
        assets = Photos.PHAsset.fetchAssetsWithMediaType_options_(Photos.PHAssetMediaTypeImage, None)
        entries = []
        for index in range(assets.count()):
            asset = assets.objectAtIndex_(index)
            asset_id = asset.localIdentifier()
            moment = asset.modificationDate() or asset.creationDate()
            mtime_ns = int(moment.timeIntervalSince1970() * 1e9) if moment else 0
            path, size, mtime = known.get(asset_id, (None, None, None))
            if mtime != mtime_ns:
                path, size = self._describe(asset)
            entries.append((path, '', size, mtime_ns))
            if found and len(entries) % 500 == 0:
                found(len(entries))
        # Exports are only for the image being viewed, so they go with each scan.
        shutil.rmtree(self.exports, ignore_errors=True)
        videos = Photos.PHAsset.fetchAssetsWithMediaType_options_(Photos.PHAssetMediaTypeVideo, None).count()
        return entries, [], [], {'raw': 0, 'video': videos}

    @staticmethod
    def _describe(asset):
        """The path and size for an asset, from its original file."""
        import Photos

        resources = Photos.PHAssetResource.assetResourcesForAsset_(asset)
        original = next((resource for resource in resources if resource.type() == Photos.PHAssetResourceTypePhoto), None)
        original = original or (resources[0] if resources else None)
        name = original.originalFilename() if original else 'Photo'
        try:
            size = int(original.valueForKey_('fileSize'))
        except Exception:
            size = 1  # Unknown, but not empty.
        return f'{asset.localIdentifier()}/{name}', size or 1

    def read(self, path: str) -> tuple[bytes, str]:
        """The photo's current version, with any edits, and its file extension."""
        import Photos

        assets = Photos.PHAsset.fetchAssetsWithLocalIdentifiers_options_([identifier(path)], None)
        if not assets.count():
            raise FileNotFoundError(path)
        options = Photos.PHImageRequestOptions.alloc().init()
        options.setSynchronous_(True)
        options.setVersion_(Photos.PHImageRequestOptionsVersionCurrent)
        options.setDeliveryMode_(Photos.PHImageRequestOptionsDeliveryModeHighQualityFormat)
        # Photos kept only in iCloud would download here. Orchard doesn't download a whole library unasked.
        options.setNetworkAccessAllowed_(False)
        result = {}
        Photos.PHImageManager.defaultManager().requestImageDataAndOrientationForAsset_options_resultHandler_(
            assets.objectAtIndex_(0), options, lambda data, uti, orientation, info: result.update(data=data, uti=uti, info=info))
        if result.get('data') is None:
            info = result.get('info') or {}
            if info.get(Photos.PHImageResultIsInCloudKey):
                raise OnlyInCloud(path)
            raise OSError(f'Photos could not provide {path}')
        return bytes(result['data']), EXTENSIONS.get(str(result.get('uti')), Path(path).suffix)

    def open(self, path: str):
        return BytesIO(self.read(path)[0])

    def file(self, path: str) -> Path:
        """The photo written out, for viewing and downloading. It keeps its original name."""
        data, extension = self.read(path)
        name = path.rpartition('/')[2]
        target = self.exports / identifier(path).replace('/', '-') / (Path(name).stem + extension)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target
