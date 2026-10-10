"""Loopback-only HTTP API and production web server. Serves one folder at a time; the folder can be changed live."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from urllib.parse import parse_qs, quote, urlparse
import urllib.error
import urllib.request
import webbrowser

from server import layout
from server.library import IMAGE_ID, Library
from server.semantic import Encoder

ROOT = Path(__file__).resolve().parent.parent
APP = json.loads((ROOT / 'app.json').read_text())
RECENT_LIMIT = 10
WATCH_SECONDS = 60
UPLOAD_LIMIT = 20 * 1024 * 1024
FORM_LIMIT = 64 * 1024
IMMUTABLE = 'private, max-age=31536000, immutable'


def default_data_dir() -> Path:
    """Where the cache and model live: the platform's per-user application data folder."""
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / APP['slug']
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / APP['slug']


def tilde(path: Path) -> str:
    """A path as people write it: the home folder shortened to ~."""
    try:
        return '~/' + str(path.relative_to(Path.home())) if path != Path.home() else '~'
    except ValueError:
        return str(path)


class App:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.encoder = Encoder(self.data_dir / 'models')
        self.recent_path = self.data_dir / 'recent.json'
        self.library: Library | None = None
        self._lock = threading.Lock()

    def resolve(self, value) -> Path:
        text = str(value or '').strip()
        if not text:
            raise ValueError('Enter the path of a folder.')
        path = Path(text).expanduser()
        if not path.is_absolute():
            raise ValueError('Enter a full path, starting with / or ~.')
        try:
            path = path.resolve(strict=True)
        except (OSError, RuntimeError):
            raise ValueError(f'{text} does not exist.')
        if not path.is_dir():
            raise ValueError(f'{text} is a file. Choose the folder that contains it.')
        if not os.access(path, os.R_OK | os.X_OK):
            raise ValueError(f'{text} cannot be read. Check its permissions.')
        if path == self.data_dir or self.data_dir in path.parents:
            raise ValueError(f'{text} is where {APP["name"]} keeps its cache. Choose a folder of images.')
        return path

    def open(self, value) -> Library:
        """Show another folder. Its cache is kept separately, so returning to a folder is instant."""
        folder = self.resolve(value)
        with self._lock:
            if self.library and self.library.folder == folder:
                return self.library
            if self.library:
                self.library.close()
            key = hashlib.sha256(str(folder).encode()).hexdigest()[:16]
            library = self.library = Library(folder, self.data_dir / 'libraries' / key, self.encoder)
            self.remember(folder)
        threading.Thread(target=library.scan, daemon=True).start()
        return library

    def prepare(self):
        """Set up visual search in the background: download the model if needed, then prepare the open folder."""
        def run():
            try:
                self.encoder.load()
            except RuntimeError:
                return  # The status reports the failure, and setting up again retries.
            # The first description searched would otherwise wait while the text half of the model warms up.
            self.encoder.warm()
            if self.library:
                self.library.index()
        if not self.encoder.loaded:
            # Reported at once, so the page never shows the setup button again while the thread starts.
            self.encoder.activity = self.encoder.activity or ('loading' if self.encoder.downloaded() else 'downloading')
        threading.Thread(target=run, daemon=True).start()

    def current(self) -> Library:
        library = self.library
        if library is None:
            raise ValueError('Choose a folder of images first.')
        return library

    def recent(self) -> list[str]:
        try:
            saved = json.loads(self.recent_path.read_text())
        except (OSError, ValueError):
            return []
        return [path for path in saved if isinstance(path, str)] if isinstance(saved, list) else []

    def remember(self, folder: Path):
        paths = [str(folder)] + [path for path in self.recent() if path != str(folder)]
        self.recent_path.write_text(json.dumps(paths[:RECENT_LIMIT]))

    def forget(self, value):
        self.recent_path.write_text(json.dumps([path for path in self.recent() if path != str(value)]))

    def status(self):
        library = self.library
        recent = [{'path': path, 'label': tilde(Path(path)), 'available': Path(path).is_dir()}
                  for path in self.recent() if not library or path != str(library.folder)]
        result = {'app': APP['name'], 'platform': sys.platform, 'recent': recent, 'folder': None, 'library': None,
                  'model': self.encoder.downloaded() or self.encoder.activity is not None}
        if library:
            result['folder'] = {'path': str(library.folder), 'label': tilde(library.folder),
                                'name': library.folder.name or str(library.folder), 'id': library.directory.name}
            result['library'] = library.status()
        return result


