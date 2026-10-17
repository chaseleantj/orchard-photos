"""Loopback-only HTTP API and production web server. Serves one folder at a time; the folder can be changed live."""
import argparse
import errno
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
from urllib.parse import parse_qs, quote, urlparse
import urllib.error
import urllib.request
import webbrowser

from server.library import IMAGE_ID, Library
from server.semantic import Encoder
from server.window import Window, become_app, unavailable

ROOT = Path(__file__).resolve().parent.parent
APP = json.loads((ROOT / 'app.json').read_text(encoding='utf-8'))
RECENT_LIMIT = 10
WATCH_SECONDS = 60
UPLOAD_LIMIT = 20 * 1024 * 1024
FORM_LIMIT = 64 * 1024
IMMUTABLE = 'private, max-age=31536000, immutable'


def default_data_dir() -> Path:
    """Where the cache and model live: the platform's per-user application data folder."""
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / APP['slug']
    if sys.platform == 'win32':
        # Local rather than roaming, since the model is too large to follow the user between computers.
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / APP['slug']
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / APP['slug']


def tilde(path: Path) -> str:
    """A path as people write it: the home folder shortened to ~."""
    try:
        return '~' + os.sep + str(path.relative_to(Path.home())) if path != Path.home() else '~'
    except ValueError:
        return str(path)


