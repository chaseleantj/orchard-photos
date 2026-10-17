"""The map's layout: a UMAP of the image embeddings, so look-alikes sit together.

UMAP (McInnes, Healy and Melville, 2018) links each image to its nearest neighbours, then arranges the images in two
dimensions so linked images pull together while random pairs push apart. It is written here in NumPy, which keeps
umap-learn and the compiler and science libraries it pulls in out of the install.

Positions persist. Images that arrive later are placed among their nearest fitted neighbours instead of refitting,
which keeps the map from rearranging each time a few photos are added.
"""

from concurrent.futures import ThreadPoolExecutor
import logging
import threading

import numpy

from server.cache import connect

NEIGHBOURS = 15
# UMAP's curve 1 / (1 + a d^2b) for how strongly two points attract at distance d, fitted for min_dist 0.25.
CURVE_A, CURVE_B = 1.1214, 1.0575
EPOCHS = 500
NEGATIVE_SAMPLES = 5
# An epoch's links are split among up to THREADS threads, at least SHARE links apiece, since smaller shares cost more
# to hand out than they save.
SHARE = 20_000
PLACE_NEIGHBOURS = 5
REFIT_SHARE = 0.2
# Similarities scored per block, about 50 MB with argpartition's indices, so the THREADS blocks in flight stay
# small however large the folder.
BLOCK = 1 << 22
THREADS = 4
# Above EXACT_LIMIT images, neighbours are searched among nearby clusters instead of the whole folder. Each image's
# cluster is compared with every cluster that its members have among their PROBES closest, which finds about
# 99.5% of the true neighbours on real libraries. The clusters are fitted to a sample of SAMPLE_PER_CLUSTER images each.
EXACT_LIMIT = 10_000
PROBES = 6
SAMPLE_PER_CLUSTER = 64
CLUSTER_ROUNDS = 8
logger = logging.getLogger(__name__)


def _top(queries, candidates, k, own=None):
    """The k candidates most similar to each query, as (indices, similarities), in no particular order.

    own holds each query's own row among the candidates, which is left out of its neighbours."""
    similarity = queries @ candidates.T
    if own is not None:
        similarity[numpy.arange(len(own)), own] = -numpy.inf
    # A copy, because a slice would keep the whole block's indices alive.
    nearest = numpy.argpartition(similarity, -k, axis=1)[:, -k:].copy()
    return nearest, numpy.take_along_axis(similarity, nearest, 1)


