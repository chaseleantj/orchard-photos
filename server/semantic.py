"""Private, on-device SigLIP 2 search. One encoder is shared by every folder; each folder keeps its own embeddings."""

import hashlib
from io import BytesIO
import logging
import os
from pathlib import Path
import platform
import sys
import threading

from server.cache import connect, thumbnail_path

# The embedding space. Vectors are stored under this key, so vectors from another model are never mixed with its own.
MODEL = "google/siglip2-base-patch16-256"
# MODEL exported to ONNX, at a fixed revision so every install runs the same weights.
REPOSITORY = "onnx-community/siglip2-base-patch16-256-ONNX"
REVISION = "d1114256522a37ffa257a0a58017348ab0058db2"
# The image encoder at full precision, and the text encoder in int8, which ranks searches as well at a quarter the size.
VISION = "onnx/vision_model.onnx"
TEXT = "onnx/text_model_int8.onnx"
TOKENIZER = "tokenizer.json"
# On Apple Silicon, the image encoder runs through Core ML: REPOSITORY's fp16 copy, rewritten by
# scripts/build-coreml-model so Core ML can compile it. Its vectors match VISION's, so they share MODEL.
CORE_ML_REPOSITORY = "ChaseLean/siglip2-base-patch16-256-coreml-fp16"
CORE_ML_REVISION = "ca75720483cf3daae26c091ab23f12e1e8a6cdb1"
CORE_ML_VISION = "vision_model_fp16_coreml.onnx"
CORE_ML_SHA256 = "87aa52ceed129728ae749782dfafb7cb4e92060f9018776040071b6d85caebc9"
# Asks for the GPU by name, since left to choose, Core ML picks the slower Neural Engine.
CORE_ML_OPTIONS = {"ModelFormat": "MLProgram", "MLComputeUnits": "CPUAndGPU"}
# On Windows x64, onnxruntime-directml runs VISION on any DirectX 12 GPU.
DIRECTML = "DmlExecutionProvider"
# A GPU is used only if its vector for a fixed test image matches the CPU's, stored here, at least this closely.
PARITY_VECTOR = Path(__file__).with_name("parity-vector.npy")
PARITY_COSINE = 0.999
SIZES = {VISION: 371_992_072, TEXT: 283_438_275, TOKENIZER: 34_363_039, CORE_ML_VISION: 186_092_579}
# SigLIP 2 reads images squashed to a square with no crop, and lowercased descriptions padded to exactly MAX_TOKENS,
# since the text encoder reads the last position.
IMAGE_SIZE = 256
IMAGE_MEAN = IMAGE_STD = 0.5
MAX_TOKENS = 64
PAD = "<pad>"
BATCH_SIZE = 16  # Also the Core ML model's fixed batch.
DEPENDENCIES_MISSING = "Visual search needs its Python dependencies. Run the setup command and retry."
logger = logging.getLogger(__name__)


