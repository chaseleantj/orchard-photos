from contextlib import closing
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from server.layout import Layout
from server.semantic import MODEL, Encoder, SemanticIndex


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.search = SemanticIndex(Path(self.directory.name), Encoder(Path(self.directory.name) / "models"))
        self.layout = Layout(self.search)
        rng = np.random.default_rng(5)
        self.centres = np.linalg.qr(rng.normal(size=(16, 16)))[0][:3]
        with closing(sqlite3.connect(self.search.database)) as connection, connection:
            connection.execute("CREATE TABLE images (id TEXT PRIMARY KEY)")
        self.count = 0
        for cluster in range(3):
            for _ in range(40):
                self.add(cluster)

    def add(self, cluster):
        vector = self.centres[cluster] + np.random.default_rng(self.count).normal(scale=0.05, size=16)
        vector = (vector / np.linalg.norm(vector)).astype("<f4")
        identifier = f"{self.count:08x}"
        with closing(sqlite3.connect(self.search.database)) as connection, connection:
            connection.execute("INSERT INTO images VALUES (?)", (identifier,))
            connection.execute("INSERT INTO semantic_embeddings VALUES (?, ?, ?)", (identifier, MODEL, vector.tobytes()))
        self.count += 1
        return identifier

    def fit(self):
        self.assertTrue(self.layout.start())
        while self.layout.status()["state"] == "computing":
            time.sleep(0.05)
        self.assertEqual(self.layout.status()["state"], "idle")

    def test_nothing_is_positioned_until_the_first_fit(self):
        self.assertIsNone(self.layout.positions())

    def test_fit_separates_clusters_and_persists(self):
        self.fit()
        first = self.layout.positions()
        points = np.array([first[f"{n:08x}"] for n in range(120)])
        self.assertLessEqual(np.percentile(np.abs(points).max(axis=1), 99), 1.0 + 1e-6)
        centres = [points[c * 40:(c + 1) * 40].mean(axis=0) for c in range(3)]
        spread = max(points[c * 40:(c + 1) * 40].std(axis=0).max() for c in range(3))
        self.assertTrue(all(np.linalg.norm(centres[a] - centres[b]) > 2 * spread for a in range(3) for b in range(a)))
        self.assertEqual(Layout(self.search).positions(), first)

    def test_new_images_join_their_neighbours_without_moving_the_rest(self):
        self.fit()
        before = self.layout.positions()
        newcomer = self.add(1)
        after = self.layout.positions()
        self.assertEqual({key: after[key] for key in before}, before)
        cluster = np.array([before[f"{n:08x}"] for n in range(40, 80)])
        self.assertLess(np.linalg.norm(np.array(after[newcomer]) - cluster.mean(axis=0)), 3 * cluster.std(axis=0).max() + 0.05)
        self.assertEqual(self.layout.status()["state"], "idle")

    def test_a_flood_of_new_images_triggers_a_refit(self):
        self.fit()
        self.layout.positions()
        for _ in range(40):
            self.add(2)
        self.layout.positions()
        while self.layout.status()["state"] == "computing":
            time.sleep(0.05)
        with closing(sqlite3.connect(self.search.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM umap_positions WHERE fitted=1").fetchone()[0], 160)

    def test_tiny_folders_still_get_positions(self):
        with closing(sqlite3.connect(self.search.database)) as connection, connection:
            connection.execute("DELETE FROM images WHERE id >= '00000005'")
        self.fit()
        self.assertEqual(set(self.layout.positions()), {f"{n:08x}" for n in range(5)})
