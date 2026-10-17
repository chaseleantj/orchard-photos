from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
import warnings

from PIL import Image

from server.cache import connect, thumbnail_path
from server.scanner import Budget, FolderUnavailable, Scanner, exif_details, walk


def picture(path: Path, color='red', size=(32, 24), **save):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', size, color).save(path, **save)
    return path


def dated(taken='2023:05:04 10:30:00', offset=None, orientation=None):
    exif = Image.Exif()
    exif[271], exif[272] = 'Canon', 'Canon EOS R6'
    if orientation:
        exif[274] = orientation
    detail = exif.get_ifd(0x8769)
    detail[36867] = taken
    if offset:
        detail[36881] = offset
    return exif


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'photos'
        self.root.mkdir()
        self.cache = Path(self.temp.name) / 'cache'
        self.scanner = Scanner(self.root, self.cache)

    def files(self):
        with connect(self.scanner.directory, rows=True) as db:
            return {row['path']: dict(row) for row in db.execute('SELECT * FROM files')}

    def test_nested_folders_hidden_entries_and_extensions(self):
        picture(self.root / 'a/b/c/deep.jpg')
        picture(self.root / 'top.PNG')
        picture(self.root / '.hidden/secret.png')
        picture(self.root / '._resource.png')
        picture(self.root / 'a/Photos Library.photoslibrary/originals/kept-by-photos.jpg')
        (self.root / 'notes.txt').write_text('not an image')
        stats = self.scanner.scan()
        self.assertEqual(set(self.files()), {'a/b/c/deep.jpg', 'top.PNG'})
        self.assertEqual(self.files()['a/b/c/deep.jpg']['folder'], 'a/b/c')
        self.assertEqual((stats['images'], stats['unreadable']), (2, 0))
        self.assertEqual(stats['photo_libraries'], ['a/Photos Library.photoslibrary'])
        self.assertGreaterEqual(stats['listed_seconds'], 0)

    @unittest.skipIf(sys.platform == 'win32', 'Symlinks need Developer Mode on Windows')
    def test_symlink_loops_end_and_real_paths_win(self):
        picture(self.root / 'real/one.png')
        os.symlink(self.root, self.root / 'real/loop')
        os.symlink(self.root / 'real', self.root / 'alias')
        found, unreadable, _ = walk(self.root)
        self.assertEqual([path for path, _ in found], ['real/one.png'])
        self.assertEqual(unreadable, [])

    def test_identical_files_share_one_image_with_a_thumbnail(self):
        first = picture(self.root / 'one.png')
        shutil.copy(first, self.root / 'copy.png')
        picture(self.root / 'other.png', 'blue')
        stats = self.scanner.scan()
        self.assertEqual((stats['images'], stats['files']), (2, 3))
        files = self.files()
        self.assertEqual(files['one.png']['image_id'], files['copy.png']['image_id'])
        self.assertTrue(thumbnail_path(self.cache, files['one.png']['image_id']).is_file())

    def test_broken_files_are_reported_and_not_retried_until_they_change(self):
        (self.root / 'random.jpg').write_bytes(os.urandom(2000))
        (self.root / 'empty.png').write_bytes(b'')
        good = picture(self.root / 'good.jpg', size=(400, 300), quality=90)
        (self.root / 'truncated.jpg').write_bytes(good.read_bytes()[:len(good.read_bytes()) // 2])
        stats = self.scanner.scan()
        errors = {path: row['error'] for path, row in self.files().items() if row['error']}
        self.assertEqual(errors, {'random.jpg': 'Not a readable image', 'empty.png': 'Empty file',
                                  'truncated.jpg': 'Damaged or incomplete'})
        self.assertEqual((stats['images'], stats['unreadable']), (1, 3))
        self.assertEqual(self.scanner.scan()['changed'], 0)

    def test_images_over_the_pixel_limit_are_refused(self):
        Image.MAX_IMAGE_PIXELS, limit = 1000, Image.MAX_IMAGE_PIXELS
        self.addCleanup(setattr, Image, 'MAX_IMAGE_PIXELS', limit)
        picture(self.root / 'big.png', size=(40, 30))
        with warnings.catch_warnings():
            # Pillow warns below twice its limit, where the scanner refuses the image itself.
            warnings.simplefilter('ignore', Image.DecompressionBombWarning)
            self.scanner.scan()
        self.assertEqual(self.files()['big.png']['error'], 'Too large to open')

    def test_rescan_follows_added_changed_and_removed_files(self):
        changing = picture(self.root / 'changing.png')
        leaving = picture(self.root / 'leaving.png', 'green')
        self.scanner.scan()
        old = self.files()['changing.png']['image_id']
        self.assertEqual(self.scanner.scan()['changed'], 0)
        picture(changing, 'blue', size=(10, 10))
        leaving.unlink()
        picture(self.root / 'new/arrival.png', 'yellow')
        stats = self.scanner.scan()
        self.assertEqual((stats['changed'], stats['removed'], stats['images']), (2, 1, 2))
        self.assertEqual(set(self.files()), {'changing.png', 'new/arrival.png'})
        self.assertNotEqual(self.files()['changing.png']['image_id'], old)
        self.assertFalse(thumbnail_path(self.cache, old).exists())

    def test_a_missing_folder_keeps_its_cache(self):
        picture(self.root / 'one.png')
        self.scanner.scan()
        shutil.rmtree(self.root)
        with self.assertRaises(FolderUnavailable):
            self.scanner.scan()
        self.assertEqual(set(self.files()), {'one.png'})

    @unittest.skipIf(sys.platform == 'win32' or os.geteuid() == 0, 'Permissions do not lock folders on Windows or for root')
    def test_files_in_a_locked_folder_are_kept(self):
        picture(self.root / 'locked/one.png')
        self.scanner.scan()
        (self.root / 'locked').chmod(0)
        self.addCleanup((self.root / 'locked').chmod, 0o755)
        stats = self.scanner.scan()
        self.assertEqual((stats['unlisted_folders'], stats['removed']), (1, 0))
        self.assertEqual(set(self.files()), {'locked/one.png'})

    def test_capture_date_camera_and_orientation(self):
        picture(self.root / 'offset.jpg', exif=dated(offset='+02:00'))
        picture(self.root / 'rotated.jpg', size=(40, 20), exif=dated(orientation=6))
        picture(self.root / 'plain.png')
        self.scanner.scan()
        with connect(self.scanner.directory, rows=True) as db:
            rows = {row['path']: row for row in db.execute('SELECT f.path, i.* FROM files f JOIN images i ON i.id=f.image_id')}
        self.assertEqual(rows['offset.jpg']['taken'], '2023-05-04T08:30:00Z')
        self.assertEqual(rows['offset.jpg']['camera'], 'Canon EOS R6')
        self.assertEqual((rows['rotated.jpg']['width'], rows['rotated.jpg']['height']), (20, 40))
        self.assertIsNone(rows['plain.png']['taken'])

    def test_a_rotated_png_is_drawn_upright(self):
        picture(self.root / 'rotated.png', size=(40, 20), exif=dated(orientation=6))
        self.scanner.scan()
        row = self.files()['rotated.png']
        with connect(self.scanner.directory, rows=True) as db:
            image = db.execute('SELECT width, height FROM images WHERE id=?', (row['image_id'],)).fetchone()
        self.assertEqual(tuple(image), (20, 40))
        with Image.open(thumbnail_path(self.cache, row['image_id'])) as thumbnail:
            self.assertEqual(thumbnail.size, (20, 40))

    def test_exif_without_an_offset_is_local_time(self):
        path = picture(self.root / 'local.jpg', exif=dated('2023:05:04 10:30:00'))
        with Image.open(path) as image:
            taken, camera = exif_details(image)
        expected = datetime(2023, 5, 4, 10, 30).astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
        self.assertEqual((taken, camera), (expected, 'Canon EOS R6'))

    def test_heic_and_sixteen_bit_images_get_thumbnails(self):
        picture(self.root / 'phone.heic', format='HEIF')
        Image.new('I;16', (20, 10), 40000).save(self.root / 'scan.tif')
        self.scanner.scan()
        files = self.files()
        self.assertTrue(all(row['image_id'] for row in files.values()), files)
        with Image.open(thumbnail_path(self.cache, files['scan.tif']['image_id'])) as thumbnail:
            # The brightest value becomes white rather than the near-black a plain conversion would give.
            self.assertGreater(thumbnail.convert('L').getpixel((0, 0)), 250)

    def test_the_cache_inside_the_folder_is_not_scanned(self):
        inside = Scanner(self.root, self.root / 'cache')
        picture(self.root / 'one.png')
        inside.scan()
        with connect(inside.directory, rows=True) as db:
            self.assertEqual([row[0] for row in db.execute('SELECT path FROM files')], ['one.png'])


class BudgetTests(unittest.TestCase):
    def test_holds_that_do_not_fit_together_take_turns(self):
        budget, first_held, overlapped = Budget(10), threading.Event(), []

        def second():
            first_held.wait()
            with budget.hold(8):
                overlapped.append(budget.used)
        thread = threading.Thread(target=second)
        thread.start()
        with budget.hold(8):
            first_held.set()
            thread.join(0.1)
            self.assertTrue(thread.is_alive())
        thread.join()
        self.assertEqual((overlapped, budget.used), ([8], 0))

    def test_a_hold_larger_than_the_budget_runs_alone(self):
        budget = Budget(10)
        with budget.hold(25):
            self.assertEqual(budget.used, 10)
        self.assertEqual(budget.used, 0)


if __name__ == '__main__':
    unittest.main()