class Encoder:
    """Downloads the model once, loads it on first use, and turns images and text into unit vectors.

    `activity` says what it is doing ("downloading" or "loading"), and `failure` why the last attempt failed, for
    whichever folder is open. `core_ml` says whether the image encoder runs through Core ML. It turns off once Core ML
    fails, and stays off on a Mac where that left only the CPU's files."""

    def __init__(self, cache: Path):
        self.cache = Path(cache)
        self.lock = threading.RLock()
        self.activity = None
        self.failure = None
        self._vision = None
        self._text = None
        self._tokenizer = None
        self.core_ml = core_ml_available() and (self._complete(_files(True)[:1]) or not self._complete(_files(False)))

    def _folder(self, repository):
        return self.cache / f"models--{repository.replace('/', '--')}"

    def _path(self, repository, revision, name) -> Path:
        return self._folder(repository) / "snapshots" / revision / name

    def _complete(self, files) -> bool:
        return all(self._path(*file).is_file() for file in files)

    @property
    def loaded(self) -> bool:
        return self._vision is not None

    @property
    def size(self) -> int:
        """Bytes to download, which depend on the image encoder this computer runs."""
        return sum(SIZES[name] for _, _, name in _files(self.core_ml))

    def downloaded(self) -> bool:
        """Whether every file is on disk, so indexing needs no download and can start on its own."""
        return self._complete(_files(self.core_ml))

    def received(self) -> int:
        """Bytes downloaded so far, partial files included. Finished files are measured at their snapshot path, where
        Windows, without symlinks, moves them."""
        files = _files(self.core_ml)
        partial = [blob for repository in {repository for repository, _, _ in files}
                   for blob in (self._folder(repository) / "blobs").glob("*.incomplete")]
        total = 0
        for path in [self._path(*file) for file in files] + partial:
            try:
                # Not the listing's size, which Windows keeps at 0 while the file is open for writing.
                total += path.stat().st_size
            except OSError:
                pass  # Not downloaded yet, or finished and moved since the listing.
        return min(self.size, total)

    def _fetch(self):
        self.activity = "downloading"
        try:
            from huggingface_hub import hf_hub_download, snapshot_download
            from huggingface_hub.errors import HFValidationError, RemoteEntryNotFoundError, RepositoryNotFoundError, RevisionNotFoundError
        except ImportError as error:
            raise RuntimeError(DEPENDENCIES_MISSING) from error
        try:
            if self.core_ml and not self._complete(_files(True)[:1]):
                try:
                    hf_hub_download(CORE_ML_REPOSITORY, CORE_ML_VISION, revision=CORE_ML_REVISION, cache_dir=self.cache)
                except (HFValidationError, RepositoryNotFoundError, RevisionNotFoundError, RemoteEntryNotFoundError):
                    logger.warning("The Core ML search model is not available from %s, so the CPU runs it", CORE_ML_REPOSITORY)
                    self.core_ml = False
                else:
                    self.core_ml = self._verified(self._path(*_files(True)[0]))
            snapshot_download(REPOSITORY, revision=REVISION, cache_dir=self.cache,
                              allow_patterns=[name for repository, _, name in _files(self.core_ml) if repository == REPOSITORY])
        except Exception as error:
            raise RuntimeError("The search model could not download. Check your internet connection, then try again.") from error

    @staticmethod
    def _verified(path: Path) -> bool:
        """Whether a downloaded Core ML model is the expected file. One that isn't is deleted, and the CPU runs VISION,
        since downloading it again would give the same file."""
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest == CORE_ML_SHA256:
            return True
        logger.warning("The Core ML search model has SHA-256 %s, not %s, so the CPU runs it", digest, CORE_ML_SHA256)
        blob = path.resolve()
        path.unlink()
        blob.unlink(missing_ok=True)
        return False

    def load(self):
        """Download the weights if they are missing, then load them. Raises RuntimeError with a message to show."""
        with self.lock:
            if self._vision is not None:
                return
            self.failure = None
            self.cache.mkdir(parents=True, exist_ok=True)
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
                vision = self._gpu_vision(onnxruntime)
                if vision is None and not self.downloaded():
                    self._fetch()  # Core ML failed, and the CPU's image encoder isn't here yet.
                    self.activity = "loading"
                # CUDA when onnxruntime-gpu is installed.
                providers = [name for name in ("CUDAExecutionProvider", "CPUExecutionProvider")
                             if name in onnxruntime.get_available_providers()]
                vision_file, text_file, tokenizer_file = (self._path(*file) for file in _files(self.core_ml))
                try:
                    vision = vision or onnxruntime.InferenceSession(str(vision_file), providers=providers)
                    text = onnxruntime.InferenceSession(str(text_file), providers=providers)
                    tokenizer = Tokenizer.from_file(str(tokenizer_file))
                except Exception as error:
                    raise RuntimeError("The search model could not load. Retry, or delete the models folder to download it again.") from error
                tokenizer.enable_truncation(MAX_TOKENS)
                tokenizer.enable_padding(pad_id=tokenizer.token_to_id(PAD), pad_token=PAD, length=MAX_TOKENS)
                self._vision, self._text, self._tokenizer = vision, text, tokenizer
            except RuntimeError as error:
                self.failure = str(error)
                raise
            finally:
                self.activity = None

    def _gpu_vision(self, onnxruntime):
        """The image encoder on the GPU: through Core ML on Apple Silicon, or DirectML on Windows x64. None when
        neither is available or passes the parity check, so the CPU runs it."""
        if self.core_ml:
            session = _gpu_session(onnxruntime, "Core ML", self._path(*_files(True)[0]),
                                   [("CoreMLExecutionProvider", CORE_ML_OPTIONS), "CPUExecutionProvider"])
            self.core_ml = session is not None
            return session
        if DIRECTML in onnxruntime.get_available_providers():
            # DirectML can't reuse memory patterns or run nodes in parallel.
            options = onnxruntime.SessionOptions()
            options.enable_mem_pattern = False
            options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
            return _gpu_session(onnxruntime, "DirectML", self._path(*_files(False)[0]),
                                [DIRECTML, "CPUExecutionProvider"], options)
        return None

    def features(self, *, images=None, text=None):
        import numpy

        with self.lock:
            self.load()
            if images is not None:
                features = _run(self._vision, numpy.stack([_pixels(image) for image in images]))
            else:
                lowered = [description.lower() for description in text]
                tokens = numpy.array([encoding.ids for encoding in self._tokenizer.encode_batch(lowered)], dtype=numpy.int64)
                features = self._text.run(["pooler_output"], {"input_ids": tokens})[0]
            return _unit(features)

    def warm(self):
        """Load the model ahead of the first query. No-op until the weights have been downloaded."""
        if not self.downloaded():
            return
        try:
            self.features(text=["warm up"])
        except Exception:
            logger.exception("Visual search warm-up failed")