class App:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.encoder = Encoder(self.data_dir / 'models')
        self.recent_path = self.data_dir / 'recent.json'
        self.library: Library | None = None
        self.window: Window | None = None
        self._lock = threading.Lock()

    def resolve(self, value) -> Path:
        # Explorer's Copy as path puts the path in quotes, which no folder name on Windows contains.
        text = str(value or '').strip().strip('"').strip()
        if not text:
            raise ValueError('Enter the path of a folder.')
        path = Path(text).expanduser()
        if not path.is_absolute():
            raise ValueError('Enter a full path, like C:\\Users\\you\\Pictures.' if sys.platform == 'win32' else 'Enter a full path, starting with / or ~.')
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

    def choose(self) -> str | None:
        """Ask for a folder with the window's dialog, or the system's in the browser. Returns None when cancelled."""
        start = self.library.folder if self.library else None
        if self.window:
            return self.window.choose_folder(start)
        command = picker_command(start)
        if not command:
            raise ValueError('Type the folder path instead.')
        return choose_folder(command)

    def close(self):
        if self.library:
            self.library.close()

    def current(self) -> Library:
        library = self.library
        if library is None:
            raise ValueError('Choose a folder of images first.')
        return library

    def recent(self) -> list[str]:
        try:
            saved = json.loads(self.recent_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return []
        return [path for path in saved if isinstance(path, str)] if isinstance(saved, list) else []

    def remember(self, folder: Path):
        paths = [str(folder)] + [path for path in self.recent() if path != str(folder)]
        self.recent_path.write_text(json.dumps(paths[:RECENT_LIMIT]), encoding='utf-8')

    def forget(self, value):
        self.recent_path.write_text(json.dumps([path for path in self.recent() if path != str(value)]), encoding='utf-8')

    def status(self):
        library = self.library
        recent = [{'path': path, 'label': tilde(Path(path)), 'available': Path(path).is_dir()}
                  for path in self.recent() if not library or path != str(library.folder)]
        result = {'app': APP['name'], 'platform': sys.platform, 'picker': self.window is not None or picker_command(None) is not None, 'recent': recent, 'folder': None, 'library': None,
                  'model': {'present': self.encoder.downloaded() or self.encoder.activity is not None,
                            'size': self.encoder.size, 'update': self.encoder.replaces()}}
        if library:
            result['folder'] = {'path': str(library.folder), 'label': tilde(library.folder),
                                'name': library.folder.name or str(library.folder), 'id': library.directory.name}
            result['library'] = library.status()
        return result


def picker_command(start: Path | None) -> list[str] | None:
    """The command that shows the system folder dialog, or None when this computer has none."""
    title = 'Choose a folder of images'
    if sys.platform == 'darwin':
        script = ['-e', 'on run argv', '-e', 'set prompt to item 1 of argv']
        if start:
            script += ['-e', 'POSIX path of (choose folder with prompt prompt default location (POSIX file (item 2 of argv)))']
        else:
            script += ['-e', 'POSIX path of (choose folder with prompt prompt)']
        return ['osascript', *script, '-e', 'end run', title, *([str(start)] if start else [])]
    if shutil.which('zenity'):
        return ['zenity', '--file-selection', '--directory', f'--title={title}', *([f'--filename={start}/'] if start else [])]
    if shutil.which('kdialog'):
        return ['kdialog', '--title', title, '--getexistingdirectory', *([str(start)] if start else [])]
    return None


def choose_folder(command: list[str]):
    """Ask with the system folder dialog. Returns None when cancelled."""
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def reveal(path: Path):
    if sys.platform == 'darwin':
        subprocess.Popen(['open', '-R', str(path)])
    elif sys.platform == 'win32':
        subprocess.Popen(['explorer', '/select,', str(path)])
    elif shutil.which('xdg-open'):
        subprocess.Popen(['xdg-open', str(path.parent)])
    else:
        raise ValueError('Showing the folder needs xdg-open. On Ubuntu: sudo apt update && sudo apt install xdg-utils')


def open_browser(url: str):
    """Open url in the default browser, or say to open it by hand when there is none, as on a fresh WSL."""
    if not webbrowser.open(url):
        print(f'No web browser was found. Open {url} in one.', flush=True)


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
                chosen = self.app.choose()
                if chosen:
                    self.app.open(chosen)
                self.json({**self.app.status(), 'cancelled': not chosen})
            elif route == ('/api/window/front', True):
                if self.app.window:
                    self.app.window.bring_forward()
                self.json({'window': self.app.window is not None})
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
        # The page went away mid-response. Windows reports it as ConnectionAbortedError, others as a broken pipe or reset.
        except ConnectionError:
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


class Server(ThreadingHTTPServer):
    # On Windows, SO_REUSEADDR lets a second program bind a port that is already taken, so a clash would go unnoticed.
    # Windows reuses a recently closed port without it.
    allow_reuse_address = sys.platform != 'win32'


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


def bring_forward(url: str) -> bool:
    """Ask an already running server to bring its window to the front. Returns whether it has a window."""
    request = urllib.request.Request(f'{url}/api/window/front', b'{}', {'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response).get('window') is True
    except (OSError, ValueError):
        return False


def arguments(argv=None):
    parser = argparse.ArgumentParser(prog=APP['slug'], description='Browse and search the images in a folder.')
    parser.add_argument('folder', nargs='?', help='folder to show; defaults to the last one opened')
    parser.add_argument('--port', type=int, default=APP['port'])
    parser.add_argument('--data-dir', type=Path, default=default_data_dir())
    parser.add_argument('--no-watch', action='store_true', help='scan only on request, not every minute')
    # The launcher passes --window, so a --browser after it wins.
    parser.add_argument('--window', dest='show', action='store_const', const='window', help='open in its own window')
    parser.add_argument('--browser', dest='show', action='store_const', const='browser', help='open in the browser instead')
    return parser.parse_args(argv)


def main(argv=None):
    args = arguments(argv)
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(name)s: %(message)s')
    url = f'http://127.0.0.1:{args.port}'
    folder = str(Path(args.folder).expanduser().absolute()) if args.folder else None

    def join_running():
        """Hand the folder to a copy of this app that already answers at url. Returns whether there was one."""
        if not running(url):
            return False
        if error := hand_over(url, folder):
            sys.exit(error)
        print(f'{APP["name"]} is already running at {url}', flush=True)
        if args.show == 'browser' or args.show == 'window' and not bring_forward(url):
            open_browser(url)
        return True

    if join_running():
        return
    if args.show == 'window':
        become_app(APP['name'])
    # The port stays fixed: the Dock app, a second launch and the page's saved settings all find the app by it.
    try:
        server = Server(('127.0.0.1', args.port), Handler)
    except OSError as error:
        # Another launch may have started the server since the check above.
        if join_running():
            return
        if error.errno in (errno.EACCES, getattr(errno, 'WSAEACCES', errno.EACCES)):
            # Windows reserves ranges of ports for Hyper-V and WSL, and other systems keep ports below 1024 for root.
            reserved = ' See the reserved ranges with: netsh int ipv4 show excludedportrange protocol=tcp' if sys.platform == 'win32' else ''
            sys.exit(f'Port {args.port} is reserved by the system. Start {APP["name"]} on another port with --port.{reserved}')
        sys.exit(f'Port {args.port} is used by another program. Quit that program, or start {APP["name"]} on another port with --port.')
    if args.show == 'window' and (reason := unavailable()):
        print(f'{APP["name"]} is opening in the browser, because {reason}', flush=True)
        args.show = 'browser'
    app = server.app = App(args.data_dir)
    try:
        if folder:
            app.open(folder)
        elif app.recent() and Path(app.recent()[0]).is_dir():
            app.open(app.recent()[0])
    except ValueError as error:
        sys.exit(str(error))
    if not args.no_watch:
        def watch():
            while not threading.Event().wait(WATCH_SECONDS):
                if app.library:
                    app.library.scan()
        threading.Thread(target=watch, daemon=True).start()
    if app.encoder.downloaded():
        # Load the model ahead of the first search, then index. A scan that finishes first indexes on its own, unless
        # Core ML failed meanwhile and the CPU's image encoder was still downloading.
        app.prepare()
    print(f'{APP["name"]} is running at {url}', flush=True)
    if args.show == 'window':
        # The window runs on the main thread, as macOS requires, and closing it quits.
        app.window = Window(APP['name'], url)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            app.window.run()
        except KeyboardInterrupt:
            pass
        server.shutdown()
        server.server_close()
        app.close()
        return
    if args.show == 'browser':
        threading.Timer(0.3, lambda: open_browser(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == '__main__':
    main()
