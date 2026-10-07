"""Near-duplicate groups: images that look almost the same share one tile, fronted by the best of them.

Bursts, edits and resized copies differ byte for byte, so the scanner keeps them apart, but their embeddings barely
differ. Crops differ more, so copies a website or export tool cut from one picture are recognised by their file names
too. Each group gathers around one centre and every member must match it, so a slow series, like a crystal
photographed every day, cannot chain into one long group.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import re
import sqlite3
import threading

import numpy
from PIL import Image

from server.scanner import WORKERS, thumbnail_path

# Cosine similarity between image embeddings. Bursts and resized copies score above it; different shots of the
# same subject, like two photos of one plant or one speaker, score between 0.85 and 0.93.
THRESHOLD = 0.95
# Files in one folder whose names differ only by a size or copy suffix, like photo-800x400.jpg and photo (1).jpg,
# need only look related: crops of one picture score from 0.7 up, unrelated pictures that share a name far lower.
RELATED_THRESHOLD = 0.7
EXTENSION = re.compile(r'\.(jpe?g|jpe|png|gif|webp|bmp|tiff?|hei[cf]|avif)$', re.I)
SUFFIX = re.compile(r'(-\d+x\d+|@\d+x|-scaled|\.bk| \(\d+\)| copy( \d+)?|-e\d{10,})$', re.I)
CHUNK = 2048
# Sharpness is measured at one size, so a small copy does not look crisper just for having fewer pixels.
SHARPNESS_EDGE = 512


def stem(path: str) -> str:
    """A file's folder and name without its extensions and size or copy suffixes."""
    name, previous = path.lower(), None
    while name != previous:
        previous, name = name, SUFFIX.sub('', EXTENSION.sub('', name))
    return name


def gather(matrix, related=()) -> numpy.ndarray:
    """For each row of unit vectors, the row of its group's centre. `related` lists sets of rows whose file names
    mark them as versions of one picture.

    The images with the most near-duplicates claim their unclaimed neighbours first, so centres sit in the middle
    of a burst rather than at its edge.
    """
    rows, columns = [], []
    for start in range(0, len(matrix), CHUNK):
        row, column = numpy.nonzero(matrix[start:start + CHUNK] @ matrix.T >= THRESHOLD)
        rows.append(row + start)
        columns.append(column)
    for members in related:
        members = numpy.asarray(members)
        row, column = numpy.nonzero(matrix[members] @ matrix[members].T >= RELATED_THRESHOLD)
        rows.append(members[row])
        columns.append(members[column])
    rows, columns = numpy.concatenate(rows), numpy.concatenate(columns)
    # Group each image's neighbours into one contiguous run; a pair found by both rules is harmless.
    order = numpy.argsort(rows, kind='stable')
    rows, columns = rows[order], columns[order]
    counts = numpy.bincount(rows, minlength=len(matrix))
    ends = numpy.cumsum(counts)
    centres = numpy.full(len(matrix), -1)
    for index in numpy.argsort(-counts, kind='stable'):
        if centres[index] >= 0:
            continue
        centres[index] = index
        neighbours = columns[ends[index] - counts[index]:ends[index]]
        centres[neighbours[centres[neighbours] < 0]] = index
    return centres


def sharpness(path: Path) -> float:
    """Variance of the Laplacian: high for crisp edges, low for blur and camera shake."""
    with Image.open(path) as image:
        grey = image.convert('L')
    scale = SHARPNESS_EDGE / max(grey.size)
    grey = grey.resize((max(3, round(grey.width * scale)), max(3, round(grey.height * scale))), Image.Resampling.BILINEAR)
    pixels = numpy.asarray(grey, dtype=numpy.float32)
    laplacian = pixels[1:-1, :-2] + pixels[1:-1, 2:] + pixels[:-2, 1:-1] + pixels[2:, 1:-1] - 4 * pixels[1:-1, 1:-1]
    return float(laplacian.var())


class Groups:
    """Which images of one folder are near-duplicates, and how well each would front its group."""

    def __init__(self, directory: Path, semantic):
        self.directory = Path(directory)
        self.database = self.directory / 'library.sqlite'
        self.semantic = semantic
        self._lock = threading.Lock()
        self._grouped = None
        with self._connect() as connection:
            # Only images with near-duplicates have a row; every other image is a group of one.
            connection.execute('''
                CREATE TABLE IF NOT EXISTS image_groups (
                    image_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, score REAL NOT NULL
                )
            ''')

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.database, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _score(self, image_id: str, pixels: int) -> float:
        """How good a cover the image makes. Sharpness picks the best frame of a burst; between copies of one
        picture, which are about equally sharp at a fixed size, the larger one wins."""
        try:
            crisp = sharpness(thumbnail_path(self.directory, image_id))
        except (OSError, ValueError):
            crisp = 0.0
        return crisp * pixels ** 0.25

    def update(self) -> bool:
        """Regroup if the embeddings changed since the last grouping. Returns whether any group changed."""
        with self._lock:
            ids, matrix = self.semantic.embeddings()
            # The index hands back the same matrix until an embedding is added or an image removed.
            if matrix is self._grouped:
                return False
            with self._connect() as connection:
                files = connection.execute('SELECT path, image_id FROM files WHERE image_id IS NOT NULL').fetchall()
            position = {image_id: index for index, image_id in enumerate(ids)}
            families = {}
            for path, image_id in files:
                if image_id in position:
                    families.setdefault(stem(path), set()).add(position[image_id])
            related = [sorted(family) for family in families.values() if len(family) > 1]
            centres = gather(matrix, related) if matrix is not None else []
            sizes = numpy.bincount(centres, minlength=len(ids)) if len(ids) else []
            grouped = [index for index, centre in enumerate(centres) if sizes[centre] > 1]
            with self._connect() as connection:
                before = {row[0]: row[1:] for row in connection.execute('SELECT image_id, group_id, score FROM image_groups')}
                pixels = dict(connection.execute('SELECT id, width * height FROM images'))
            # An image's content never changes under its id, so neither does its score.
            scores = {ids[index]: before[ids[index]][1] for index in grouped if ids[index] in before}
            missing = [ids[index] for index in grouped if ids[index] not in scores]
            with ThreadPoolExecutor(WORKERS) as pool:
                scores.update(zip(missing, pool.map(lambda image_id: self._score(image_id, pixels.get(image_id, 0)), missing)))
            after = {ids[index]: (ids[centres[index]], scores[ids[index]]) for index in grouped}
            with self._connect() as connection:
                connection.execute('DELETE FROM image_groups')
                connection.executemany('INSERT INTO image_groups VALUES (?,?,?)',
                                       [(image_id, group, score) for image_id, (group, score) in after.items()])
            self._grouped = matrix
            return after != before
