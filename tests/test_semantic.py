from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from server.scanner import thumbnail_path
from server.semantic import DOWNLOAD_BYTES, FILES, MODEL, REVISION, Encoder, SemanticIndex


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.encoder = Encoder(self.directory / "models")
        self.search = SemanticIndex(self.directory, self.encoder)
        with closing(sqlite3.connect(self.search.database)) as connection, connection:
            connection.execute("CREATE TABLE images (id TEXT PRIMARY KEY)")

    def add(self, *ids, readable=True):
        thumbnail_path(self.directory, "x").parent.mkdir(exist_ok=True)
        with closing(sqlite3.connect(self.search.database)) as connection, connection:
            for image_id in ids:
                if readable:
                    Image.new("RGB", (8, 8), (len(image_id), 0, 0)).save(thumbnail_path(self.directory, image_id), "WEBP")
                connection.execute("INSERT INTO images VALUES (?)", (image_id,))

    def test_empty_folder_and_invalid_queries_do_not_download_a_model(self):
        self.assertEqual(self.search.status(), {"state": "idle", "indexed": 0, "total": 0, "downloaded": False})
        self.search.index()
        self.assertEqual(self.search.status()["state"], "ready")
        for arguments in ({}, {"text": "cat", "image_id": "one"}):
            with self.assertRaises(ValueError):
                self.search.search(**arguments)
        self.assertEqual(self.search.search(text="a sunset"), [])
        self.assertFalse((self.directory / "models").exists())

    def test_downloaded_weights_are_recognised_only_when_complete(self):
        snapshot = self.encoder.repository / "snapshots" / REVISION
        snapshot.mkdir(parents=True)
        for name in FILES[:-1]:
            (snapshot / name).write_text("{}")
        self.assertFalse(self.encoder.downloaded())
        (snapshot / FILES[-1]).write_text("{}")
        self.assertTrue(self.encoder.downloaded())

    def test_download_progress_and_failure_are_reported_between_runs(self):
        self.add("1")
        blobs = self.encoder.repository / "blobs"
        blobs.mkdir(parents=True)
        (blobs / "weights.incomplete").write_bytes(b"x" * 1000)
        self.encoder.activity = "downloading"
        status = self.search.status()
        self.assertEqual((status["state"], status["received"], status["size"]), ("downloading", 1000, DOWNLOAD_BYTES))
        self.encoder.activity, self.encoder.failure = None, "The search model could not download."
        self.assertEqual((self.search.status()["state"], self.search.status()["error"]), ("error", "The search model could not download."))

    def test_a_failed_download_is_kept_for_the_status_and_cleared_on_retry(self):
        with patch.object(self.encoder, "_fetch", side_effect=RuntimeError("No connection")):
            with self.assertRaisesRegex(RuntimeError, "No connection"):
                self.encoder.load()
        self.assertEqual((self.encoder.failure, self.encoder.activity), ("No connection", None))
        with patch.object(self.encoder, "_fetch", side_effect=RuntimeError("Still no connection")):
            with self.assertRaises(RuntimeError):
                self.encoder.load()
        self.assertEqual(self.encoder.failure, "Still no connection")

    def test_model_failure_is_reported_and_can_be_retried(self):
        self.add("1")
        with patch.object(self.encoder, "load", side_effect=RuntimeError("Download unavailable")), self.assertLogs("server.semantic", level="ERROR"):
            self.search.index()
        self.assertEqual(self.search.status()["state"], "error")
        with self.assertRaisesRegex(RuntimeError, "Download unavailable"):
            self.search.search(text="a sunset")
        self.assertFalse(self.search._index_lock.locked())

    def test_index_is_incremental_and_persistent_and_ignores_deleted_images(self):
        self.add("1", "2")
        with patch.object(self.encoder, "load"), patch.object(self.encoder, "features", return_value=np.eye(2, dtype=np.float32)) as encode:
            self.search.index()
            self.search.index()
            self.assertEqual(encode.call_count, 1)
        reopened = SemanticIndex(self.directory, self.encoder)
        self.assertEqual(reopened.status()["indexed"], 2)
        self.assertEqual(reopened.status()["state"], "ready")
        self.assertEqual(reopened.search(image_id="2"), [("2", 1.0), ("1", 0.0)])
        with closing(sqlite3.connect(self.search.database)) as connection, connection:
            connection.execute("DELETE FROM images WHERE id = '1'")
        self.assertEqual(reopened.search(image_id="2"), [("2", 1.0)])
        with patch.object(self.encoder, "load") as load:
            reopened.index()
            load.assert_not_called()
        with closing(sqlite3.connect(self.search.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM semantic_embeddings WHERE model=?", (MODEL,)).fetchone()[0], 1)

    def test_unreadable_image_is_reported_without_discarding_good_images(self):
        self.add("1")
        self.add("2", readable=False)
        with patch.object(self.encoder, "load"), patch.object(self.encoder, "features", return_value=np.array([[1, 0]], dtype=np.float32)):
            self.search.index()
        status = self.search.status()
        self.assertEqual((status["indexed"], status["total"]), (1, 2))
        self.assertIn("1 image", status["error"])
        self.assertEqual(self.search.search(image_id="1"), [("1", 1.0)])

    def test_indexing_stops_when_cancelled(self):
        self.add(*[str(n) for n in range(40)])
        with patch.object(self.encoder, "load"), patch.object(self.encoder, "features", return_value=np.eye(16, dtype=np.float32)) as encode:
            self.search.index(cancelled=lambda: encode.call_count >= 1)
        self.assertEqual(self.search.status()["indexed"], 16)

    def test_folders_share_one_encoder_but_keep_their_own_embeddings(self):
        (self.directory / "other").mkdir()
        other = SemanticIndex(self.directory / "other", self.encoder)
        with closing(sqlite3.connect(other.database)) as connection, connection:
            connection.execute("CREATE TABLE images (id TEXT PRIMARY KEY)")
        self.add("1")
        with patch.object(self.encoder, "load"), patch.object(self.encoder, "features", return_value=np.array([[1, 0]], dtype=np.float32)):
            self.search.index()
        self.assertEqual((self.search.status()["indexed"], other.status()["indexed"]), (1, 0))
        self.assertIs(other.encoder, self.search.encoder)


if __name__ == "__main__":
    unittest.main()
