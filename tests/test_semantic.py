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
from server import semantic
from server.semantic import (CORE_ML_SHA256, CORE_ML_VISION, EARLIER, IMAGE_SIZE, MAX_TOKENS, MODEL, PARITY_VECTOR, REPOSITORY,
                             TEXT, TOKENIZER, VISION, Encoder, SemanticIndex, _files, _pixels, parity_pixels)


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        # Tests choose the engine themselves, so they behave the same on every computer. The Core ML revision names
        # a folder, so they use one of their own that any file system accepts, whatever the real one is.
        revision = patch("server.semantic.CORE_ML_REVISION", "0123456789abcdef0123456789abcdef01234567")
        revision.start()
        self.addCleanup(revision.stop)
        with patch("server.semantic.core_ml_available", return_value=False):
            self.encoder = Encoder(self.directory / "models")
        self.search = SemanticIndex(self.directory, self.encoder)
        with closing(sqlite3.connect(self.search.database)) as connection, connection:
            connection.execute("CREATE TABLE images (id TEXT PRIMARY KEY, taken TEXT)")
            connection.execute("CREATE TABLE files (path TEXT PRIMARY KEY, image_id TEXT, modified TEXT NOT NULL)")

    def add(self, *ids, readable=True, taken=None, modified="2026-01-01T00:00:00Z"):
        thumbnail_path(self.directory, "x").parent.mkdir(exist_ok=True)
        with closing(sqlite3.connect(self.search.database)) as connection, connection:
            for image_id in ids:
                if readable:
                    Image.new("RGB", (8, 8), (len(image_id), 0, 0)).save(thumbnail_path(self.directory, image_id), "WEBP")
                connection.execute("INSERT INTO images VALUES (?, ?)", (image_id, taken))
                connection.execute("INSERT INTO files VALUES (?, ?, ?)", (f"{image_id}.png", image_id, modified))

    def place(self, core_ml, content="{}"):
        """Write every file the given engine needs, with the tokenizer as `content`."""
        for file in _files(core_ml):
            path = self.encoder._path(*file)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    def test_empty_folder_and_invalid_queries_do_not_download_a_model(self):
        self.assertEqual(self.search.status(), {"state": "idle", "indexed": 0, "total": 0, "downloaded": False})
        self.search.index()
        # An empty folder has nothing to search, so visual search isn't ready there.
        self.assertEqual(self.search.status()["state"], "idle")
        for arguments in ({}, {"text": "cat", "image_id": "one"}):
            with self.assertRaises(ValueError):
                self.search.search(**arguments)
        self.assertEqual(self.search.search(text="a sunset"), [])
        self.assertFalse((self.directory / "models").exists())

    def test_downloaded_weights_are_recognised_only_when_complete(self):
        for core_ml in (False, True):
            self.encoder.core_ml = core_ml
            self.place(core_ml)
            self.encoder._path(*_files(core_ml)[-1]).unlink()
            self.assertFalse(self.encoder.downloaded())
            self.place(core_ml)
            self.assertTrue(self.encoder.downloaded())

    def test_apple_silicon_downloads_the_core_ml_image_encoder_in_place_of_the_full_precision_one(self):
        self.assertEqual(self.encoder.size, 689_793_386)
        self.encoder.core_ml = True
        self.assertEqual(self.encoder.size, 503_893_893)
        self.assertEqual([name for _, _, name in _files(True)], [CORE_ML_VISION, TEXT, TOKENIZER])
        self.assertEqual([name for _, _, name in _files(False)], [VISION, TEXT, TOKENIZER])

    def test_core_ml_is_chosen_only_where_available_and_not_after_an_earlier_fallback(self):
        def chosen(available):
            with patch("server.semantic.core_ml_available", return_value=available):
                return Encoder(self.directory / "models").core_ml
        self.assertEqual((chosen(False), chosen(True)), (False, True))
        # A Mac that fell back before has only the CPU's files, and keeps using them.
        self.place(False)
        self.assertFalse(chosen(True))
        self.place(True)
        self.assertTrue(chosen(True))

    def test_platform_check_wants_an_apple_silicon_mac_with_core_ml(self):
        providers = ["CoreMLExecutionProvider", "CPUExecutionProvider"]
        for system, machine, available, expected in [("darwin", "arm64", providers, True), ("darwin", "x86_64", providers, False),
                                                     ("linux", "arm64", providers, False), ("darwin", "arm64", providers[1:], False)]:
            with patch.object(semantic.sys, "platform", system), patch("platform.machine", return_value=machine), \
                    patch("onnxruntime.get_available_providers", return_value=available):
                self.assertEqual(semantic.core_ml_available(), expected, (system, machine, available))

    def test_download_progress_and_failure_are_reported_between_runs(self):
        self.add("1")
        blobs = self.encoder._folder(REPOSITORY) / "blobs"
        blobs.mkdir(parents=True)
        (blobs / "weights.incomplete").write_bytes(b"x" * 1000)
        self.encoder.activity = "downloading"
        status = self.search.status()
        self.assertEqual((status["state"], status["received"], status["size"]), ("downloading", 1000, self.encoder.size))
        # With Core ML, the image encoder comes from its own repository, and both count.
        self.encoder.core_ml = True
        other = self.encoder._path(*_files(True)[0]).parents[2] / "blobs"
        other.mkdir(parents=True)
        (other / "weights.incomplete").write_bytes(b"x" * 500)
        self.assertEqual(self.search.status()["received"], 1500)
        self.encoder.activity, self.encoder.failure = None, "The search model could not download."
        self.assertEqual((self.search.status()["state"], self.search.status()["error"]), ("error", "The search model could not download."))

    def test_an_earlier_model_makes_setup_an_update_until_the_download_removes_it(self):
        self.assertFalse(self.encoder.replaces())
        for repository in EARLIER:
            blobs = self.directory / "models" / f"models--{repository.replace('/', '--')}" / "blobs"
            blobs.mkdir(parents=True)
            (blobs / "weights").write_bytes(b"x")
        self.assertTrue(self.encoder.replaces())
        with patch("huggingface_hub.snapshot_download") as download:
            self.encoder._fetch()
        self.assertEqual(download.call_args.kwargs["allow_patterns"], [VISION, TEXT, TOKENIZER])
        self.assertFalse(self.encoder.replaces())
        self.assertEqual(list((self.directory / "models").iterdir()), [])

    def test_a_failed_download_keeps_the_earlier_model(self):
        earlier = self.directory / "models" / f"models--{EARLIER[-1].replace('/', '--')}"
        earlier.mkdir(parents=True)
        with patch("huggingface_hub.snapshot_download", side_effect=OSError("offline")), self.assertRaisesRegex(RuntimeError, "could not download"):
            self.encoder._fetch()
        self.assertTrue(self.encoder.replaces())

    def test_a_failed_download_is_kept_for_the_status_and_cleared_on_retry(self):
        with patch.object(self.encoder, "_fetch", side_effect=RuntimeError("No connection")):
            with self.assertRaisesRegex(RuntimeError, "No connection"):
                self.encoder.load()
        self.assertEqual((self.encoder.failure, self.encoder.activity), ("No connection", None))
        with patch.object(self.encoder, "_fetch", side_effect=RuntimeError("Still no connection")):
            with self.assertRaises(RuntimeError):
                self.encoder.load()
        self.assertEqual(self.encoder.failure, "Still no connection")

    def test_images_are_squashed_whole_into_a_square_and_scaled_to_plus_minus_one(self):
        wide = Image.new("RGB", (900, 300), (255, 0, 0))
        wide.paste((0, 0, 255), (0, 0, 300, 300))
        pixels = _pixels(wide)
        self.assertEqual((pixels.shape, pixels.dtype), ((3, IMAGE_SIZE, IMAGE_SIZE), np.float32))
        # Nothing is cropped: the blue third on the left survives, squashed to a third of the width.
        third = IMAGE_SIZE // 3
        np.testing.assert_allclose(pixels[:, :, :third - 2].mean(axis=(1, 2)), [-1, -1, 1], atol=1e-3)
        np.testing.assert_allclose(pixels[:, :, third + 2:].mean(axis=(1, 2)), [1, -1, -1], atol=1e-3)
        self.assertEqual(_pixels(Image.new("RGB", (5, 2000))).shape, (3, IMAGE_SIZE, IMAGE_SIZE))

    def test_features_run_the_matching_encoder_and_return_unit_vectors(self):
        self.encoder._vision = self.session(np.array([3.0, 4.0], dtype=np.float32))
        self.encoder._text = Mock(**{"run.return_value": [np.array([[0.0, 2.0], [5.0, 0.0]], dtype=np.float32)]})
        self.encoder._tokenizer = Mock(**{"encode_batch.return_value": [SimpleNamespace(ids=[1, 2, 3]), SimpleNamespace(ids=[1, 3, 3])]})
        np.testing.assert_allclose(self.encoder.features(images=[Image.new("RGB", (300, 200))]), [[0.6, 0.8]])
        self.assertEqual(self.encoder._vision.run.call_args.args[1]["pixel_values"].shape, (1, 3, IMAGE_SIZE, IMAGE_SIZE))
        np.testing.assert_allclose(self.encoder.features(text=["A Cat", "a dog"]), [[0, 1], [1, 0]])
        self.encoder._tokenizer.encode_batch.assert_called_once_with(["a cat", "a dog"])
        tokens = self.encoder._text.run.call_args.args[1]["input_ids"]
        self.assertEqual((tokens.dtype, tokens.tolist()), (np.int64, [[1, 2, 3], [1, 3, 3]]))
        # Each tower's pooled embedding, not its per-token states.
        self.assertEqual((self.encoder._vision.run.call_args.args[0], self.encoder._text.run.call_args.args[0]), (["pooler_output"], ["pooler_output"]))

    def test_descriptions_are_always_exactly_the_tokens_the_text_model_reads(self):
        from tokenizers import Tokenizer, models, pre_tokenizers, processors
        tokenizer = Tokenizer(models.WordLevel({"<pad>": 0, "<eos>": 1, "<unk>": 2, "a": 3, "cat": 4}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        tokenizer.post_processor = processors.TemplateProcessing(single="$A <eos>", special_tokens=[("<eos>", 1)])
        self.place(False)
        tokenizer.save(str(self.encoder._path(*_files(False)[2])))
        with patch("onnxruntime.InferenceSession"):
            self.encoder.load()
        short, long = self.encoder._tokenizer.encode_batch(["a cat", "a " * 100])
        self.assertEqual(short.ids, [3, 4, 1] + [0] * (MAX_TOKENS - 3))
        self.assertEqual((len(long.ids), long.ids[-1]), (MAX_TOKENS, 1))

    def session(self, vector=None, batch="batch_size"):
        """A stand-in ONNX Runtime session whose image encoder gives `vector` for every image."""
        vector = np.load(PARITY_VECTOR) if vector is None else vector
        session = Mock(**{"get_inputs.return_value": [SimpleNamespace(shape=[batch, 3, IMAGE_SIZE, IMAGE_SIZE])]})
        session.run.side_effect = lambda names, feed: [np.tile(vector, (len(next(iter(feed.values()))), 1))]
        return session

    def load_core_ml(self, core_ml_session):
        """Load with Core ML on and only its files present. Returns the providers each session was opened with."""
        self.encoder.core_ml = True
        self.place(True)
        opened = []

        def open_session(path, providers):
            opened.append((Path(path).name, providers))
            if isinstance(providers[0], tuple):
                return core_ml_session()
            return self.session()

        with patch("onnxruntime.InferenceSession", side_effect=open_session), patch("tokenizers.Tokenizer.from_file"), \
                patch.object(self.encoder, "_fetch", side_effect=lambda: self.place(False)) as download:
            self.encoder.load()
        return opened, download.call_count

    def test_core_ml_runs_the_image_encoder_when_it_matches_the_cpu(self):
        opened, downloads = self.load_core_ml(lambda: self.session(batch=16))
        self.assertEqual((opened[0][0], opened[0][1][0]), (CORE_ML_VISION, ("CoreMLExecutionProvider", semantic.CORE_ML_OPTIONS)))
        self.assertEqual((self.encoder.core_ml, downloads, len(opened)), (True, 0, 2))

    def test_core_ml_falls_back_to_the_cpu_and_downloads_its_encoder_when_it_fails_to_load_or_is_off(self):
        for failing in (lambda: (_ for _ in ()).throw(RuntimeError("compile failed")), lambda: self.session(-np.load(PARITY_VECTOR), 16)):
            with self.subTest(failing=failing):
                self.encoder = Encoder(self.directory / "models")
                with self.assertLogs("server.semantic", level="WARNING") as logs:
                    opened, downloads = self.load_core_ml(failing)
                self.assertIn("so the CPU runs it", logs.output[0])
                self.assertEqual((self.encoder.core_ml, downloads), (False, 1))
                self.assertEqual([name for name, _ in opened], [CORE_ML_VISION, Path(VISION).name, Path(TEXT).name])
                self.assertTrue(self.encoder.loaded)
                for core_ml in (False, True):
                    for file in _files(core_ml):
                        self.encoder._path(*file).unlink(missing_ok=True)

    def test_an_unavailable_core_ml_repository_downloads_the_cpu_encoder_instead(self):
        from huggingface_hub.errors import HFValidationError
        self.encoder.core_ml = True
        with patch("huggingface_hub.hf_hub_download", side_effect=HFValidationError("bad id")), \
                patch("huggingface_hub.snapshot_download") as download, self.assertLogs("server.semantic", level="WARNING"):
            self.encoder._fetch()
        self.assertFalse(self.encoder.core_ml)
        self.assertEqual(download.call_args.kwargs["allow_patterns"], [VISION, TEXT, TOKENIZER])

    def test_a_connection_failure_is_not_taken_for_a_missing_core_ml_repository(self):
        self.encoder.core_ml = True
        with patch("huggingface_hub.hf_hub_download", side_effect=OSError("offline")), self.assertRaisesRegex(RuntimeError, "could not download"):
            self.encoder._fetch()
        self.assertTrue(self.encoder.core_ml)

    def test_a_core_ml_download_is_checked_against_its_sha256(self):
        path = self.encoder._path(*_files(True)[0])
        content = b"the model"

        def download(*args, **kwargs):
            blob = path.parents[2] / "blobs" / "weights"
            blob.parent.mkdir(parents=True, exist_ok=True)
            blob.write_bytes(content)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.symlink_to(blob)
        with patch("huggingface_hub.hf_hub_download", side_effect=download), patch("huggingface_hub.snapshot_download") as source:
            # A file that isn't the expected one is deleted, and the CPU's encoder downloaded in its place.
            self.encoder.core_ml = True
            with self.assertLogs("server.semantic", level="WARNING"):
                self.encoder._fetch()
            self.assertFalse(self.encoder.core_ml)
            self.assertFalse(path.exists() or (path.parents[2] / "blobs" / "weights").exists())
            self.assertEqual(source.call_args.kwargs["allow_patterns"], [VISION, TEXT, TOKENIZER])
            self.encoder.core_ml = True
            with patch("server.semantic.CORE_ML_SHA256", __import__("hashlib").sha256(content).hexdigest()):
                self.encoder._fetch()
        self.assertTrue(self.encoder.core_ml and path.is_file())
        self.assertEqual(source.call_args.kwargs["allow_patterns"], [TEXT, TOKENIZER])
        self.assertEqual(len(CORE_ML_SHA256), 64)

    def test_a_core_ml_file_already_in_place_is_not_downloaded_again(self):
        self.encoder.core_ml = True
        self.encoder._path(*_files(True)[0]).parent.mkdir(parents=True)
        self.encoder._path(*_files(True)[0]).write_text("{}")
        with patch("huggingface_hub.hf_hub_download") as download, patch("huggingface_hub.snapshot_download") as source:
            self.encoder._fetch()
        download.assert_not_called()
        self.assertEqual((self.encoder.core_ml, source.call_args.kwargs["allow_patterns"]), (True, [TEXT, TOKENIZER]))

    def test_a_fixed_batch_is_padded_and_the_padding_dropped(self):
        session = self.session(batch=16)
        session.run.side_effect = lambda names, feed: [feed["pixel_values"][:, 0, 0, :2] + 1]
        pixels = np.arange(20, dtype=np.float32)[:, None, None, None] * np.ones((20, 3, 1, 2), np.float32)
        vectors = semantic._run(session, pixels)
        self.assertEqual([call.args[1]["pixel_values"].shape[0] for call in session.run.call_args_list], [16, 16])
        np.testing.assert_array_equal(vectors[:, 0], np.arange(20) + 1)

    def test_the_parity_vector_and_image_are_well_formed(self):
        self.assertEqual(np.load(PARITY_VECTOR).shape, (768,))
        np.testing.assert_allclose(np.linalg.norm(np.load(PARITY_VECTOR)), 1, atol=1e-5)
        pixels = parity_pixels()
        self.assertEqual((pixels.shape, pixels.dtype), ((3, IMAGE_SIZE, IMAGE_SIZE), np.float32))
        self.assertTrue(-1 <= pixels.min() and pixels.max() <= 1)

    def test_newest_images_are_indexed_first(self):
        self.add("old", modified="2020-01-01T00:00:00Z")
        self.add("new", modified="2026-06-01T00:00:00Z")
        self.add("photo", taken="2024-05-01T00:00:00Z", modified="2026-07-01T00:00:00Z")
        self.add("middle", modified="2023-01-01T00:00:00Z")
        # A copy of "old" written recently makes it recent.
        with closing(sqlite3.connect(self.search.database)) as connection, connection:
            connection.execute("INSERT INTO files VALUES ('copy.png', 'old', '2025-01-01T00:00:00Z')")
        order = []
        with patch.object(self.encoder, "load"), patch.object(self.encoder, "features", return_value=np.eye(4, dtype=np.float32)), \
                patch.object(self.search, "_open_image", side_effect=lambda image_id: order.append(image_id) or Image.new("RGB", (8, 8))):
            self.search.index()
        # The photo's capture date counts, not when its file was written.
        self.assertEqual(order, ["new", "old", "photo", "middle"])

    def test_vectors_from_an_earlier_model_are_discarded_and_the_folder_indexed_again(self):
        self.add("1", "2")
        with closing(sqlite3.connect(self.search.database)) as connection, connection:
            connection.executemany("INSERT INTO semantic_embeddings VALUES (?, ?, ?)",
                                   [(image_id, EARLIER[0], np.ones(512, "<f4").tobytes()) for image_id in ("1", "2")])
        self.assertEqual(self.search.status()["indexed"], 0)
        self.assertTrue(self.search.has_earlier())
        self.search.discard_earlier()
        self.assertFalse(self.search.has_earlier())
        with patch.object(self.encoder, "load"), patch.object(self.encoder, "features", return_value=np.eye(2, dtype=np.float32)) as encode:
            self.search.index()
        self.assertEqual(len(encode.call_args.kwargs["images"]), 2)
        with closing(sqlite3.connect(self.search.database)) as connection:
            self.assertEqual(connection.execute("SELECT DISTINCT model FROM semantic_embeddings").fetchall(), [(MODEL,)])

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

    def test_ready_only_once_every_image_has_a_vector_including_ones_a_scan_adds_later(self):
        # The startup run can start on a partial scan. Images the scan commits afterwards keep it from reading ready.
        self.add("1", "2")
        with patch.object(self.encoder, "load"), patch.object(self.encoder, "features", side_effect=lambda images: np.eye(len(images), 4, dtype=np.float32)):
            self.search.index()
            self.assertEqual(self.search.status()["state"], "ready")
            self.add("3", "4")
            status = self.search.status()
            self.assertEqual((status["state"], status["indexed"], status["total"]), ("idle", 2, 4))
            self.search.index()
            self.assertEqual(self.search.status()["state"], "ready")

    def test_images_a_scan_adds_while_indexing_are_indexed_in_the_same_run(self):
        self.add("1")

        def features(images):
            if self.search.status()["total"] == 1:
                self.add("2", "3")  # The scan commits another batch meanwhile.
            return np.eye(len(images), 4, dtype=np.float32)
        with patch.object(self.encoder, "load"), patch.object(self.encoder, "features", side_effect=features) as encode:
            self.search.index()
        self.assertEqual(encode.call_count, 2)
        status = self.search.status()
        self.assertEqual((status["state"], status["indexed"], status["total"]), ("ready", 3, 3))

    def test_unreadable_image_is_reported_without_discarding_good_images(self):
        self.add("1")
        self.add("2", readable=False)
        with patch.object(self.encoder, "load"), patch.object(self.encoder, "features", return_value=np.array([[1, 0]], dtype=np.float32)):
            self.search.index()
        status = self.search.status()
        self.assertEqual((status["indexed"], status["total"]), (1, 2))
        self.assertIn("1 image", status["error"])
        self.assertEqual(self.search.search(image_id="1"), [("1", 1.0)])
        # The image that can't be read doesn't hold the folder back, but a new one does.
        self.assertEqual(status["state"], "ready")
        self.add("3")
        self.assertEqual(self.search.status()["state"], "idle")

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