def choose_folder(start: Path | None):
    """Ask with the system folder dialog. Returns None when cancelled. macOS only."""
    script = ['-e', 'on run argv', '-e', 'set prompt to item 1 of argv']
    if start:
        script += ['-e', 'POSIX path of (choose folder with prompt prompt default location (POSIX file (item 2 of argv)))']
    else:
        script += ['-e', 'POSIX path of (choose folder with prompt prompt)']
    script += ['-e', 'end run', 'Choose a folder of images']
    result = subprocess.run(['osascript', *script, *([str(start)] if start else [])], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def reveal(path: Path):
    if sys.platform == 'darwin':
        subprocess.Popen(['open', '-R', str(path)])
    elif sys.platform == 'win32':
        subprocess.Popen(['explorer', '/select,', str(path)])
    else:
        subprocess.Popen(['xdg-open', str(path.parent)])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    @property
    def app(self) -> App:
        return self.server.app

    def allowed(self):
        host = self.headers.get('Host', '').split(':')[0]
        if host not in ('127.0.0.1', 'localhost') or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return False
        origin = self.headers.get('Origin')
        if origin:
            try:
                parsed = urlparse(origin)
                port = parsed.port
            except ValueError:
                return False
            if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or port not in (self.server.server_port, APP['devPort']):
                return False
        return True

    def json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def body(self, limit):
        try:
            size = int(self.headers.get('Content-Length', 0))
        except ValueError:
            size = -1
        if size <= 0 or size > limit:
            raise ValueError('Choose an image smaller than 20 MB.' if limit == UPLOAD_LIMIT else 'The request was empty or too large.')
        return self.rfile.read(size)

    def form(self):
        try:
            data = json.loads(self.body(FORM_LIMIT))
        except ValueError:
            raise ValueError('The request could not be read.')
        if not isinstance(data, dict):
            raise ValueError('The request could not be read.')
        return data

    def do_GET(self):
        self.dispatch(False)

    def do_POST(self):
        self.dispatch(True)

    def dispatch(self, post):
        if not self.allowed():
            self.json({'error': 'This app is available only on this computer.'}, 403)
            return
        url = urlparse(self.path)
        params = {key: values[0] for key, values in parse_qs(url.query).items()}
        route = (url.path, post)
        try:
            if route == ('/api/status', False):
                self.json(self.app.status())
            elif route == ('/api/folder', True):
                self.app.open(self.form().get('path'))
                self.json(self.app.status())
            elif route == ('/api/folder/choose', True):
                if sys.platform != 'darwin':
                    raise ValueError('Type the folder path instead.')
                chosen = choose_folder(self.app.library.folder if self.app.library else None)
                if chosen:
                    self.app.open(chosen)
                self.json({**self.app.status(), 'cancelled': not chosen})
            elif route == ('/api/folder/forget', True):
                self.app.forget(self.form().get('path'))
                self.json(self.app.status())
            elif route == ('/api/scan', True):
                threading.Thread(target=self.app.current().scan, daemon=True).start()
                self.json({'started': True}, 202)
            elif route == ('/api/search/index', True):
                self.app.prepare()
                self.json({'started': True}, 202)
            elif route == ('/api/images', False):
                self.json(self.app.current().pictures(params))
            elif route == ('/api/search/image', True):
                library = self.app.current()
                self.json(library.pictures(params, self.body(UPLOAD_LIMIT)))
            elif route == ('/api/timeline', False):
                self.json(self.app.current().timeline(params))
            elif route == ('/api/facets', False):
                self.json(self.app.current().facets())
            elif route == ('/api/layout', False):
                self.json(self.app.current().layout.status())
            elif route == ('/api/layout', True):
                self.json({'started': self.app.current().layout.start()}, 202)
            elif route == ('/api/map', False):
                self.json(self.app.current().map(params))
            elif re.fullmatch(r'/api/atlas/\d+', url.path) and not post:
                self.file(self.app.current().atlas.sheet_path(int(url.path.rsplit('/', 1)[1])))
            elif url.path.startswith('/api/images/'):
                self.image(url.path.strip('/').split('/')[2:], params, post)
            elif url.path.startswith('/api/') or post:
                self.json({'error': 'Not found.'}, 404)
            else:
                path = (ROOT / 'dist' / url.path.lstrip('/')).resolve()
                if not path.is_relative_to(ROOT / 'dist'):
                    self.json({'error': 'Not found.'}, 404)
                elif path.is_file():
                    self.file(path, cache='no-cache')
                else:
                    self.file(ROOT / 'dist/index.html', cache='no-cache')
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, RuntimeError) as error:
            self.json({'error': str(error)}, 400)
        except Exception:
            logging.exception('Request failed: %s', url.path)
            self.json({'error': 'The request could not be completed. Retry, or rescan the folder.'}, 500)

    def image(self, parts, params, post):
        if not parts or not IMAGE_ID.fullmatch(parts[0]):
            self.json({'error': 'Image not found.'}, 404)
            return
        library, image_id = self.app.current(), parts[0]
        action = parts[1] if len(parts) == 2 else None
        if action == 'thumbnail' and not post:
            self.file(library.thumbnail(image_id), mime='image/webp')
            return
        details = library.details(image_id)
        if not details:
            self.json({'error': 'This image is no longer in the folder. Rescan to refresh.'}, 404)
            return
        if len(parts) == 1 and not post:
            self.json(details)
        elif action == 'reveal' and post:
            path = library.original(image_id, self.form().get('path'))
            if not path or not path.exists():
                raise ValueError('This file is no longer there. Rescan to refresh.')
            reveal(path)
            self.json({'revealed': True})
        elif action == 'display' and not post:
            path = library.display(image_id)
            self.file(path, mime=details['mime'] if not details['preview'] else 'image/jpeg')
        elif action == 'original' and not post:
            path = library.original(image_id, params.get('path'))
            self.file(path, mime=details['mime'], download=params.get('download') == '1')
        else:
            self.json({'error': 'Not found.'}, 404)

    def file(self, path, mime=None, download=False, cache=IMMUTABLE):
        if not path or not path.is_file():
            self.json({'error': 'This image is no longer available. Rescan the folder to refresh.'}, 404)
            return
        self.send_response(200)
        self.send_header('Content-Type', mime or mimetypes.guess_type(path)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(path.stat().st_size))
        self.send_header('Cache-Control', cache)
        self.send_header('X-Content-Type-Options', 'nosniff')
        if download:
            fallback = re.sub(r'[^A-Za-z0-9._-]', '_', path.name)
            self.send_header('Content-Disposition', f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(path.name)}")
        self.end_headers()
        with path.open('rb') as stream:
            while chunk := stream.read(256 * 1024):
                self.wfile.write(chunk)


