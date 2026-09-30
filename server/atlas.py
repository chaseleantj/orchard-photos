"""Rounded-square icon sheets, so the map can draw thousands of images from a handful of requests."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import logging
from pathlib import Path
import sqlite3
import threading

from server.scanner import thumbnail_path

CELL = 64
COLUMNS = 32
PER_SHEET = COLUMNS * COLUMNS
INSET = 2
RADIUS = 7
logger = logging.getLogger(__name__)


class Atlas:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.folder = self.directory / "atlas"
        self.database = self.directory / "library.sqlite"
        self._lock = threading.Lock()
        self.folder.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database, timeout=30)) as connection, connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS atlas_slots (
                    image_id TEXT PRIMARY KEY, slot INTEGER NOT NULL UNIQUE
                )
            """)

    def sheet_path(self, sheet: int) -> Path:
        return self.folder / f"sheet-{sheet}.webp"

    def versions(self) -> list[str]:
        """One cache-busting token per sheet on disk, in order."""
        result = []
        while (path := self.sheet_path(len(result))).is_file():
            stat = path.stat()
            result.append(f"{stat.st_mtime_ns:x}-{stat.st_size:x}")
        return result

    def ensure(self) -> dict[str, int]:
        """Give every image a slot, drawing icons for the new ones. Returns image id -> slot."""
        with self._lock, closing(sqlite3.connect(self.database, timeout=30)) as connection, connection:
            slots = dict(connection.execute("SELECT image_id, slot FROM atlas_slots"))
            missing = connection.execute("""
                SELECT id FROM images WHERE id NOT IN (SELECT image_id FROM atlas_slots) ORDER BY rowid
            """).fetchall()
            if not missing:
                return slots
            first = max(slots.values(), default=-1) + 1
            assigned = {image_id: first + offset for offset, (image_id,) in enumerate(missing)}
            with ThreadPoolExecutor(max_workers=4) as pool:
                icons = list(pool.map(lambda row: self._icon(thumbnail_path(self.directory, row[0])), missing))
            sheets: dict[int, list] = {}
            for (image_id,), icon in zip(missing, icons):
                sheets.setdefault(assigned[image_id] // PER_SHEET, []).append((assigned[image_id] % PER_SHEET, icon))
            for sheet, tiles in sheets.items():
                self._paste(sheet, tiles)
            connection.executemany("INSERT INTO atlas_slots VALUES (?, ?)", assigned.items())
            slots.update(assigned)
            return slots

    def _icon(self, path: Path):
        from PIL import Image, ImageDraw, ImageOps

        size = CELL - 2 * INSET
        try:
            with Image.open(path) as source:
                icon = ImageOps.fit(source.convert("RGB"), (size, size), Image.LANCZOS)
        except (OSError, ValueError):
            logger.warning("Could not draw a map icon for %s", path.name)
            icon = Image.new("RGB", (size, size), (200, 200, 195))
        mask = Image.new("L", (size * 4, size * 4), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), RADIUS * 4, fill=255)
        icon = icon.convert("RGBA")
        icon.putalpha(mask.resize((size, size), Image.LANCZOS))
        # A faint neutral hairline keeps white images visible on a light page and dark ones on a dark page.
        edge = Image.new("RGBA", (size * 4, size * 4), (0, 0, 0, 0))
        ImageDraw.Draw(edge).rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), RADIUS * 4, outline=(128, 128, 120, 70), width=4)
        return Image.alpha_composite(icon, edge.resize((size, size), Image.LANCZOS))

    def _paste(self, sheet: int, tiles):
        from PIL import Image

        path = self.sheet_path(sheet)
        if path.is_file():
            with Image.open(path) as existing:
                canvas = existing.convert("RGBA")
        else:
            canvas = Image.new("RGBA", (CELL * COLUMNS, CELL * COLUMNS), (0, 0, 0, 0))
        for slot, icon in tiles:
            canvas.paste(icon, ((slot % COLUMNS) * CELL + INSET, (slot // COLUMNS) * CELL + INSET))
        temporary = path.with_suffix(".tmp")
        canvas.save(temporary, "WEBP", quality=80, method=4)
        temporary.replace(path)