def _files(core_ml):
    """(repository, revision, name) of each file to download, the image encoder first, with or without Core ML."""
    vision = (CORE_ML_REPOSITORY, CORE_ML_REVISION, CORE_ML_VISION) if core_ml else (REPOSITORY, REVISION, VISION)
    return [vision, (REPOSITORY, REVISION, TEXT), (REPOSITORY, REVISION, TOKENIZER)]


def _gpu_session(onnxruntime, engine, path, providers, options=None):
    """The image encoder through `engine`, or None when it can't load or gives the wrong vector for the test image."""
    import numpy

    try:
        session = onnxruntime.InferenceSession(str(path), sess_options=options, providers=providers)
        cosine = float(_unit(_run(session, parity_pixels()[None]))[0] @ numpy.load(PARITY_VECTOR))
        if cosine >= PARITY_COSINE:
            return session
        reason = f"its vector for the test image is off, at a cosine of {cosine:.4f}"
    except Exception as error:
        reason = str(error) or type(error).__name__
    logger.warning("%s could not run the search model, so the CPU runs it: %s", engine, reason)
    return None


def core_ml_available() -> bool:
    """Whether this is an Apple Silicon Mac whose ONNX Runtime can use Core ML."""
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return False
    try:
        import onnxruntime
    except ImportError:
        return False
    return "CoreMLExecutionProvider" in onnxruntime.get_available_providers()


def _run(session, pixels):
    """The image encoder's vectors for a stack of pixels. A model with a fixed batch, like the Core ML one, gets each
    chunk padded with blank images, whose vectors are dropped."""
    import numpy

    batch = session.get_inputs()[0].shape[0]
    if not isinstance(batch, int):
        return session.run(["pooler_output"], {"pixel_values": pixels})[0]
    vectors = []
    for start in range(0, len(pixels), batch):
        chunk = pixels[start:start + batch]
        padded = numpy.concatenate([chunk, numpy.zeros((batch - len(chunk), *chunk.shape[1:]), chunk.dtype)])
        vectors.append(session.run(["pooler_output"], {"pixel_values": padded})[0][:len(chunk)])
    return numpy.concatenate(vectors)


