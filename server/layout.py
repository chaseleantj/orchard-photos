"""The map's layout: a UMAP of the CLIP embeddings, so look-alikes sit together.

Positions persist. Images that arrive later are placed among their nearest fitted neighbours instead of refitting,
which keeps the map from rearranging each time a few photos are added.
"""

from contextlib import closing
import logging
import sqlite3
import threading

import numpy

NEIGHBOURS = 15
MIN_DIST = 0.25
MIN_IMAGES = 16
PLACE_NEIGHBOURS = 5
REFIT_SHARE = 0.2
CHUNK = 1024
logger = logging.getLogger(__name__)
# Numba's default threading layer aborts the process if two threads run parallel kernels at once,
# so every folder's layout shares one lock.
_kernels = threading.Lock()


def warm():
    """Import UMAP and compile its kernels so the first real fit doesn't pay for it."""
    try:
        import umap
        generator = numpy.random.default_rng(0)
        # Above 4096 images UMAP switches to its scalable neighbour search, whose kernels are the slow ones to compile.
        with _kernels:
            umap.UMAP(n_neighbors=5, metric="cosine").fit(generator.normal(size=(4200, 8)).astype("float32"))
    except Exception:
        logger.exception("UMAP warm-up failed")


class Layout:
    def __init__(self, semantic):
        self.semantic = semantic
        self.database = semantic.database
        self._lock = threading.Lock()
        self._state = {"state": "idle"}
        self._cache = None
        with closing(sqlite3.connect(self.database, timeout=30)) as connection, connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS umap_positions (
                    image_id TEXT PRIMARY KEY, x REAL NOT NULL, y REAL NOT NULL, fitted INTEGER NOT NULL
                )
            """)

    def status(self) -> dict:
        return dict(self._state)

    def _set(self, state, stage="", error=None):
        self._state = {"state": state, "stage": stage, **({"error": error} if error else {})}

    def start(self):
        """Fit in the background. Returns False when a fit is already running."""
        if not self._lock.acquire(blocking=False):
            return False
        self._set("computing", "Laying out the map")
        threading.Thread(target=self._fit, daemon=True).start()
        return True

    def _fit(self):
        try:
            ids, matrix = self.semantic.embeddings()
            if not ids:
                self._set("idle")
                return
            points = self._normalise(self._embed(matrix))
            with closing(sqlite3.connect(self.database, timeout=30)) as connection, connection:
                connection.execute("DELETE FROM umap_positions")
                connection.executemany("INSERT INTO umap_positions VALUES (?, ?, ?, 1)",
                                       [(i, float(x), float(y)) for i, (x, y) in zip(ids, points)])
            self._cache = None
            self._set("idle")
        except Exception as error:
            logger.exception("UMAP layout failed")
            self._set("error", error=str(error) if isinstance(error, RuntimeError) else "The layout could not be computed. Retry.")
        finally:
            self._lock.release()

    def _embed(self, matrix):
        try:
            import umap
        except ImportError as error:
            raise RuntimeError("The layout needs its Python dependencies. Run the setup command and retry.") from error
        count = len(matrix)
        if count < 3:
            return numpy.array([[index, 0.0] for index in range(count)])
        # Tiny folders have no neighbourhoods to speak of, and spectral start-up needs more images than neighbours.
        small = count < MIN_IMAGES
        with _kernels:
            return umap.UMAP(n_neighbors=min(NEIGHBOURS, count - 1), min_dist=MIN_DIST, metric="cosine",
                             init="random" if small else "spectral").fit_transform(matrix)

    @staticmethod
    def _normalise(points):
        """Centre, and scale so most images fall within [-1, 1], with one scale for both axes so distances stay honest."""
        points = points - numpy.median(points, axis=0)
        extent = float(numpy.percentile(numpy.abs(points).max(axis=1), 99)) or 1.0
        return points / extent

    def positions(self):
        """Fitted positions for every indexed image, or None before the first fit. Newer images are placed, not fitted."""
        ids, matrix = self.semantic.embeddings()
        if not ids:
            return {}
        if self._cache and self._cache[0] is matrix:
            return self._cache[1]
        with closing(sqlite3.connect(self.database, timeout=30)) as connection, connection:
            stored = {i: (x, y, fitted) for i, x, y, fitted in connection.execute("SELECT * FROM umap_positions")}
        rows = [n for n, i in enumerate(ids) if i in stored]
        if not rows:
            return None
        result = {ids[n]: stored[ids[n]][:2] for n in rows}
        missing = [n for n, i in enumerate(ids) if i not in stored]
        if missing:
            result.update(self._place(ids, matrix, rows, missing, stored))
            fitted = sum(1 for n in rows if stored[ids[n]][2])
            if len(missing) > REFIT_SHARE * max(1, fitted):
                self.start()
        self._cache = (matrix, result)
        return result

    def _place(self, ids, matrix, rows, missing, stored):
        """Put each new image at the similarity-weighted centre of its nearest fitted neighbours."""
        anchors = matrix[rows]
        coordinates = numpy.array([stored[ids[n]][:2] for n in rows])
        k = min(PLACE_NEIGHBOURS, len(rows))
        placed = {}
        for start in range(0, len(missing), CHUNK):
            chunk = missing[start:start + CHUNK]
            similarity = matrix[chunk] @ anchors.T
            nearest = numpy.argpartition(-similarity, k - 1, axis=1)[:, :k]
            values = numpy.take_along_axis(similarity, nearest, 1)
            weights = numpy.exp((values - values.max(axis=1, keepdims=True)) / 0.05)
            weights /= weights.sum(axis=1, keepdims=True)
            centres = (weights[:, :, None] * coordinates[nearest]).sum(axis=1)
            for n, centre in zip(chunk, centres):
                # A little deterministic scatter keeps look-alikes from stacking on one spot.
                seed = int(ids[n][:8], 16)
                jitter = numpy.random.default_rng(seed).normal(scale=0.006, size=2)
                placed[ids[n]] = tuple(float(v) for v in centre + jitter)
        with closing(sqlite3.connect(self.database, timeout=30)) as connection, connection:
            connection.executemany("INSERT OR REPLACE INTO umap_positions VALUES (?, ?, ?, 0)",
                                   [(i, x, y) for i, (x, y) in placed.items()])
        return placed
