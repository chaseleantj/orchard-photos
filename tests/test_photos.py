from io import BytesIO
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from server import photos
from server.api import App
from server.cache import connect
from server.photos import SHOW, PhotosLibrary, show
from server.scanner import OnlyInCloud, Scanner


def jpeg(color='red'):
    stream = BytesIO()
    Image.new('RGB', (40, 30), color).save(stream, 'JPEG')
    return stream.getvalue()


class Source:
    """A Photos library in memory, standing in for PhotosLibrary."""

    def __init__(self):
        self.photos = {}
        self.opened = []

    def add(self, asset_id, name, color='red', mtime_ns=1):
        self.photos[f'{asset_id}/{name}'] = (jpeg(color), mtime_ns)

    def check(self):
        pass

    def list(self, found=None):
        return [(path, '', len(data), mtime) for path, (data, mtime) in self.photos.items()], [], [], {'raw': 0, 'video': 2}

    def open(self, path):
        self.opened.append(path)
        if path.endswith('cloud.jpg'):
            raise OnlyInCloud(path)
        return BytesIO(self.photos[path][0])


class ScanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Source()
        self.scanner = Scanner(photos.LIBRARY, Path(self.temp.name) / 'cache', self.source)

    def files(self):
        with connect(self.scanner.directory, rows=True) as db:
            return {row['path']: dict(row) for row in db.execute('SELECT * FROM files')}

    def test_photos_are_scanned_like_files_with_no_folders(self):
        self.source.add('A/L0/001', 'IMG_1.jpg')
        self.source.add('B/L0/001', 'IMG_2.jpg', 'blue')
        stats = self.scanner.scan()
        self.assertEqual((stats['images'], stats['skipped']), (2, {'raw': 0, 'video': 2}))
        self.assertEqual({row['folder'] for row in self.files().values()}, {''})

    def test_only_new_and_edited_photos_are_read_again(self):
        self.source.add('A/L0/001', 'IMG_1.jpg')
        self.source.add('B/L0/001', 'IMG_2.jpg', 'blue')
        self.scanner.scan()
        self.source.opened.clear()
        self.source.add('B/L0/001', 'IMG_2.jpg', 'green', mtime_ns=2)  # edited in Photos
        self.source.add('C/L0/001', 'IMG_3.jpg', 'white')
        del self.source.photos['A/L0/001/IMG_1.jpg']
        stats = self.scanner.scan()
        self.assertEqual(sorted(self.source.opened), ['B/L0/001/IMG_2.jpg', 'C/L0/001/IMG_3.jpg'])
        self.assertEqual((stats['images'], stats['removed']), (2, 1))

    def test_a_photo_kept_only_in_icloud_says_so(self):
        self.source.add('A/L0/001', 'cloud.jpg')
        self.scanner.scan()
        self.assertEqual(self.files()['A/L0/001/cloud.jpg']['error'], 'Only in iCloud')


class Asset(SimpleNamespace):
    def localIdentifier(self):
        return self.id

    def modificationDate(self):
        return SimpleNamespace(timeIntervalSince1970=lambda: self.modified)

    def creationDate(self):
        return None


class Fetched(list):
    def count(self):
        return len(self)

    def objectAtIndex_(self, index):
        return self[index]


class ListingTests(unittest.TestCase):
    """PhotosLibrary.list against a stand-in for PhotoKit."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        Scanner(photos.LIBRARY, self.directory, Source())  # makes the tables
        self.assets = Fetched([Asset(id='A/L0/001', modified=10.0), Asset(id='B/L0/001', modified=20.0)])
        self.described = []

        def resources(asset):
            self.described.append(asset.id)
            return [SimpleNamespace(type=lambda: 1, originalFilename=lambda: f'{asset.id[0]}.heic', valueForKey_=lambda key: 1234)]
        kit = SimpleNamespace(
            PHAssetMediaTypeImage=1, PHAssetMediaTypeVideo=2, PHAssetResourceTypePhoto=1,
            PHAsset=SimpleNamespace(fetchAssetsWithMediaType_options_=lambda kind, options: self.assets if kind == 1 else Fetched([None] * 3)),
            PHAssetResource=SimpleNamespace(assetResourcesForAsset_=resources))
        modules = patch.dict(sys.modules, {'Photos': kit})
        modules.start()
        self.addCleanup(modules.stop)

    def test_paths_keep_the_asset_id_and_original_name_and_unchanged_photos_are_not_described_again(self):
        library = PhotosLibrary(self.directory)
        (library.exports / 'old').mkdir(parents=True)
        entries, unreadable, libraries, skipped = library.list()
        self.assertEqual(entries, [('A/L0/001/A.heic', '', 1234, 10_000_000_000), ('B/L0/001/B.heic', '', 1234, 20_000_000_000)])
        self.assertEqual((unreadable, libraries, skipped), ([], [], {'raw': 0, 'video': 3}))
        self.assertFalse(library.exports.exists(), 'Exports of viewed photos go with each scan')
        with connect(self.directory) as db:
            db.executemany('INSERT INTO files VALUES (?,?,?,?,?,?,?)', [(path, '', None, size, mtime, '', None) for path, _, size, mtime in entries])
        self.described.clear()
        self.assets[1].modified = 21.0
        library.list()
        self.assertEqual(self.described, ['B/L0/001'])


class ShowingTests(unittest.TestCase):
    def test_photos_opens_at_the_photo_whose_id_is_passed_as_an_argument_not_as_script(self):
        done = subprocess.CompletedProcess([], 0, '', '')
        with patch('server.photos.subprocess.run', return_value=done) as run:
            show('A"B/L0/001/IMG_1.jpg')
        self.assertEqual(run.call_args.args[0], [*SHOW, 'A"B/L0/001'])

    def test_each_failure_says_what_to_do(self):
        for stderr, message in (('execution error: Not authorized to send Apple events to Photos. (-1743)', 'Automation'),
                                ('execution error: Can’t get media item id "A/L0/001". (-1728)', 'Rescan'),
                                ('execution error: something else (-1)', 'couldn’t show')):
            failed = subprocess.CompletedProcess([], 1, '', stderr)
            with self.subTest(stderr=stderr), patch('server.photos.subprocess.run', return_value=failed), \
                    self.assertRaisesRegex(ValueError, message):
                show('A/L0/001/IMG_1.jpg')


class OpeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = App(Path(self.temp.name) / 'data')
        # Opening starts a scan in the background; the tests look only at what opening decides, as if on a Mac.
        for patcher in (patch('server.api.threading.Thread'), patch('server.api.photos.available', return_value=True)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_photos_library_opens_by_its_name_and_is_remembered(self):
        library = self.app.open(str(photos.LIBRARY))
        self.assertTrue(library.photos)
        status = self.app.status()
        self.assertEqual((status['photos'], status['folder']['name'], status['folder']['photos']), (str(photos.LIBRARY), 'Photos', True))
        self.app.open(self.temp.name)
        self.assertEqual(self.app.status()['recent'][0], {'path': str(photos.LIBRARY), 'label': 'Photos', 'available': True})

    def test_only_the_system_library_opens_and_only_on_a_mac(self):
        with self.assertRaisesRegex(ValueError, 'System Photo Library'):
            self.app.open(str(Path(self.temp.name) / 'Old.photoslibrary'))
        with patch('server.api.photos.available', return_value=False), self.assertRaisesRegex(ValueError, 'Only a Mac'):
            self.app.open(str(photos.LIBRARY))
        self.assertIsNone(self.app.library)


if __name__ == '__main__':
    unittest.main()
