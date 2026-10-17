import contextlib
from email.message import Message
import errno
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from server.api import (
    APP,
    RECENT_LIMIT,
    SECURITY_HEADERS,
    App,
    Handler,
    Server,
    arguments,
    default_data_dir,
    main,
    open_browser,
    picker_command,
    reveal,
    wsl_explorer,
)

PORT = APP['port']
LOCAL = {'Host': f'localhost:{PORT}'}
JSON = {**LOCAL, 'Content-Type': 'application/json'}


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.app = App(self.home / 'data')
        # Opening starts a scan in the background; the tests look only at what opening decides.
        patcher = patch('server.api.threading.Thread')
        patcher.start()
        self.addCleanup(patcher.stop)

    def folder(self, name):
        path = self.home / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def test_paths_that_are_not_readable_folders_are_explained(self):
        (self.home / 'photo.jpg').write_bytes(b'')
        for value, message in (('', 'Enter the path'), ('relative/photos', 'full path'), (str(self.home / 'missing'), 'does not exist'),
                               (str(self.home / 'photo.jpg'), 'is a file'), (str(self.home / 'data'), 'keeps its cache')):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, message):
                self.app.open(value)
        self.assertIsNone(self.app.library)

    def test_paths_copied_with_quotes_open_and_windows_gets_a_windows_example(self):
        self.assertEqual(self.app.open(f'  "{self.folder("photos")}" ').folder, self.home / 'photos')
        with patch('server.api.sys.platform', 'win32'), self.assertRaisesRegex(ValueError, r'like C:\\Users'):
            self.app.open('relative/photos')

    def test_windows_keeps_data_in_local_app_data(self):
        with patch('server.api.sys.platform', 'win32'), patch.dict('os.environ', {'LOCALAPPDATA': str(self.home)}):
            self.assertEqual(default_data_dir(), self.home / APP['slug'])

    def test_each_folder_has_its_own_cache_and_the_old_one_stops(self):
        first = self.app.open(str(self.folder('one')))
        self.assertIs(self.app.open(str(self.home / 'one' / '..' / 'one')), first)
        second = self.app.open(str(self.folder('two')))
        self.assertTrue(first.closed.is_set())
        self.assertFalse(second.closed.is_set())
        self.assertNotEqual(first.directory, second.directory)
        self.assertEqual(self.app.status()['folder']['path'], str(self.home / 'two'))

    def test_recent_folders_are_newest_first_bounded_and_forgettable(self):
        for number in range(RECENT_LIMIT + 2):
            self.app.open(str(self.folder(f'folder-{number}')))
        recent = self.app.recent()
        self.assertEqual(len(recent), RECENT_LIMIT)
        self.assertEqual(recent[0], str(self.home / f'folder-{RECENT_LIMIT + 1}'))
        self.app.open(str(self.home / 'folder-5'))
        self.assertEqual(self.app.recent()[0], str(self.home / 'folder-5'))
        self.app.forget(str(self.home / 'folder-6'))
        self.assertNotIn(str(self.home / 'folder-6'), self.app.recent())
        listed = [entry['path'] for entry in self.app.status()['recent']]
        self.assertNotIn(str(self.home / 'folder-5'), listed, 'The open folder is not offered as a recent one')

    def test_the_window_asks_for_folders_with_its_own_dialog(self):
        self.app.open(str(self.folder('photos')))
        self.app.window = Mock()
        self.app.window.choose_folder.return_value = '/Volumes/Photos'
        with patch('server.api.picker_command', return_value=None):
            self.assertTrue(self.app.status()['picker'])
            self.assertEqual(self.app.choose(), '/Volumes/Photos')
            self.app.window.choose_folder.assert_called_once_with(self.home / 'photos')
            self.app.window = None
            self.assertFalse(self.app.status()['picker'])
            with self.assertRaisesRegex(ValueError, 'Type the folder path'):
                self.app.choose()

    def test_status_before_any_folder_is_open(self):
        status = self.app.status()
        self.assertEqual((status['app'], status['folder'], status['library'], status['recent']), (APP['name'], None, None, []))
        self.assertEqual(status['model'], {'present': False, 'size': self.app.encoder.size})
        with self.assertRaisesRegex(ValueError, 'Choose a folder'):
            self.app.current()

    def test_the_version_is_app_json_s_and_npm_s_files_agree(self):
        self.assertEqual(self.app.status()['version'], APP['version'])
        root = Path(__file__).resolve().parent.parent
        package = json.loads((root / 'package.json').read_text(encoding='utf-8'))
        lock = json.loads((root / 'package-lock.json').read_text(encoding='utf-8'))
        self.assertEqual((package['version'], lock['version'], lock['packages']['']['version']), (APP['version'],) * 3)


