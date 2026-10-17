"""Near-duplicate groups: images that look almost the same share one tile, fronted by the best of them.

Bursts, edits and resized copies are different files, but their vectors barely differ. Crops differ more, so copies
cut from one picture are also recognised by their file names. Every member of a group must match its centre, so a
slow series, like a plant photographed every day, can't chain into one long group.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import threading

import numpy
from PIL import Image

from server.cache import connect, thumbnail_path
from server.scanner import WORKERS

# The cosine similarity two images need to group. Copies and the closest frames of a burst score above it, but
# versions of one design, like an illustration in another colour, score nearly as high, so it sits close to 1.
THRESHOLD = 0.9775
# What files in one folder whose names differ only by a size or copy suffix, like photo-800x400.jpg and
# photo (1).jpg, need instead. Crops of one picture score above it, and numbered files of different pictures below.
RELATED_THRESHOLD = 0.72
EXTENSION = re.compile(r'\.(jpe?g|jpe|png|gif|webp|bmp|tiff?|hei[cf]|avif)$', re.I)
SUFFIX = re.compile(r'(-\d+x\d+|@\d+x|-scaled|\.bk| \(\d+\)| copy( \d+)?|-e\d{10,})$', re.I)
CHUNK = 2048
# Sharpness is measured at one size, so a small copy doesn't look crisper for having fewer pixels.
SHARPNESS_EDGE = 512


def stem(path: str) -> str:
    """A file's folder and name without its extensions and size or copy suffixes."""
    name, previous = path.lower(), None
    while name != previous:
        previous, name = name, SUFFIX.sub('', EXTENSION.sub('', name))
    return name


def gather(matrix, related=()) -> numpy.ndarray:
    """For each row of unit vectors, the row of its group's centre. `related` lists sets of rows whose file names
    mark them as versions of one picture. The images with the most near-duplicates claim their neighbours first, so
    centres sit in the middle of a burst rather than at its edge."""
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
    # Each image's neighbours in one contiguous run. A pair found by both rules is harmless.
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
        self.semantic = semantic
        self._lock = threading.Lock()
        self._grouped = None
        with connect(self.directory) as connection:
            # Only images with near-duplicates have a row. Every other image is a group of one.
            connection.execute('''
                CREATE TABLE IF NOT EXISTS image_groups (
                    image_id TEXT PRIMARY KEY, group_id TEXT NOT NULL, score REAL NOT NULL
                )
            ''')

    def _score(self, image_id: str, pixels: int) -> float:
        """How good a cover the image makes. Sharpness picks the best frame of a burst, and between copies of one
        picture, which are about equally sharp, the larger one wins."""
        try:
            crisp = sharpness(thumbnail_path(self.directory, image_id))
        except (OSError, ValueError):
            crisp = 0.0
        return crisp * pixels ** 0.25

    def clear(self):
        """Forget every group, so each image stands alone until the next update."""
        with self._lock:
            with connect(self.directory) as connection:
                connection.execute('DELETE FROM image_groups')
            self._grouped = None

    def update(self) -> bool:
        """Regroup if the embeddings changed since the last grouping. Returns whether any group changed."""
        with self._lock:
            ids, matrix = self.semantic.embeddings()
            # The index returns the same matrix until a vector is added or an image removed.
            if matrix is self._grouped:
                return False
            with connect(self.directory) as connection:
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
            with connect(self.directory) as connection:
                before = {row[0]: row[1:] for row in connection.execute('SELECT image_id, group_id, score FROM image_groups')}
                pixels = dict(connection.execute('SELECT id, width * height FROM images'))
            # An image's content never changes under its id, so neither does its score.
            scores = {ids[index]: before[ids[index]][1] for index in grouped if ids[index] in before}
            missing = [ids[index] for index in grouped if ids[index] not in scores]
            with ThreadPoolExecutor(WORKERS) as pool:
                scores.update(zip(missing, pool.map(lambda image_id: self._score(image_id, pixels.get(image_id, 0)), missing)))
            after = {ids[index]: (ids[centres[index]], scores[ids[index]]) for index in grouped}
            with connect(self.directory) as connection:
                connection.execute('DELETE FROM image_groups')
                connection.executemany('INSERT INTO image_groups VALUES (?,?,?)',
                                       [(image_id, group, score) for image_id, (group, score) in after.items()])
            self._grouped = matrix
            return after != before
