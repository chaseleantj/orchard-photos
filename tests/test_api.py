import io
import json
from email.message import Message
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from server.api import APP, RECENT_LIMIT, App, Handler

PORT = APP['port']


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

    def test_status_before_any_folder_is_open(self):
        status = self.app.status()
        self.assertEqual((status['app'], status['folder'], status['library'], status['recent']), (APP['name'], None, None, []))
        with self.assertRaisesRegex(ValueError, 'Choose a folder'):
            self.app.current()


class HandlerTests(unittest.TestCase):
    def dispatch(self, path, headers=None, post=False, body=b''):
        handler = Handler.__new__(Handler)
        handler.path = path
        handler.headers = Message()
        for key, value in (headers if headers is not None else {'Host': f'localhost:{PORT}'}).items():
            handler.headers[key] = value
        handler.server = SimpleNamespace(app=Mock(), server_port=PORT)
        handler.json = Mock()
        handler.file = Mock()
        handler.rfile = io.BytesIO(body)
        handler.dispatch(post)
        return handler

    def test_foreign_hosts_origins_and_cross_site_requests_are_rejected(self):
        for headers in ({}, {'Host': 'attacker.example'}, {'Host': 'localhost.attacker.example'},
                        {'Host': f'localhost:{PORT}', 'Origin': 'https://attacker.example'},
                        {'Host': f'localhost:{PORT}', 'Origin': 'null'},
                        {'Host': f'localhost:{PORT}', 'Sec-Fetch-Site': 'cross-site'}):
            with self.subTest(headers=headers):
                handler = self.dispatch('/api/status', headers)
                self.assertEqual(handler.json.call_args.args[1], 403)
                handler.server.app.status.assert_not_called()

    def test_local_browser_and_dev_server_origins_are_allowed(self):
        for origin in (f'http://localhost:{PORT}', f'http://127.0.0.1:{PORT}', f'http://localhost:{APP["devPort"]}'):
            with self.subTest(origin=origin):
                handler = self.dispatch('/api/status', {'Host': f'127.0.0.1:{PORT}', 'Origin': origin})
                handler.server.app.status.assert_called_once_with()

    def test_custom_port_accepts_same_origin(self):
        handler = Handler.__new__(Handler)
        handler.server = SimpleNamespace(server_port=4319)
        handler.headers = Message()
        handler.headers['Host'] = 'localhost:4319'
        handler.headers['Origin'] = 'http://localhost:4319'
        self.assertTrue(handler.allowed())
        handler.headers.replace_header('Origin', 'http://localhost:bad')
        self.assertFalse(handler.allowed())

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
                handler = self.dispatch('/api/search/image', {'Host': f'localhost:{PORT}', 'Content-Length': size}, post=True)
                self.assertEqual(handler.json.call_args.args[1], 400)
                handler.server.app.current.return_value.pictures.assert_not_called()

    def test_opening_a_folder_reads_its_path_from_the_body(self):
        body = json.dumps({'path': '/Volumes/Photos'}).encode()
        handler = self.dispatch('/api/folder', {'Host': f'localhost:{PORT}', 'Content-Length': str(len(body))}, post=True, body=body)
        handler.server.app.open.assert_called_once_with('/Volumes/Photos')
        for broken in (b'not json', b'[1, 2]'):
            with self.subTest(body=broken):
                handler = self.dispatch('/api/folder', {'Host': f'localhost:{PORT}', 'Content-Length': str(len(broken))}, post=True, body=broken)
                self.assertEqual(handler.json.call_args.args[1], 400)
                handler.server.app.open.assert_not_called()


if __name__ == '__main__':
    unittest.main()