def _unit(features):
    import numpy

    return features / numpy.maximum(numpy.linalg.norm(features, axis=-1, keepdims=True), 1e-12)


def _missing(error: ImportError) -> str:
    """What to install when ONNX Runtime or the tokenizer can't be imported. On Windows, ONNX Runtime also needs
    Microsoft's C++ runtime, which Python doesn't include."""
    if sys.platform == "win32" and "DLL load failed" in str(error):
        machine = "arm64" if platform.machine().lower() == "arm64" else "x64"
        return ("Visual search needs the Microsoft Visual C++ Redistributable. Install it with: "
                f"winget install Microsoft.VCRedist.2015+.{machine}, then restart Orchard.")
    return DEPENDENCIES_MISSING


def _pixels(image):
    """One RGB image as SigLIP 2's input: squashed to a square, scaled to [-1, 1], channels first."""
    import numpy
    from PIL import Image

    image = image.resize((IMAGE_SIZE, IMAGE_SIZE), Image.Resampling.BILINEAR)
    pixels = numpy.asarray(image, dtype=numpy.float32) / 255
    return ((pixels - IMAGE_MEAN) / IMAGE_STD).transpose(2, 0, 1)


def parity_pixels():
    """The test image a GPU must get right, drawn without a decoder so it is the same everywhere."""
    import numpy

    y, x = numpy.mgrid[0:IMAGE_SIZE, 0:IMAGE_SIZE].astype(numpy.float32) / IMAGE_SIZE
    return numpy.stack([2 * x - 1, numpy.sin(6 * numpy.pi * x * y), numpy.cos(4 * numpy.pi * (x - y))]).astype(numpy.float32)