class HandlerTests(unittest.TestCase):
    def dispatch(self, path, headers=LOCAL, post=False, body=b''):
        handler = Handler.__new__(Handler)
        handler.command = 'POST' if post else 'GET'
        handler.path = path
        handler.headers = Message()
        for key, value in headers.items():
            handler.headers[key] = value
        handler.server = SimpleNamespace(app=Mock(), server_port=PORT)
        handler.json = Mock()
        handler.file = Mock()
        handler.rfile = io.BytesIO(body)
        handler.dispatch(post)
        return handler

    def test_foreign_hosts_origins_and_other_sites_are_refused(self):
        # Other local ports count as other pages, Vite's included, and a Host without this port may be DNS rebinding.
        for headers in ({}, {'Host': 'attacker.example'}, {'Host': f'localhost.attacker.example:{PORT}'}, {'Host': 'localhost'},
                        {'Host': f'localhost:{PORT + 1}'}, {'Host': f'attacker.example:{PORT}'},
                        {**LOCAL, 'Origin': 'https://attacker.example'}, {**LOCAL, 'Origin': 'null'},
                        {**LOCAL, 'Origin': f'http://localhost:{APP["devPort"]}'}, {**LOCAL, 'Origin': f'http://127.0.0.1:{PORT + 1}'},
                        {**LOCAL, 'Origin': f'https://localhost:{PORT}'}, {**LOCAL, 'Origin': f'http://localhost:{PORT}/'},
                        {**LOCAL, 'Sec-Fetch-Site': 'cross-site'}, {**LOCAL, 'Sec-Fetch-Site': 'same-site'}):
            for post in (False, True):
                with self.subTest(headers=headers, post=post), self.assertLogs(level='WARNING') as logs:
                    handler = self.dispatch('/api/folder' if post else '/api/status', {**headers, 'Content-Type': 'application/json'}, post, b'{}')
                    self.assertEqual(handler.json.call_args.args[1], 403)
                    self.assertIn('Refused', logs.output[0])
                    self.assertEqual(handler.server.app.method_calls, [])

    def test_the_own_page_and_programs_without_a_page_are_allowed(self):
        for host in (f'127.0.0.1:{PORT}', f'localhost:{PORT}', f'[::1]:{PORT}'):
            for extra in ({}, {'Origin': f'http://{host}', 'Sec-Fetch-Site': 'same-origin'}, {'Sec-Fetch-Site': 'none'}):
                with self.subTest(host=host, extra=extra):
                    handler = self.dispatch('/api/status', {'Host': host, **extra})
                    handler.server.app.status.assert_called_once_with()

    def test_a_link_on_another_page_opens_the_page_but_reaches_nothing_else(self):
        link = {**LOCAL, 'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Dest': 'document'}
        handler = self.dispatch('/', link)
        handler.file.assert_called_once()
        for path, headers, post in (('/api/images/abc/original', link, False), ('/', {**link, 'Sec-Fetch-Dest': 'iframe'}, False),
                                    ('/', {**link, 'Origin': 'https://attacker.example', 'Content-Type': 'application/json'}, True)):
            with self.subTest(path=path, headers=headers), self.assertLogs(level='WARNING'):
                handler = self.dispatch(path, headers, post)
                self.assertEqual(handler.json.call_args.args[1], 403)
                handler.file.assert_not_called()

    def test_custom_port_accepts_same_origin(self):
        handler = Handler.__new__(Handler)
        handler.server = SimpleNamespace(server_port=4319)
        handler.headers = Message()
        handler.headers['Host'] = 'localhost:4319'
        handler.headers['Origin'] = 'http://localhost:4319'
        self.assertTrue(handler.allowed('/api/status'))
        handler.headers.replace_header('Origin', 'http://localhost:bad')
        self.assertFalse(handler.allowed('/api/status'))

    def test_posts_need_a_type_that_a_form_cannot_send(self):
        # A form can post these without the browser asking the server first.
        for kind in (None, 'text/plain', 'application/x-www-form-urlencoded', 'multipart/form-data; boundary=x'):
            for path in ('/api/folder', '/api/scan', '/api/search/image'):
                with self.subTest(kind=kind, path=path):
                    handler = self.dispatch(path, {**LOCAL, **({'Content-Type': kind} if kind else {}), 'Content-Length': '2'}, True, b'{}')
                    self.assertEqual(handler.json.call_args.args[1], 415)
                    self.assertEqual(handler.server.app.method_calls, [])
        for path, kind in (('/api/scan', 'application/json; charset=utf-8'), ('/api/search/image', 'image/png'),
                           ('/api/search/image', 'application/octet-stream')):
            with self.subTest(kind=kind, path=path):
                handler = self.dispatch(path, {**LOCAL, 'Content-Type': kind, 'Content-Length': '2'}, True, b'{}')
                handler.server.app.current.assert_called_once_with()
        handler = self.dispatch('/api/folder', {**LOCAL, 'Content-Type': 'image/png', 'Content-Length': '2'}, True, b'{}')
        self.assertEqual(handler.json.call_args.args[1], 415)

    def test_every_response_says_it_may_not_be_framed_or_sniffed(self):
        server = Server(('127.0.0.1', 0), Handler)
        server.app = Mock(**{'status.return_value': {}})
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        own, rebound = f'127.0.0.1:{server.server_port}', f'attacker.example:{server.server_port}'
        for method, path, host, status in (('GET', '/api/status', own, 200), ('GET', '/', own, 200), ('PUT', '/api/status', own, 501),
                                           ('GET', '/api/status', rebound, 403)):
            with self.subTest(method=method, path=path, host=host), self.assertLogs(level='WARNING') if status == 403 else contextlib.nullcontext():
                connection = HTTPConnection('127.0.0.1', server.server_port, timeout=10)
                self.addCleanup(connection.close)
                connection.request(method, path, headers={'Host': host})
                response = connection.getresponse()
                response.read()
                self.assertEqual(response.status, status)
                for name, value in SECURITY_HEADERS.items():
                    self.assertEqual(response.getheader(name), value)
        self.assertIn("frame-ancestors 'none'", SECURITY_HEADERS['Content-Security-Policy'])
        self.assertEqual(SECURITY_HEADERS['X-Frame-Options'], 'DENY')

    def test_static_and_image_path_traversal_cannot_read_files(self):
        for path in ('/../server/api.py', '/../../etc/passwd', '/api/images/../original', '/api/images/%2e%2e/original'):
            with self.subTest(path=path):
                handler = self.dispatch(path)
                self.assertEqual(handler.json.call_args.args[1], 404)
                handler.file.assert_not_called()
                handler.server.app.current.assert_not_called()

    def test_image_upload_limit_is_checked_before_reading(self):
        for size in ('0', str(20 * 1024 * 1024 + 1), 'invalid'):
            with self.subTest(size=size):
                handler = self.dispatch('/api/search/image', {**LOCAL, 'Content-Type': 'image/jpeg', 'Content-Length': size}, post=True)
                self.assertEqual(handler.json.call_args.args[1], 400)
                handler.server.app.current.return_value.pictures.assert_not_called()

    def test_opening_a_folder_reads_its_path_from_the_body(self):
        body = json.dumps({'path': '/Volumes/Photos'}).encode()
        handler = self.dispatch('/api/folder', {**JSON, 'Content-Length': str(len(body))}, post=True, body=body)
        handler.server.app.open.assert_called_once_with('/Volumes/Photos')
        for broken in (b'not json', b'[1, 2]'):
            with self.subTest(body=broken):
                handler = self.dispatch('/api/folder', {**JSON, 'Content-Length': str(len(broken))}, post=True, body=broken)
                self.assertEqual(handler.json.call_args.args[1], 400)
                handler.server.app.open.assert_not_called()

    def test_a_second_launch_brings_the_window_forward_when_there_is_one(self):
        for window in (Mock(), None):
            with self.subTest(window=window):
                handler = self.dispatch('/api/window/front', JSON, post=True)
                handler.server.app.window = window
                handler.dispatch(True)
                self.assertEqual(handler.json.call_args.args[0], {'window': window is not None})
                if window:
                    window.bring_forward.assert_called_once_with()

    def test_linux_folder_dialog_uses_zenity_then_kdialog_then_none(self):
        for installed, program in ((['zenity', 'kdialog'], 'zenity'), (['kdialog'], 'kdialog'), ([], None)):
            with self.subTest(installed=installed), patch('server.api.sys.platform', 'linux'), \
                    patch('server.api.shutil.which', lambda name: name if name in installed else None):  # noqa: B023
                command = picker_command(None)
                self.assertEqual(command and command[0], program)


    def test_linux_without_xdg_open_names_the_package_to_show_a_folder(self):
        with patch('server.api.sys.platform', 'linux'), patch('server.api.wsl_explorer', return_value=None), patch('server.api.shutil.which', return_value=None), \
                patch('server.api.subprocess.Popen') as popen, self.assertRaisesRegex(ValueError, 'sudo apt update && sudo apt install xdg-utils'):
            reveal(Path('/photos/a.jpg'))
        popen.assert_not_called()

    def test_linux_shows_a_folder_with_xdg_open_and_says_when_it_finds_no_app(self):
        # xdg-open exits with 3 when nothing can open a folder. One still running when the wait ends found an app.
        for outcome, fails in ((0, False), (3, True), (subprocess.TimeoutExpired('xdg-open', 1), False)):
            with self.subTest(outcome=outcome), patch('server.api.sys.platform', 'linux'), patch('server.api.wsl_explorer', return_value=None), \
                    patch('server.api.shutil.which', return_value='/usr/bin/xdg-open'), patch('server.api.subprocess.Popen') as popen:
                popen.return_value.wait.side_effect = [outcome]
                if fails:
                    with self.assertRaisesRegex(ValueError, 'xdg-open found no app'):
                        reveal(Path('/photos/a.jpg'))
                else:
                    reveal(Path('/photos/a.jpg'))
                self.assertEqual(popen.call_args.args[0], ['xdg-open', str(Path('/photos'))])

    def test_wsl_is_recognised_by_its_kernel(self):
        for release, expected in (('5.15.167.4-microsoft-standard-WSL2', '/mnt/c/Windows/explorer.exe'), ('6.8.0-1021-azure', None)):
            with self.subTest(release=release), patch.object(Path, 'read_text', return_value=release), \
                    patch('server.api.shutil.which', return_value='/mnt/c/Windows/explorer.exe'):
                self.assertEqual(wsl_explorer(), expected)
        with patch.object(Path, 'read_text', side_effect=FileNotFoundError):
            self.assertIsNone(wsl_explorer())

    def test_under_wsl_explorer_shows_the_file_and_opens_the_page_in_windows(self):
        explorer = '/mnt/c/Windows/explorer.exe'
        with patch('server.api.sys.platform', 'linux'), patch('server.api.wsl_explorer', return_value=explorer), \
                patch('server.api.subprocess.run', return_value=SimpleNamespace(stdout='\\\\wsl.localhost\\Ubuntu\\photos\\a b.jpg\n')) as run, \
                patch('server.api.subprocess.Popen') as popen, patch('server.api.webbrowser.open') as browser:
            reveal(Path('/photos/a b.jpg'))
            self.assertEqual(run.call_args.args[0], ['wslpath', '-w', str(Path('/photos/a b.jpg'))])
            self.assertEqual(popen.call_args.args[0], [explorer, '/select,', '\\\\wsl.localhost\\Ubuntu\\photos\\a b.jpg'])
            open_browser('http://127.0.0.1:4400')
            self.assertEqual(popen.call_args.args[0], [explorer, 'http://127.0.0.1:4400'])
        browser.assert_not_called()

    def test_without_a_browser_the_address_is_printed_to_open_by_hand(self):
        for opened in (True, False):
            with self.subTest(opened=opened), patch('server.api.wsl_explorer', return_value=None), \
                    patch('server.api.webbrowser.open', return_value=opened), patch('server.api.print') as say:
                open_browser('http://127.0.0.1:4400')
            self.assertEqual(say.called, not opened)
            if not opened:
                self.assertIn('Open http://127.0.0.1:4400 in one', say.call_args.args[0])