def running(url: str):
    """Whether this app already answers at url."""
    try:
        with urllib.request.urlopen(f'{url}/api/status', timeout=1) as response:
            return json.load(response).get('app') == APP['name']
    except (OSError, ValueError):
        return False


def hand_over(url: str, folder: str | None):
    """Point an already running server at a folder. Returns an error message, or None."""
    if not folder:
        return None
    request = urllib.request.Request(f'{url}/api/folder', json.dumps({'path': folder}).encode(), {'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(request, timeout=10).close()
    except urllib.error.HTTPError as error:
        return json.load(error).get('error', 'The folder could not be opened.')
    return None


def main():
    parser = argparse.ArgumentParser(prog=APP['slug'], description='Browse and search the images in a folder.')
    parser.add_argument('folder', nargs='?', help='folder to show; defaults to the last one opened')
    parser.add_argument('--port', type=int, default=APP['port'])
    parser.add_argument('--data-dir', type=Path, default=default_data_dir())
    parser.add_argument('--no-watch', action='store_true', help='scan only on request, not every minute')
    parser.add_argument('--open-browser', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')
    url = f'http://127.0.0.1:{args.port}'
    folder = str(Path(args.folder).expanduser().absolute()) if args.folder else None
    if running(url):
        if error := hand_over(url, folder):
            sys.exit(error)
        print(f'{APP["name"]} is already running at {url}', flush=True)
        if args.open_browser:
            webbrowser.open(url)
        return
    app = App(args.data_dir)
    try:
        if folder:
            app.open(folder)
        elif app.recent() and Path(app.recent()[0]).is_dir():
            app.open(app.recent()[0])
    except ValueError as error:
        sys.exit(str(error))
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    except OSError:
        sys.exit(f'Port {args.port} is in use. Choose another with --port.')
    server.app = app
    if not args.no_watch:
        def watch():
            while not threading.Event().wait(WATCH_SECONDS):
                if app.library:
                    app.library.scan()
        threading.Thread(target=watch, daemon=True).start()
    threading.Thread(target=app.encoder.warm, daemon=True).start()
    threading.Thread(target=layout.warm, daemon=True).start()
    print(f'{APP["name"]} is running at {url}', flush=True)
    if args.open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == '__main__':
    main()
