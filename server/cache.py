"""Where one folder's cache keeps its index, thumbnails and previews, and how its files are opened and replaced."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import sys
import time

DATABASE = 'library.sqlite'
# Windows refuses to replace or delete a file while another thread reads it, as the server does while sending it.
OPEN_FILE_TRIES = 20
OPEN_FILE_WAIT = 0.05


@contextmanager
def connect(directory: Path, rows=False):
    """A connection to the cache's database, in a transaction that commits on success. With `rows`, rows are
    sqlite3.Row."""
    connection = sqlite3.connect(Path(directory) / DATABASE, timeout=30)
    if rows:
        connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def thumbnail_path(directory: Path, image_id: str) -> Path:
    return Path(directory) / 'thumbnails' / f'{image_id}.webp'


def preview_path(directory: Path, image_id: str) -> Path:
    """A full-size JPEG for formats browsers cannot show, drawn when first viewed."""
    return Path(directory) / 'previews' / f'{image_id}.jpg'


def while_open(change, *args, **options):
    """Replace or delete a file, waiting briefly on Windows for any thread still reading it to finish."""
    for attempt in range(OPEN_FILE_TRIES):
        try:
            return change(*args, **options)
        except PermissionError:
            if sys.platform != 'win32' or attempt == OPEN_FILE_TRIES - 1:
                raise
            time.sleep(OPEN_FILE_WAIT)
