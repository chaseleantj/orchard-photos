"""Private, on-device CLIP search. One encoder is shared by every folder; each folder keeps its own embeddings."""

from contextlib import contextmanager
from io import BytesIO
import logging
import os
from pathlib import Path
import sqlite3
import threading

from server.scanner import thumbnail_path

MODEL = "openai/clip-vit-base-patch32"
# A fixed revision, so every install runs the same weights and a finished download can be recognised on disk.
REVISION = "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268"
# Only what CLIP needs in PyTorch: the repository also holds TensorFlow and Flax copies of the weights.
FILES = ["config.json", "preprocessor_config.json", "pytorch_model.bin", "merges.txt", "vocab.json", "tokenizer.json",
         "tokenizer_config.json", "special_tokens_map.json"]
DOWNLOAD_BYTES = 608_863_580
BATCH_SIZE = 16
logger = logging.getLogger(__name__)


class Encoder:
    """Downloads CLIP once, loads it on first use, and turns images and text into unit vectors.

    `activity` says what it is doing for the status line ("downloading" or "loading"), and `failure` why the last
    attempt failed. Both belong to the encoder, so they are the same whichever folder is open."""

    def __init__(self, cache: Path):
        self.cache = Path(cache)
        self.repository = self.cache / f"models--{MODEL.replace('/', '--')}"
        self.lock = threading.RLock()
        self.activity = None
        self.failure = None
        self._model = None
        self._processor = None
        self._torch = None
        self._device = "cpu"

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def downloaded(self) -> bool:
        """Whether every file is on disk, so indexing needs no download and can start on its own."""
        snapshot = self.repository / "snapshots" / REVISION
        return all((snapshot / name).is_file() for name in FILES)

    def received(self) -> int:
        """Bytes downloaded so far, partial files included."""
        try:
            with os.scandir(self.repository / "blobs") as entries:
                return min(DOWNLOAD_BYTES, sum(entry.stat().st_size for entry in entries if entry.is_file()))
        except OSError:
            return 0

    def _fetch(self):
        self.activity = "downloading"
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(MODEL, revision=REVISION, cache_dir=self.cache, allow_patterns=FILES)
        except ImportError as error:
            raise RuntimeError("Visual search needs its Python dependencies. Run the setup command and retry.") from error
        except Exception as error:
            raise RuntimeError("The search model could not download. Check your internet connection, then try again.") from error

    def load(self):
        """Download the weights if they are missing, then load them. Raises RuntimeError with a message to show."""
        with self.lock:
            if self._model is not None:
                return
            self.failure = None
            self.cache.mkdir(parents=True, exist_ok=True)
            # Keep all downloaded weights and ancillary caches in the app's data folder.
            os.environ["HF_HOME"] = str(self.cache)
            os.environ["HF_HUB_CACHE"] = str(self.cache)
            os.environ["HF_XET_CACHE"] = str(self.cache / "xet")
            os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
            os.environ["HF_HUB_DISABLE_XET"] = "1"
            try:
                if not self.downloaded():
                    self._fetch()
                self.activity = "loading"
                try:
                    import torch
                    from transformers import CLIPModel, CLIPProcessor
                except ImportError as error:
                    raise RuntimeError("Visual search needs its Python dependencies. Run the setup command and retry.") from error
                self._torch = torch
                self._device = "mps" if torch.backends.mps.is_available() else "cpu"
                try:
                    # Loading only from disk also stops Transformers fetching a converted copy of the weights.
                    options = {"cache_dir": self.cache, "revision": REVISION, "local_files_only": True}
                    processor = CLIPProcessor.from_pretrained(MODEL, **options)
                    model = CLIPModel.from_pretrained(MODEL, use_safetensors=False, **options).to(self._device).eval()
                except Exception as error:
                    raise RuntimeError("The search model could not load. Retry, or delete the models folder to download it again.") from error
                self._processor, self._model = processor, model
            except RuntimeError as error:
                self.failure = str(error)
                raise
            finally:
                self.activity = None

    def features(self, *, images=None, text=None):
        with self.lock:
            self.load()
            inputs = self._processor(
                images=images, text=text, return_tensors="pt",
                **({"padding": True, "truncation": True, "max_length": 77} if text is not None else {}),
            ).to(self._device)
            with self._torch.inference_mode():
                if images is not None:
                    features = self._model.get_image_features(**inputs)
                else:
                    features = self._model.get_text_features(**inputs)
                # Transformers 5 returns a model output; 4 returned the projected tensor.
                if hasattr(features, "pooler_output"):
                    features = features.pooler_output
                features = features / features.norm(dim=-1, keepdim=True).clamp_min(1e-12)
            return features.cpu().float().numpy()

    def warm(self):
        """Load the model ahead of the first query. No-op until the weights have been downloaded."""
        if not self.downloaded():
            return
        try:
            self.features(text=["warm up"])
        except Exception:
            logger.exception("Visual search warm-up failed")


