"""Private, on-device CLIP search. One encoder is shared by every folder; each folder keeps its own embeddings."""

from contextlib import contextmanager
from io import BytesIO
import logging
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import sys
import threading

from server.scanner import thumbnail_path

# The embedding space. Stored vectors are keyed by it, so they stay valid for as long as the weights are CLIP's own.
MODEL = "openai/clip-vit-base-patch32"
# MODEL's weights exported to ONNX, which give the same vectors as the PyTorch original.
# A fixed revision, so every install runs the same weights and a finished download can be recognised on disk.
REPOSITORY = "Xenova/clip-vit-base-patch32"
REVISION = "d15189d7028b43f1d3e65039190477f6af591c2a"
# Only the full-precision encoders: the repository also holds a combined model and smaller, less faithful copies.
FILES = ["onnx/vision_model.onnx", "onnx/text_model.onnx", "tokenizer.json"]
DOWNLOAD_BYTES = 607_968_381
# CLIP's inputs: square images normalised per channel, and descriptions of up to 77 tokens.
IMAGE_SIZE = 224
IMAGE_MEAN = (0.48145466, 0.4578275, 0.40821073)
IMAGE_STD = (0.26862954, 0.26130258, 0.27577711)
MAX_TOKENS = 77
END_OF_TEXT = "<|endoftext|>"
BATCH_SIZE = 16
logger = logging.getLogger(__name__)


class Encoder:
    """Downloads CLIP once, loads it on first use, and turns images and text into unit vectors.

    `activity` says what it is doing for the status line ("downloading" or "loading"), and `failure` why the last
    attempt failed. Both belong to the encoder, so they are the same whichever folder is open."""

    def __init__(self, cache: Path):
        self.cache = Path(cache)
        self.repository = self.cache / f"models--{REPOSITORY.replace('/', '--')}"
        self.lock = threading.RLock()
        self.activity = None
        self.failure = None
        self._vision = None
        self._text = None
        self._tokenizer = None

    @property
    def loaded(self) -> bool:
        return self._vision is not None

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
            snapshot_download(REPOSITORY, revision=REVISION, cache_dir=self.cache, allow_patterns=FILES)
        except ImportError as error:
            raise RuntimeError("Visual search needs its Python dependencies. Run the setup command and retry.") from error
        except Exception as error:
            raise RuntimeError("The search model could not download. Check your internet connection, then try again.") from error
        # Earlier versions ran the PyTorch copy of the weights, which nothing reads any more.
        shutil.rmtree(self.cache / f"models--{MODEL.replace('/', '--')}", ignore_errors=True)

    def load(self):
        """Download the weights if they are missing, then load them. Raises RuntimeError with a message to show."""
        with self.lock:
            if self._vision is not None:
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
                    import onnxruntime
                    from tokenizers import Tokenizer
                except ImportError as error:
                    raise RuntimeError(_missing(error)) from error
                # CUDA when onnxruntime-gpu is installed. Core ML is left out: measured on Apple Silicon, it ran no faster than the CPU.
                providers = [name for name in ("CUDAExecutionProvider", "CPUExecutionProvider")
                             if name in onnxruntime.get_available_providers()]
                snapshot = self.repository / "snapshots" / REVISION
                try:
                    vision = onnxruntime.InferenceSession(str(snapshot / "onnx" / "vision_model.onnx"), providers=providers)
                    text = onnxruntime.InferenceSession(str(snapshot / "onnx" / "text_model.onnx"), providers=providers)
                    tokenizer = Tokenizer.from_file(str(snapshot / "tokenizer.json"))
                except Exception as error:
                    raise RuntimeError("The search model could not load. Retry, or delete the models folder to download it again.") from error
                tokenizer.enable_truncation(MAX_TOKENS)
                # The text model reads each description up to its first end token, so padding with more of them changes nothing.
                tokenizer.enable_padding(pad_id=tokenizer.token_to_id(END_OF_TEXT), pad_token=END_OF_TEXT)
                self._vision, self._text, self._tokenizer = vision, text, tokenizer
            except RuntimeError as error:
                self.failure = str(error)
                raise
            finally:
                self.activity = None

    def features(self, *, images=None, text=None):
        import numpy

        with self.lock:
            self.load()
            if images is not None:
                pixels = numpy.stack([_pixels(image) for image in images])
                features = self._vision.run(None, {"pixel_values": pixels})[0]
            else:
                tokens = numpy.array([encoding.ids for encoding in self._tokenizer.encode_batch(text)], dtype=numpy.int64)
                features = self._text.run(None, {"input_ids": tokens})[0]
            return features / numpy.maximum(numpy.linalg.norm(features, axis=-1, keepdims=True), 1e-12)

    def warm(self):
        """Load the model ahead of the first query. No-op until the weights have been downloaded."""
        if not self.downloaded():
            return
        try:
            self.features(text=["warm up"])
        except Exception:
            logger.exception("Visual search warm-up failed")


def _missing(error: ImportError) -> str:
    """What to install when ONNX Runtime or the tokenizer can't be imported.

    On Windows, ONNX Runtime also needs Microsoft's C++ runtime, which Python doesn't include."""
    if sys.platform == "win32" and "DLL load failed" in str(error):
        machine = "arm64" if platform.machine().lower() == "arm64" else "x64"
        return ("Visual search needs the Microsoft Visual C++ Redistributable. Install it with: "
                f"winget install Microsoft.VCRedist.2015+.{machine}, then restart Orchard.")
    return "Visual search needs its Python dependencies. Run the setup command and retry."


def _pixels(image):
    """One RGB image as CLIP's input: resized, centre-cropped and normalised, channels first."""
    import numpy
    from PIL import Image

    width, height = image.size
    # The short side becomes 224 px, and the long side is rounded down the way Transformers does it, so the crop
    # lands on the same pixels as the PyTorch original.
    long = int(IMAGE_SIZE * max(width, height) / min(width, height))
    width, height = (IMAGE_SIZE, long) if width <= height else (long, IMAGE_SIZE)
    left, top = (width - IMAGE_SIZE) // 2, (height - IMAGE_SIZE) // 2
    image = image.resize((width, height), Image.Resampling.BICUBIC).crop((left, top, left + IMAGE_SIZE, top + IMAGE_SIZE))
    pixels = numpy.asarray(image, dtype=numpy.float32) / 255
    return ((pixels - numpy.array(IMAGE_MEAN, numpy.float32)) / numpy.array(IMAGE_STD, numpy.float32)).transpose(2, 0, 1)


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
