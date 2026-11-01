"""The Mac's Photos library as a source of images and videos, read through PhotoKit with the user's permission.

macOS keeps the library's files closed to other apps, so they are never read from disk. Photos hands over each photo's
and video's current version, with any edits, and the scanner treats it like a file in a folder. PhotoKit reads only the System
Photo Library, wherever it is, so that is the one library Orchard opens.
"""
from io import BytesIO
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

from server.cache import connect, while_open
from server.scanner import FolderUnavailable, OnlyInCloud, video_type

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
    """A source for the scanner, like scanner.Folder. A photo's or video's path is its asset's id and its original file
    name, so searching file names finds it and the scanner knows a video by it. Its folder is empty, since Photos has
    no folders on disk."""

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
        """Every photo and video as (path, folder, size, mtime_ns), with no unreadable folders or libraries. One whose
        modification date hasn't changed keeps its path and size, so only new and edited ones are asked about."""
        import Photos

        with connect(self.directory, rows=True) as db:
            known = {identifier(row['path']): (row['path'], row['size'], row['mtime_ns'])
                     for row in db.execute('SELECT path, size, mtime_ns FROM files')}
        entries = []
        for kind, resource_type in ((Photos.PHAssetMediaTypeImage, Photos.PHAssetResourceTypePhoto),
                                    (Photos.PHAssetMediaTypeVideo, Photos.PHAssetResourceTypeVideo)):
            assets = Photos.PHAsset.fetchAssetsWithMediaType_options_(kind, None)
            for index in range(assets.count()):
                asset = assets.objectAtIndex_(index)
                asset_id = asset.localIdentifier()
                moment = asset.modificationDate() or asset.creationDate()
                mtime_ns = int(moment.timeIntervalSince1970() * 1e9) if moment else 0
                path, size, mtime = known.get(asset_id, (None, None, None))
                if mtime != mtime_ns:
                    path, size = self._describe(asset, resource_type)
                entries.append((path, '', size, mtime_ns))
                if found and len(entries) % 500 == 0:
                    found(len(entries))
        # Exports are only for what is being viewed, so they go with each scan.
        shutil.rmtree(self.exports, ignore_errors=True)
        return entries, [], [], {'raw': 0}

    @staticmethod
    def _describe(asset, resource_type):
        """The path and size for an asset, from its original file: the resource of `resource_type`, or else its first."""
        import Photos

        resources = Photos.PHAssetResource.assetResourcesForAsset_(asset)
        original = next((resource for resource in resources if resource.type() == resource_type), None)
        original = original or (resources[0] if resources else None)
        name = original.originalFilename() if original else ('Video' if resource_type == Photos.PHAssetResourceTypeVideo else 'Photo')
        try:
            size = int(original.valueForKey_('fileSize'))
        except Exception:
            size = 1  # Unknown, but not empty.
        return f'{asset.localIdentifier()}/{name}', size or 1

    @staticmethod
    def _asset(path: str):
        import Photos

        assets = Photos.PHAsset.fetchAssetsWithLocalIdentifiers_options_([identifier(path)], None)
        if not assets.count():
            raise FileNotFoundError(path)
        return assets.objectAtIndex_(0)

    def read(self, path: str) -> tuple[bytes, str]:
        """The photo's current version, with any edits, and its file extension."""
        import Photos

        asset = self._asset(path)
        options = Photos.PHImageRequestOptions.alloc().init()
        options.setSynchronous_(True)
        options.setVersion_(Photos.PHImageRequestOptionsVersionCurrent)
        options.setDeliveryMode_(Photos.PHImageRequestOptionsDeliveryModeHighQualityFormat)
        # Photos kept only in iCloud would download here. Orchard doesn't download a whole library unasked.
        options.setNetworkAccessAllowed_(False)
        result = {}
        Photos.PHImageManager.defaultManager().requestImageDataAndOrientationForAsset_options_resultHandler_(
            asset, options, lambda data, uti, orientation, info: result.update(data=data, uti=uti, info=info))
        if result.get('data') is None:
            info = result.get('info') or {}
            if info.get(Photos.PHImageResultIsInCloudKey):
                raise OnlyInCloud(path)
            raise OSError(f'Photos could not provide {path}')
        return bytes(result['data']), EXTENSIONS.get(str(result.get('uti')), Path(path).suffix)

    def write_video(self, path: str, target: Path):
        """Have Photos write the video's current version, with any edits, to `target`. Videos are written rather than
        read into memory, since they can be large."""
        from Foundation import NSURL
        import Photos

        resources = {resource.type(): resource for resource in Photos.PHAssetResource.assetResourcesForAsset_(self._asset(path))}
        resource = resources.get(Photos.PHAssetResourceTypeFullSizeVideo) or resources.get(Photos.PHAssetResourceTypeVideo)
        if resource is None:
            raise OSError(f'Photos has no video for {path}')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f'.{os.getpid()}-{threading.get_ident()}.tmp')
        options = Photos.PHAssetResourceRequestOptions.alloc().init()
        # As with photos, a video kept only in iCloud isn't downloaded unasked.
        options.setNetworkAccessAllowed_(False)
        done, failed = threading.Event(), []

        # PhotoKit calls this on its own queue. It must return None: anything else, or an exception, aborts the app.
        def finished(error):
            failed.append(error)
            done.set()
        Photos.PHAssetResourceManager.defaultManager().writeDataForAssetResource_toFile_options_completionHandler_(
            resource, NSURL.fileURLWithPath_(str(temporary)), options, finished)
        done.wait()
        if failed[0] is not None:
            temporary.unlink(missing_ok=True)
            try:
                local = bool(resource.valueForKey_('locallyAvailable'))
            except Exception:
                local = True
            raise OnlyInCloud(path) if not local else OSError(f'Photos could not provide {path}: {failed[0]}')
        while_open(temporary.replace, target)

    def open(self, path: str):
        """A stream of the photo or video. A video is written to a file that goes as soon as the stream closes."""
        if not video_type(path):
            return BytesIO(self.read(path)[0])
        written = self.exports / 'reading' / f'{os.getpid()}-{threading.get_ident()}'
        self.write_video(path, written)
        stream = written.open('rb')
        written.unlink()  # The open stream still reads it.
        return stream

    def file(self, path: str) -> Path:
        """The photo or video written out, for viewing and downloading, and kept until the next scan, so a video
        streamed by byte range is written once. It keeps its original name."""
        name = path.rpartition('/')[2]
        target = self.exports / identifier(path).replace('/', '-') / name
        if video_type(path):
            if not target.is_file():
                self.write_video(path, target)
            return target
        data, extension = self.read(path)
        target = target.with_suffix(extension)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target