class SemanticIndex:
    """The embeddings of one folder's images, stored next to its library."""

    def __init__(self, directory: Path, encoder: Encoder):
        self.directory = Path(directory)
        self.database = self.directory / "library.sqlite"
        self.encoder = encoder
        self._index_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._state = "idle"
        self._error = None
        self._matrix = None
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS semantic_embeddings (
                    image_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    PRIMARY KEY (image_id, model)
                )
            """)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _set_state(self, state, error=None):
        with self._state_lock:
            self._state, self._error = state, error

    def status(self) -> dict:
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='images'"
            ).fetchone()
            total = connection.execute("SELECT COUNT(*) FROM images").fetchone()[0] if exists else 0
            indexed = connection.execute("""
                SELECT COUNT(*) FROM semantic_embeddings e
                JOIN images i ON i.id = e.image_id WHERE e.model = ?
            """, (MODEL,)).fetchone()[0] if exists else 0
        with self._state_lock:
            state, error = self._state, self._error
        if state == "idle" and total and indexed == total:
            state = "ready"
        # Between runs, the shared encoder says whether the model is downloading, loading, or failed to.
        if state == "idle" and self.encoder.activity:
            state = self.encoder.activity
        elif state == "idle" and self.encoder.failure:
            state, error = "error", self.encoder.failure
        result = {"state": state, "indexed": indexed, "total": total, "downloaded": self.encoder.downloaded()}
        if state == "downloading":
            result["received"], result["size"] = self.encoder.received(), DOWNLOAD_BYTES
        if error:
            result["error"] = error
        return result

    def _open_image(self, image_id):
        from PIL import Image

        with Image.open(thumbnail_path(self.directory, image_id)) as image:
            return image.convert("RGB")

    def index(self, cancelled=lambda: False):
        """Incrementally embed new images. Safe to call from a background worker."""
        if not self._index_lock.acquire(blocking=False):
            return
        try:
            self._set_state("idle")
            if self.status()["total"] == 0:
                self._set_state("ready")
                return
            with self._connect() as connection:
                connection.execute("""
                    DELETE FROM semantic_embeddings WHERE image_id NOT IN (SELECT id FROM images)
                """)
                pending = [row[0] for row in connection.execute("""
                    SELECT i.id FROM images i
                    LEFT JOIN semantic_embeddings e ON i.id = e.image_id AND e.model = ?
                    WHERE e.image_id IS NULL
                """, (MODEL,))]
            if not pending:
                self._set_state("ready")
                return
            self.encoder.load()
            self._set_state("indexing")
            failed = 0
            for offset in range(0, len(pending), BATCH_SIZE):
                if cancelled():
                    self._set_state("idle")
                    return
                images, ids = [], []
                for image_id in pending[offset:offset + BATCH_SIZE]:
                    try:
                        images.append(self._open_image(image_id))
                        ids.append(image_id)
                    except (OSError, ValueError):
                        failed += 1
                        logger.warning("Could not read image %s for visual search", image_id)
                if not images:
                    continue
                try:
                    vectors = self.encoder.features(images=images)
                    with self._connect() as connection:
                        connection.executemany(
                            "INSERT OR REPLACE INTO semantic_embeddings VALUES (?, ?, ?)",
                            [(image_id, MODEL, vector.astype("<f4").tobytes()) for image_id, vector in zip(ids, vectors)],
                        )
                finally:
                    for image in images:
                        image.close()
            self._set_state("ready", f"{failed} {'image' if failed == 1 else 'images'} could not be read for visual search." if failed else None)
        except Exception as error:
            logger.exception("Visual search indexing failed")
            self._set_state("error", str(error))
        finally:
            self._index_lock.release()

    def embeddings(self):
        """Return (ids, matrix) for indexed images, reloading only when the embeddings table changed."""
        import numpy

        with self._connect() as connection:
            # INSERT OR REPLACE assigns a new rowid, so (count, max rowid) changes on any write.
            # Images can be removed without touching embeddings, so key on both tables.
            version = connection.execute("""
                SELECT (SELECT COUNT(*) FROM semantic_embeddings), (SELECT MAX(rowid) FROM semantic_embeddings),
                       (SELECT COUNT(*) FROM images), (SELECT MAX(rowid) FROM images)
            """).fetchone()
            cached = self._matrix
            if cached and cached[0] == version:
                return cached[1], cached[2]
            rows = connection.execute("""
                SELECT e.image_id, e.vector FROM semantic_embeddings e
                JOIN images i ON i.id = e.image_id WHERE e.model = ?
            """, (MODEL,)).fetchall()
        ids = [identifier for identifier, _ in rows]
        matrix = numpy.stack([numpy.frombuffer(vector, dtype="<f4") for _, vector in rows]) if rows else None
        self._matrix = (version, ids, matrix)
        return ids, matrix

    def search(self, text: str = "", image_id: str = "", image_bytes: bytes | None = None) -> list[tuple[str, float]]:
        """Return every indexed image ranked by cosine similarity, best first."""
        import numpy

        if sum((bool(text.strip()), bool(image_id), image_bytes is not None)) != 1:
            raise ValueError("Provide one text query or one reference image.")
        status = self.status()
        if status["total"] == 0:
            return []
        ids, matrix = self.embeddings()
        if not ids:
            raise RuntimeError(status.get("error", "Visual search is preparing your images. Please try again shortly."))
        try:
            if image_id:
                if image_id not in ids:
                    raise ValueError
                query = matrix[ids.index(image_id)]
            elif image_bytes is not None:
                from PIL import Image, ImageOps
                with Image.open(BytesIO(image_bytes)) as source:
                    image = ImageOps.exif_transpose(source).convert("RGB")
                try:
                    query = self.encoder.features(images=[image])[0]
                finally:
                    image.close()
            else:
                query = self.encoder.features(text=[text.strip()])[0]
        except (ValueError, OSError):
            raise ValueError("The reference image could not be read or is not indexed yet.")
        except Exception as error:
            self._set_state("error", str(error))
            raise
        scores = matrix @ query
        order = numpy.argsort(-scores, kind="stable")
        return [(ids[index], float(scores[index])) for index in order]
