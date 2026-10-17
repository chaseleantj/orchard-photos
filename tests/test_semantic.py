from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from server.scanner import thumbnail_path
from server.semantic import DOWNLOAD_BYTES, FILES, IMAGE_MEAN, IMAGE_SIZE, IMAGE_STD, MODEL, REVISION, Encoder, SemanticIndex, _pixels


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
        for name in FILES[:-1]:
            (snapshot / name).parent.mkdir(parents=True, exist_ok=True)
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

    def test_a_finished_download_removes_the_old_pytorch_weights(self):
        old = self.directory / "models" / f"models--{MODEL.replace('/', '--')}" / "blobs"
        old.mkdir(parents=True)
        (old / "pytorch_model.bin").write_bytes(b"x")
        with patch("huggingface_hub.snapshot_download"):
            self.encoder._fetch()
        self.assertFalse(old.parent.exists())

    def test_a_failed_download_is_kept_for_the_status_and_cleared_on_retry(self):
        with patch.object(self.encoder, "_fetch", side_effect=RuntimeError("No connection")):
            with self.assertRaisesRegex(RuntimeError, "No connection"):
                self.encoder.load()
        self.assertEqual((self.encoder.failure, self.encoder.activity), ("No connection", None))
        with patch.object(self.encoder, "_fetch", side_effect=RuntimeError("Still no connection")):
            with self.assertRaises(RuntimeError):
                self.encoder.load()
        self.assertEqual(self.encoder.failure, "Still no connection")

    def test_images_are_resized_and_centre_cropped_like_clip(self):
        wide = Image.new("RGB", (900, 300), (255, 0, 0))
        wide.paste((128, 128, 128), (300, 0, 600, 300))
        pixels = _pixels(wide)
        self.assertEqual(pixels.shape, (3, IMAGE_SIZE, IMAGE_SIZE))
        grey = (128 / 255 - np.array(IMAGE_MEAN)) / np.array(IMAGE_STD)
        np.testing.assert_allclose(pixels[:, 10:-10, 10:-10].mean(axis=(1, 2)), grey, atol=1e-3)
        self.assertEqual(_pixels(Image.new("RGB", (5, 2000))).shape, (3, IMAGE_SIZE, IMAGE_SIZE))

    def test_features_run_the_matching_encoder_and_return_unit_vectors(self):
        self.encoder._vision = Mock(**{"run.return_value": [np.array([[3.0, 4.0]], dtype=np.float32)]})
        self.encoder._text = Mock(**{"run.return_value": [np.array([[0.0, 2.0], [5.0, 0.0]], dtype=np.float32)]})
        self.encoder._tokenizer = Mock(**{"encode_batch.return_value": [SimpleNamespace(ids=[1, 2, 3]), SimpleNamespace(ids=[1, 3, 3])]})
        np.testing.assert_allclose(self.encoder.features(images=[Image.new("RGB", (300, 200))]), [[0.6, 0.8]])
        self.assertEqual(self.encoder._vision.run.call_args.args[1]["pixel_values"].shape, (1, 3, IMAGE_SIZE, IMAGE_SIZE))
        np.testing.assert_allclose(self.encoder.features(text=["a cat", "a dog"]), [[0, 1], [1, 0]])
        tokens = self.encoder._text.run.call_args.args[1]["input_ids"]
        self.assertEqual((tokens.dtype, tokens.tolist()), (np.int64, [[1, 2, 3], [1, 3, 3]]))

    def test_model_failure_is_reported_and_can_be_retried(self):
        self.add("1")
        with patch.object(self.encoder, "load", side_effect=RuntimeError("Download unavailable")), self.assertLogs("server.semantic", level="ERROR"):
            self.search.index()
        self.assertEqual(self.search.status()["state"], "error")
        with self.assertRaisesRegex(RuntimeError, "Download unavailable"):
            self.search.search(text="a sunset")
        self.assertFalse(self.search._index_lock.locked())

    def test_a_missing_windows_runtime_is_named_with_its_install_command(self):
        from server.semantic import _missing

        error = ImportError("DLL load failed while importing onnxruntime_pybind11_state: The specified module could not be found.")
        with patch("server.semantic.sys.platform", "win32"), patch("server.semantic.platform.machine", return_value="AMD64"):
            self.assertIn("winget install Microsoft.VCRedist.2015+.x64", _missing(error))
        self.assertIn("Python dependencies", _missing(ImportError("No module named 'onnxruntime'")))

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