class SemanticIndex:
    """The embeddings of one folder's images, stored next to its library."""

    def __init__(self, directory: Path, encoder: Encoder):
        self.directory = Path(directory)
        self.encoder = encoder
        self._index_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._state = "idle"
        self._error = None
        # Images the last run couldn't read, which don't keep the folder from being ready.
        self._unreadable = frozenset()
        self._matrix = None
        with connect(self.directory) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS semantic_embeddings (
                    image_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    PRIMARY KEY (image_id, model)
                )
            """)

    def _set_state(self, state, error=None):
        with self._state_lock:
            self._state, self._error = state, error

    def status(self) -> dict:
        with connect(self.directory) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='images'"
            ).fetchone()
            total = connection.execute("SELECT COUNT(*) FROM images").fetchone()[0] if exists else 0
            indexed = connection.execute("""
                SELECT COUNT(*) FROM semantic_embeddings e
                JOIN images i ON i.id = e.image_id WHERE e.model = ?
            """, (MODEL,)).fetchone()[0] if exists else 0
            # Derived, not stored, since a scan can add images after a run: every image has a vector or can't be read.
            ready = total > 0 and (indexed == total or self._only_unreadable_pending(connection, total - indexed))
        with self._state_lock:
            state, error = self._state, self._error
        if state == "idle" and ready:
            state = "ready"
        # Between runs, the shared encoder says whether the model is downloading, loading, or failed to.
        if state == "idle" and self.encoder.activity:
            state = self.encoder.activity
        elif state == "idle" and self.encoder.failure:
            state, error = "error", self.encoder.failure
        result = {"state": state, "indexed": indexed, "total": total, "downloaded": self.encoder.downloaded()}
        if state == "downloading":
            result["received"], result["size"] = self.encoder.received(), self.encoder.size
        if error:
            result["error"] = error
        return result

    def _only_unreadable_pending(self, connection, pending) -> bool:
        unreadable = self._unreadable
        if not 0 < pending <= len(unreadable):
            return False
        return unreadable.issuperset(self._pending(connection))

    @staticmethod
    def _pending(connection) -> list[str]:
        """The images without a vector, newest first by the date the grid shows, so recent images are searchable soonest."""
        return [row[0] for row in connection.execute("""
            SELECT i.id FROM images i
            LEFT JOIN files f ON f.image_id = i.id
            LEFT JOIN semantic_embeddings e ON i.id = e.image_id AND e.model = ?
            WHERE e.image_id IS NULL
            GROUP BY i.id
            ORDER BY max(coalesce(i.taken, f.modified)) DESC
        """, (MODEL,))]

    def has_other_models(self) -> bool:
        """Whether vectors from another model are stored. They can't be compared with MODEL's."""
        with connect(self.directory) as connection:
            return connection.execute("SELECT 1 FROM semantic_embeddings WHERE model != ? LIMIT 1", (MODEL,)).fetchone() is not None

    def discard_other_models(self):
        with connect(self.directory) as connection:
            connection.execute("DELETE FROM semantic_embeddings WHERE model != ?", (MODEL,))

    def _open_image(self, image_id):
        from PIL import Image

        with Image.open(thumbnail_path(self.directory, image_id)) as image:
            return image.convert("RGB")

    def index(self, cancelled=lambda: False):
        """Embed new images until none are left, including any a scan adds meanwhile."""
        if not self._index_lock.acquire(blocking=False):
            return
        try:
            self._set_state("idle")
            unreadable = set()
            while True:
                with connect(self.directory) as connection:
                    connection.execute("""
                        DELETE FROM semantic_embeddings WHERE image_id NOT IN (SELECT id FROM images)
                    """)
                    pending = [image_id for image_id in self._pending(connection) if image_id not in unreadable]
                if not pending:
                    break
                self.encoder.load()
                self._set_state("indexing")
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
                            unreadable.add(image_id)
                            logger.warning("Could not read image %s for visual search", image_id)
                    if not images:
                        continue
                    try:
                        vectors = self.encoder.features(images=images)
                        with connect(self.directory) as connection:
                            connection.executemany(
                                "INSERT OR REPLACE INTO semantic_embeddings VALUES (?, ?, ?)",
                                [(image_id, MODEL, vector.astype("<f4").tobytes()) for image_id, vector in zip(ids, vectors)],
                            )
                    finally:
                        for image in images:
                            image.close()
            self._unreadable = frozenset(unreadable)
            failed = len(unreadable)
            self._set_state("idle", f"{failed} {'image' if failed == 1 else 'images'} could not be read for visual search." if failed else None)
        except Exception as error:
            logger.exception("Visual search indexing failed")
            self._set_state("error", str(error))
        finally:
            self._index_lock.release()

    def embeddings(self):
        """Return (ids, matrix) for indexed images, reloading only when the embeddings table changed."""
        import numpy

        with connect(self.directory) as connection:
            # Any write changes (count, max rowid), as INSERT OR REPLACE assigns a new rowid. Images can be removed
            # without touching embeddings, so both tables count.
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
        from PIL import Image, ImageOps
        from server.scanner import refuse_oversized

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
                with Image.open(BytesIO(image_bytes)) as source:
                    refuse_oversized(source)
                    image = ImageOps.exif_transpose(source).convert("RGB")
                try:
                    query = self.encoder.features(images=[image])[0]
                finally:
                    image.close()
            else:
                query = self.encoder.features(text=[text.strip()])[0]
        except (ValueError, OSError, Image.DecompressionBombError):
            raise ValueError("The reference image could not be read or is not indexed yet.")
        except Exception as error:
            self._set_state("error", str(error))
            raise
        scores = matrix @ query
        order = numpy.argsort(-scores, kind="stable")
        return [(ids[index], float(scores[index])) for index in order]
