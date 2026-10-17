"""The opt-in check for a newer release on GitHub. It is off until turned on in Info. Once on, GitHub is asked at most
once a day, and only when the page asks, and any failure stays silent until the next day's check."""
import json
import logging
from pathlib import Path
import re
import threading
import time
import urllib.request

REPOSITORY = 'chaseleantj/orchard-photos'
LATEST = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
RELEASES = f'https://github.com/{REPOSITORY}/releases/'
CHECK_EVERY = 24 * 60 * 60
TIMEOUT = 3
VERSION = re.compile(r'v?(\d+)\.(\d+)\.(\d+)')
logger = logging.getLogger(__name__)


def parse(version) -> tuple[int, ...] | None:
    match = VERSION.fullmatch(str(version).strip())
    return tuple(int(part) for part in match.groups()) if match else None


class Updates:
    """Keeps the setting and the last check's answer in `path`, so a restart doesn't ask GitHub again the same day."""

    def __init__(self, path: Path, version: str, agent: str):
        self.path = Path(path)
        self.version = version
        self.agent = agent
        self.lock = threading.Lock()

    def _saved(self) -> dict:
        try:
            saved = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
        return saved if isinstance(saved, dict) else {}

    def _save(self, saved: dict):
        self.path.write_text(json.dumps(saved), encoding='utf-8')

    def turn(self, enabled: bool):
        with self.lock:
            self._save({**self._saved(), 'enabled': enabled})

    def status(self) -> dict:
        """Whether the check is on, and the newer release as {'version', 'url'}, or None when there is none or GitHub
        couldn't say. GitHub is never asked while the check is off."""
        with self.lock:
            saved = self._saved()
            if saved.get('enabled') is not True:
                return {'enabled': False, 'update': None}
            checked = saved.get('checked')
            if not isinstance(checked, (int, float)) or not 0 <= time.time() - checked < CHECK_EVERY:
                saved = {'enabled': True, 'checked': time.time(), **self.fetch()}
                self._save(saved)
        newest, current = parse(saved.get('version')), parse(self.version)
        update = {'version': '.'.join(map(str, newest)), 'url': saved['url']} if newest and current and newest > current else None
        return {'enabled': True, 'update': update}

    def fetch(self) -> dict:
        """The latest release's version and page, or nothing when GitHub can't be reached or has no release."""
        request = urllib.request.Request(LATEST, headers={'Accept': 'application/vnd.github+json', 'User-Agent': self.agent})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                release = json.load(response)
            version, url = release['tag_name'], release['html_url']
        # Offline, slow, a 404 before the first release, or an unexpected reply.
        except (OSError, ValueError, KeyError, TypeError) as error:
            logger.info('No update check today: %s', error)
            return {}
        # The link is shown in the page, so only GitHub's own release pages are kept.
        return {'version': version, 'url': url} if isinstance(url, str) and url.startswith(RELEASES) else {}
