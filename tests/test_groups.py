from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageFilter

from server.groups import THRESHOLD, Groups, gather, sharpness, stem
from server.scanner import Scanner, thumbnail_path
from server.semantic import MODEL, Encoder, SemanticIndex


def turned(degrees):
    """A unit vector in the plane of the first two axes; two of them have cosine similarity cos(angle between)."""
    vector = np.zeros(8, dtype='<f4')
    vector[0], vector[1] = np.cos(np.radians(degrees)), np.sin(np.radians(degrees))
    return vector


def checkerboard(size=64):
    return Image.fromarray((np.indices((size, size)).sum(axis=0) % 2 * 255).astype(np.uint8)).convert('RGB')


class GatherTests(unittest.TestCase):
    def test_bursts_group_and_different_shots_stay_apart(self):
        matrix = np.stack([turned(0), turned(5), turned(10), turned(60)])
        centres = gather(matrix)
        self.assertEqual(len(set(centres[:3])), 1)
        self.assertEqual(centres[3], 3)

    def test_a_slow_series_does_not_chain_into_one_group(self):
        # Each step is a near-duplicate of the next (cos 10° ≈ 0.985), but the ends are far apart.
        matrix = np.stack([turned(10 * step) for step in range(7)])
        centres = gather(matrix)
        for index, centre in enumerate(centres):
            self.assertGreaterEqual(float(matrix[index] @ matrix[centre]), THRESHOLD)
        self.assertGreater(len(set(centres)), 1)


class FamilyTests(unittest.TestCase):
    def test_size_and_copy_suffixes_share_a_stem_within_one_folder(self):
        for path in ('a/Salt-Crust-150x150.jpg', 'a/salt-crust-800x400.bk.jpg', 'a/salt-crust.jpg.webp', 'a/salt-crust@2x.png',
                     'a/salt-crust-scaled.jpg', 'a/salt-crust (1).jpg', 'a/salt-crust copy 2.jpg'):
            with self.subTest(path=path):
                self.assertEqual(stem(path), 'a/salt-crust')
        self.assertNotEqual(stem('b/salt-crust.jpg'), stem('a/salt-crust.jpg'))
        self.assertNotEqual(stem('a/salt-crust-2.jpg'), stem('a/salt-crust.jpg'))

    def test_named_versions_group_when_they_look_related_but_not_otherwise(self):
        crop, original, unrelated = turned(0), turned(40), turned(130)
        centres = gather(np.stack([crop, original, unrelated]), related=[[0, 1, 2]])
        self.assertEqual(centres[0], centres[1])
        self.assertEqual(centres[2], 2)
        self.assertNotEqual(*gather(np.stack([crop, original])))


class SharpnessTests(unittest.TestCase):
    def test_blur_lowers_sharpness_and_size_alone_does_not_raise_it(self):
        with tempfile.TemporaryDirectory() as directory:
            crisp, blurred, small = (Path(directory) / name for name in ('crisp.webp', 'blurred.webp', 'small.webp'))
            image = checkerboard().resize((512, 512), Image.Resampling.NEAREST)
            image.save(crisp, 'WEBP', lossless=True)
            image.filter(ImageFilter.GaussianBlur(4)).save(blurred, 'WEBP', lossless=True)
            image.resize((128, 128), Image.Resampling.BILINEAR).save(small, 'WEBP', lossless=True)
            self.assertGreater(sharpness(crisp), 5 * sharpness(blurred))
            self.assertGreater(sharpness(crisp), sharpness(small))


class GroupsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.scanner = Scanner(self.directory / 'photos', self.directory)
        self.semantic = SemanticIndex(self.directory, Encoder(self.directory / 'models'))
        self.groups = Groups(self.directory, self.semantic)

    def add(self, number, vector, image, width=32):
        image_id = f'{number:064x}'
        image.save(thumbnail_path(self.directory, image_id), 'WEBP', lossless=True)
        with self.scanner.connect() as db:
            db.execute('INSERT INTO images VALUES (?,?,?,?,?,?,?)', (image_id, width, width, 'image/jpeg', 100, None, None))
            db.execute('INSERT INTO semantic_embeddings VALUES (?,?,?)', (image_id, MODEL, vector.tobytes()))
        return image_id

    def stored(self):
        with self.scanner.connect() as db:
            return {row['image_id']: (row['group_id'], row['score']) for row in db.execute('SELECT * FROM image_groups')}

    def test_only_near_duplicates_are_stored_and_the_sharpest_scores_highest(self):
        blurry = self.add(1, turned(0), checkerboard().filter(ImageFilter.GaussianBlur(2)))
        crisp = self.add(2, turned(3), checkerboard())
        alone = self.add(3, turned(80), checkerboard())
        self.assertTrue(self.groups.update())
        stored = self.stored()
        self.assertEqual(set(stored), {blurry, crisp})
        self.assertEqual(stored[blurry][0], stored[crisp][0])
        self.assertGreater(stored[crisp][1], stored[blurry][1])
        self.assertNotIn(alone, stored)

    def test_regrouping_only_when_embeddings_change(self):
        self.add(1, turned(0), checkerboard())
        self.add(2, turned(3), checkerboard())
        self.assertTrue(self.groups.update())
        self.assertFalse(self.groups.update())
        self.add(3, turned(90), checkerboard())
        self.assertFalse(self.groups.update(), 'a new image with no near-duplicates leaves every group as it was')
        self.add(4, turned(1), checkerboard())
        self.assertTrue(self.groups.update())
        self.assertEqual(len(self.stored()), 3)

    def test_the_larger_of_two_equally_sharp_copies_scores_higher(self):
        small = self.add(1, turned(0), checkerboard(), width=600)
        large = self.add(2, turned(1), checkerboard(), width=4000)
        self.groups.update()
        stored = self.stored()
        self.assertGreater(stored[large][1], stored[small][1])


if __name__ == '__main__':
    unittest.main()
