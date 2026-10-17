from pathlib import Path
import tempfile
import unittest

from server.atlas import CELL, COLUMNS, Atlas
from server.cache import connect, thumbnail_path


class AtlasTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data = Path(self.directory.name)
        with connect(self.data) as connection:
            connection.execute("CREATE TABLE images (id TEXT PRIMARY KEY)")
        self.atlas = Atlas(self.data)

    def add(self, name, color):
        from PIL import Image

        path = thumbnail_path(self.data, name)
        path.parent.mkdir(exist_ok=True)
        Image.new("RGB", (40, 20), color).save(path, "WEBP")
        with connect(self.data) as connection:
            connection.execute("INSERT INTO images VALUES (?)", (name,))

    def test_slots_are_stable_and_only_new_images_are_drawn(self):
        from PIL import Image

        self.add("a", (255, 0, 0))
        first = self.atlas.ensure()
        self.assertEqual(first, {"a": 0})
        self.add("b", (0, 0, 255))
        second = self.atlas.ensure()
        self.assertEqual(second, {"a": 0, "b": 1})
        self.assertEqual(len(self.atlas.versions()), 1)
        with Image.open(self.atlas.sheet_path(0)) as sheet:
            sheet = sheet.convert("RGBA")
            centre = CELL // 2
            red, blue = sheet.getpixel((centre, centre)), sheet.getpixel((CELL + centre, centre))
            corner = sheet.getpixel((CELL * COLUMNS - 1, CELL * COLUMNS - 1))
        self.assertGreater(red[0], 200)
        self.assertGreater(blue[2], 200)
        self.assertEqual(corner[3], 0)

    def test_an_unreadable_image_still_gets_a_placeholder_slot(self):
        self.add("a", (1, 2, 3))
        thumbnail_path(self.data, "a").write_bytes(b"not an image")
        with self.assertLogs("server.atlas", level="WARNING"):
            self.assertEqual(self.atlas.ensure(), {"a": 0})
        self.assertEqual(len(self.atlas.versions()), 1)