def _nearest(queries, candidates, k, skip_self=False):
    """The k candidates most similar to each query, as (indices, similarities), in no particular order.

    With skip_self, queries are the candidates themselves and each image is left out of its own neighbours."""
    rows = max(1, BLOCK // len(candidates))

    def block(start):
        own = numpy.arange(start, min(start + rows, len(queries))) if skip_self else None
        return _top(queries[start:start + rows], candidates, k, own)

    # NumPy releases the GIL while it partitions, which is most of the time on large folders.
    with ThreadPoolExecutor(THREADS) as pool:
        blocks = list(pool.map(block, range(0, len(queries), rows)))
    return numpy.concatenate([b[0] for b in blocks]), numpy.concatenate([b[1] for b in blocks])


def _centres(matrix, count):
    """Centres for count clusters of the unit vectors, by spherical k-means on a sample."""
    generator = numpy.random.default_rng(0)
    sample = matrix[generator.choice(len(matrix), min(len(matrix), SAMPLE_PER_CLUSTER * count), replace=False)]
    centres = sample[:count]
    for _ in range(CLUSTER_ROUNDS):
        closest = (sample @ centres.T).argmax(axis=1)
        sums = (closest == numpy.arange(count)[:, None]).astype(sample.dtype) @ sample
        length = numpy.linalg.norm(sums, axis=1, keepdims=True)
        # A centre that won no images stays where it was.
        centres = numpy.where(length > 0, sums / numpy.maximum(length, 1e-12), centres)
    return centres


def _neighbours(matrix, k):
    """Each image's k most similar other images, as (indices, similarities), in no particular order.

    Small folders are searched exactly. Large ones are split into about sqrt(n) clusters and each image is compared
    only with the clusters around its own, so the cost grows about as n^1.5 rather than n^2 when the clusters are
    even."""
    count = len(matrix)
    if count <= EXACT_LIMIT:
        return _nearest(matrix, matrix, k, skip_self=True)
    centres = _centres(matrix, round(count ** 0.5))
    probes, closeness = _nearest(matrix, centres, PROBES)
    home = probes[numpy.arange(count), closeness.argmax(axis=1)]
    order = numpy.argsort(home, kind="stable")
    members = numpy.split(order, numpy.cumsum(numpy.bincount(home, minlength=len(centres)))[:-1])
    nearest, similarity = numpy.empty((count, k), numpy.int64), numpy.empty((count, k), matrix.dtype)

    def search(cluster):
        queries = members[cluster]
        candidates = numpy.concatenate([queries] + [members[c] for c in numpy.unique(probes[queries]) if c != cluster])
        if len(candidates) <= k:
            # Too isolated to have k images around it, so search the whole folder.
            candidates = numpy.concatenate([queries, numpy.setdiff1d(numpy.arange(count), queries)])
        vectors = matrix[candidates]
        rows = max(1, BLOCK // len(candidates))
        for start in range(0, len(queries), rows):
            block = slice(start, min(start + rows, len(queries)))
            found, values = _top(vectors[block], vectors, k, numpy.arange(len(queries))[block])
            nearest[queries[block]], similarity[queries[block]] = candidates[found], values

    with ThreadPoolExecutor(THREADS) as pool:
        list(pool.map(search, [cluster for cluster, images in enumerate(members) if len(images)]))
    return nearest, similarity


def _graph(matrix, k):
    """UMAP's fuzzy neighbour graph, as (first, second, weight) arrays with one entry per linked pair."""
    count = len(matrix)
    nearest, similarity = _neighbours(matrix, k)
    distance = numpy.maximum(1 - similarity.astype(numpy.float64), 0)
    # Each image's weights fall off from its closest neighbour at a rate chosen so they sum to log2(k), found by
    # bisection and never steeper than a thousandth of the typical distance.
    gaps = distance - distance.min(axis=1, keepdims=True)
    low, high = numpy.zeros((count, 1)), numpy.full((count, 1), numpy.inf)
    scale = numpy.ones((count, 1))
    for _ in range(64):
        heavy = numpy.exp(-gaps / scale).sum(axis=1, keepdims=True) > numpy.log2(k)
        high = numpy.where(heavy, scale, high)
        low = numpy.where(heavy, low, scale)
        scale = numpy.where(numpy.isinf(high), scale * 2, (low + high) / 2)
    weight = numpy.exp(-gaps / numpy.maximum(scale, 1e-3 * distance.mean()))
    # A link counts once whichever end found it: its weight is the chance that either direction holds.
    first, second = numpy.repeat(numpy.arange(count), k), nearest.ravel()
    pairs, pair = numpy.unique(numpy.minimum(first, second) * count + numpy.maximum(first, second), return_inverse=True)
    absent = numpy.ones(len(pairs))
    numpy.multiply.at(absent, pair, 1 - weight.ravel())
    return pairs // count, pairs % count, 1 - absent


def _forces(x, y, a, b, generator):
    """How far each image moves for the links between a and b, before the step size, as (x, y) per image."""
    # UMAP samples each link from both ends, and each sample pulls both ends together, so a due link pulls twice.
    dx, dy = x[a] - x[b], y[a] - y[b]
    squared = numpy.maximum(dx * dx + dy * dy, 1e-12)
    power = squared ** CURVE_B
    pull = -4 * CURVE_A * CURVE_B * power / (squared * (CURVE_A * power + 1))
    # Each end of a link is also pushed away from a few random images.
    heads = numpy.concatenate([a, b])
    other = generator.integers(0, len(x), (NEGATIVE_SAMPLES, len(heads)))
    ndx, ndy = x[heads] - x[other], y[heads] - y[other]
    squared = ndx * ndx + ndy * ndy
    push = 2 * CURVE_B / ((0.001 + squared) * (CURVE_A * squared ** CURVE_B + 1))
    # Each sample's move is clipped to 4 so near-coincident points can't fling each other away, and a pull is two
    # samples. The 0.001 keeps a push finite.
    moves = []
    for d, nd in ((dx, ndx), (dy, ndy)):
        pulled = numpy.clip(pull * d, -8, 8)
        pushed = numpy.clip(push * nd, -4, 4).sum(axis=0)
        moves.append(numpy.bincount(heads, numpy.concatenate([pulled, -pulled]) + pushed, len(x)))
    return moves


def embed(matrix):
    """Lay unit vectors out in two dimensions, so that nearest neighbours stay near."""
    count = len(matrix)
    if count < 3:
        return numpy.array([[index, 0.0] for index in range(count)])
    first, second, weight = _graph(matrix, min(NEIGHBOURS, count - 1))
    # Each link is sampled in proportion to its weight, so links too weak to come up once in the run are dropped.
    kept = weight >= weight.max() / EPOCHS
    first, second, frequency = first[kept], second[kept], weight[kept] / weight.max()
    # Start from the two main directions of variation, which spreads the folder's broad themes apart, at UMAP's
    # starting size of 10 either way, plus a whisker of noise so identical vectors can separate.
    centred = matrix - matrix.mean(axis=0)
    start = centred @ numpy.linalg.eigh(centred.T @ centred)[1][:, -2:]
    start = 10 * start / (numpy.abs(start).max() or 1.0)
    generator = numpy.random.default_rng(0)
    start += generator.normal(scale=1e-4, size=start.shape)
    x, y = (numpy.ascontiguousarray(axis, dtype=numpy.float32) for axis in start.T)
    # Each thread works through its share of the due links with its own random stream, so the result doesn't depend
    # on which thread finishes first.
    generators = generator.spawn(THREADS)
    with ThreadPoolExecutor(THREADS) as pool:
        for epoch in range(EPOCHS):
            due = numpy.flatnonzero(numpy.floor((epoch + 1) * frequency) > numpy.floor(epoch * frequency))
            shares = numpy.array_split(due, max(1, min(THREADS, len(due) // SHARE)))
            moves = list(pool.map(lambda share, generator: _forces(x, y, first[share], second[share], generator),
                                  shares, generators))
            # Steps shrink as the run settles.
            step = 1 - epoch / EPOCHS
            x += (step * sum(move[0] for move in moves)).astype(numpy.float32)
            y += (step * sum(move[1] for move in moves)).astype(numpy.float32)
    return numpy.column_stack([x, y])


class Layout:
    def __init__(self, semantic):
        self.semantic = semantic
        self.directory = semantic.directory
        self._lock = threading.Lock()
        self._state = {"state": "idle"}
        self._cache = None
        with connect(self.directory) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS umap_positions (
                    image_id TEXT PRIMARY KEY, x REAL NOT NULL, y REAL NOT NULL, fitted INTEGER NOT NULL
                )
            """)

    def status(self) -> dict:
        return dict(self._state)

    def clear(self):
        """Forget every position, so the next map is fitted afresh."""
        with connect(self.directory) as connection:
            connection.execute("DELETE FROM umap_positions")
        self._cache = None

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
            points = self._normalise(embed(matrix))
            with connect(self.directory) as connection:
                connection.execute("DELETE FROM umap_positions")
                connection.executemany("INSERT INTO umap_positions VALUES (?, ?, ?, 1)",
                                       [(i, float(x), float(y)) for i, (x, y) in zip(ids, points)])
            self._cache = None
            self._set("idle")
        except Exception:
            logger.exception("UMAP layout failed")
            self._set("error", error="The layout could not be computed. Retry.")
        finally:
            self._lock.release()

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
        with connect(self.directory) as connection:
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
        coordinates = numpy.array([stored[ids[n]][:2] for n in rows])
        nearest, values = _nearest(matrix[missing], matrix[rows], min(PLACE_NEIGHBOURS, len(rows)))
        weights = numpy.exp((values - values.max(axis=1, keepdims=True)) / 0.05)
        weights /= weights.sum(axis=1, keepdims=True)
        centres = (weights[:, :, None] * coordinates[nearest]).sum(axis=1)
        placed = {}
        for n, centre in zip(missing, centres):
            # A little deterministic scatter keeps look-alikes from stacking on one spot.
            seed = int(ids[n][:8], 16)
            jitter = numpy.random.default_rng(seed).normal(scale=0.006, size=2)
            placed[ids[n]] = tuple(float(v) for v in centre + jitter)
        with connect(self.directory) as connection:
            connection.executemany("INSERT OR REPLACE INTO umap_positions VALUES (?, ?, ?, 0)",
                                   [(i, x, y) for i, (x, y) in placed.items()])
        return placed