class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        (self.home / 'photos').mkdir()
        # The browser opens the way it does outside WSL, wherever the tests run.
        patchers = [patch(f'server.api.{target}') for target in ('become_app', 'webbrowser.open', 'print')] + [patch('server.api.wsl_explorer', return_value=None)]
        _, self.open_browser, _, _ = [patcher.start() for patcher in patchers]
        for patcher in patchers:
            self.addCleanup(patcher.stop)
        # A real folder would be scanned in the background; these tests look only at how Orchard starts and stops.
        self.library = Mock()
        patcher = patch('server.api.App.open', autospec=True, side_effect=lambda app, value: setattr(app, 'library', self.library))
        patcher.start()
        self.addCleanup(patcher.stop)

    def launch(self, *options):
        # Port 0 takes any free port, so no running copy answers.
        main([str(self.home / 'photos'), '--port', '0', '--data-dir', str(self.home / 'data'), '--no-watch', *options])

    def test_the_last_of_window_and_browser_wins(self):
        self.assertEqual(arguments(['--window', '--browser']).show, 'browser')
        self.assertEqual(arguments(['--browser', '--window']).show, 'window')
        self.assertIsNone(arguments([]).show)

    def test_closing_the_window_stops_the_server_and_background_work(self):
        with patch('server.api.unavailable', return_value=None), patch('server.api.Window') as window, \
                patch('server.api.ThreadingHTTPServer.shutdown', autospec=True, wraps=ThreadingHTTPServer.shutdown) as shutdown, \
                patch('server.api.ThreadingHTTPServer.server_close', autospec=True, wraps=ThreadingHTTPServer.server_close) as close:
            self.launch('--window')
        window.return_value.run.assert_called_once_with()
        shutdown.assert_called_once()
        close.assert_called_once()
        self.assertEqual(close.call_args.args[0].socket.fileno(), -1, 'The port is released')
        self.library.close.assert_called_once_with()

    def test_without_a_window_toolkit_it_opens_the_browser(self):
        with patch('server.api.unavailable', return_value='there is no display'), patch('server.api.Window') as window, \
                patch('server.api.ThreadingHTTPServer.serve_forever', side_effect=KeyboardInterrupt), \
                patch('server.api.threading.Timer') as timer:
            self.launch('--window')
        window.assert_not_called()
        timer.call_args.args[1]()
        self.open_browser.assert_called_once()

    def test_a_second_launch_hands_over_and_uses_the_running_window(self):
        for show, has_window, opens_browser in (('--window', True, False), ('--window', False, True), ('--browser', True, True)):
            with self.subTest(show=show, has_window=has_window), patch('server.api.running', return_value=True), \
                    patch('server.api.hand_over', return_value=None) as hand_over, \
                    patch('server.api.bring_forward', return_value=has_window), patch('server.api.Window') as window:
                self.open_browser.reset_mock()
                self.launch(show)
                hand_over.assert_called_once()
                window.assert_not_called()
                self.assertEqual(self.open_browser.called, opens_browser)

    def test_a_port_in_use_or_reserved_is_explained(self):
        with Server(('127.0.0.1', 0), Handler) as taken, self.assertRaises(OSError):
            Server(('127.0.0.1', taken.server_port), Handler)
        for code, message in ((errno.EADDRINUSE, 'used by another program'), (errno.EACCES, 'reserved by the system')):
            with self.subTest(message=message), patch('server.api.running', return_value=False), \
                    patch('server.api.Server', side_effect=OSError(code, 'refused')), self.assertRaisesRegex(SystemExit, message):
                self.launch('--browser')


if __name__ == '__main__':
    unittest.main()
