"""A short plain-text report to paste into a bug report. It names versions, the search engine, counts and states, and
never a file name or folder path."""
from datetime import UTC, datetime
from importlib import metadata
import logging
from pathlib import Path
import platform
import re
import sys

from server.semantic import core_ml_available, preferred_engine


def minute(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime('%Y-%m-%d %H:%M UTC')


class LastError(logging.Handler):
    """Remembers the last warning or error logged, in one line. Only the message's template and the exception's type
    are kept, since the values filled in can be file names or paths."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.message = None

    def emit(self, record):
        message = str(record.msg)
        if record.exc_info and record.exc_info[1]:
            message += f': {type(record.exc_info[1]).__name__}'
        self.message = f'{message.splitlines()[0]} ({minute(datetime.fromtimestamp(record.created, UTC))})'


LAST_ERROR = LastError()


def system() -> str:
    """The operating system and its version, as people name them."""
    if sys.platform == 'darwin':
        return f'macOS {platform.mac_ver()[0]}'
    if sys.platform == 'win32':
        return f'Windows {platform.release()} ({platform.version()})'
    try:
        name = platform.freedesktop_os_release()['PRETTY_NAME']
    except (OSError, KeyError):
        name = platform.system()
    return f'{name}, kernel {platform.release()}'


def runtime() -> str:
    """ONNX Runtime's version and providers."""
    try:
        import onnxruntime
    except ImportError:
        return 'not installed'
    return f'{onnxruntime.__version__} ({", ".join(onnxruntime.get_available_providers())})'


def encoder_line(encoder) -> str:
    """Which engine runs the image encoder, and whether it stands in for a faster one this computer has."""
    if encoder.engine is None:
        return f'not loaded yet, will try {preferred_engine(encoder.core_ml)}' if runtime() != 'not installed' else 'not loaded yet'
    best = preferred_engine(core_ml_available())
    return encoder.engine if encoder.engine == best else f'{encoder.engine}, in place of {best}'


def redact(text: str, folder: Path | None) -> str:
    """Leave the open folder and everything under it out of `text`, and shorten the home folder to ~."""
    if folder:
        text = re.sub(re.escape(str(folder)) + r'''(?:[/\\][^'"\n]*)?''', '<folder>', text)
    return text.replace(str(Path.home()), '~')


def report(app, title: str) -> str:
    """The report for `app`, headed by `title`, the app's name and version."""
    library = app.library
    shown = f'window (pywebview {metadata.version("pywebview")})' if app.window else 'browser'
    lines = [
        title,
        f'System: {system()}, {platform.machine()}',
        f'Python: {platform.python_version()}',
        f'ONNX Runtime: {runtime()}',
        f'Image encoder: {encoder_line(app.encoder)}',
        f'Search model: {"downloaded" if app.encoder.downloaded() else "not downloaded"}',
        f'Shown in: {shown}',
    ]
    if library:
        status = library.status()
        counts, skipped, scan, search = status['counts'], status['skipped'], status['scan'], status['search']
        finished = minute(datetime.fromisoformat(status['updated'])) if status['updated'] else 'never'
        lines += [
            f'Images: {counts["images"]:,}, unreadable {counts["unreadable"]:,}, unreached {status["unreached"]:,}, '
            f'RAW skipped {skipped.get("raw", 0):,}, videos skipped {skipped.get("video", 0):,}',
            f'Scan: {scan["state"]}' + (f', {scan["error"]}' if scan.get('error') else '') + f', last finished {finished}',
            f'Visual search: {search["state"]}, {search["indexed"]:,} of {search["total"]:,} prepared' + (f', {search["error"]}' if search.get('error') else ''),
        ]
    else:
        lines.append('Folder: none open')
    lines.append(f'Last error: {LAST_ERROR.message or "none"}')
    return redact('\n'.join(lines), library.folder if library else None)
