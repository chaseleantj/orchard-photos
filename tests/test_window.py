import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from server import window


@unittest.skipIf(sys.platform == 'win32', 'The Mac app needs symlinks, which need Developer Mode on Windows')
class AppBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / 'Orchard.app'
        (self.bundle / 'Contents' / 'MacOS').mkdir(parents=True)
        self.environment = self.root / 'venv'
        self.environment.mkdir()
        (self.bundle / 'Contents' / 'MacOS' / 'python').symlink_to(self.environment / window.APP_PYTHON)
        self.base = self.root / 'Python.framework' / 'Versions' / '3.13'
        for target, value in (('sys.platform', 'darwin'), ('sys.prefix', str(self.environment)), ('sys.base_prefix', str(self.base)),
                              ('sysconfig.get_config_var', lambda name: 'Python')):
            patcher = patch(f'server.window.{target}', value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_started_by_the_app_it_reruns_through_the_link_inside_it(self):
        with patch.dict(os.environ, {window.BUNDLE_VARIABLE: str(self.bundle)}), patch('server.window.os.execv') as execv:
            window.enter_app_bundle()
            self.assertNotIn(window.BUNDLE_VARIABLE, os.environ, 'The rerun process does not rerun again')
            self.assertTrue(os.environ['__PYVENV_LAUNCHER__'])
        link = self.environment / window.APP_PYTHON
        self.assertEqual(link.readlink(), self.base / 'Resources' / 'Python.app' / 'Contents' / 'MacOS' / 'Python')
        self.assertEqual(execv.call_args.args[0], self.bundle / 'Contents' / 'MacOS' / 'python')

    def test_started_any_other_way_it_carries_on(self):
        with patch.dict(os.environ, clear=True), patch('server.window.os.execv') as execv:
            window.enter_app_bundle()
        execv.assert_not_called()
        self.assertFalse((self.environment / window.APP_PYTHON).exists())

    def test_without_a_framework_build_it_shows_the_window_as_python(self):
        with patch.dict(os.environ, {window.BUNDLE_VARIABLE: str(self.bundle)}), patch('server.window.os.execv') as execv, \
                patch('server.window.sysconfig.get_config_var', return_value=None):
            window.enter_app_bundle()
        execv.assert_not_called()


class IconTests(unittest.TestCase):
    def test_each_platform_gets_an_icon_its_toolkit_can_read(self):
        from PIL import Image

        for platform, format in (('darwin', 'ICNS'), ('win32', 'ICO'), ('linux', 'PNG')):
            with patch('server.window.sys.platform', platform), patch('server.window.signal.signal'), patch('server.window.webview.start') as start:
                window.Window.run(None)
            with Image.open(start.call_args.kwargs['icon']) as icon:
                self.assertEqual(icon.format, format)
                if format == 'ICO':
                    # Windows picks the size it needs, from the title bar's 16 px to 256 px in Explorer.
                    self.assertTrue({(16, 16), (32, 32), (256, 256)} <= icon.info['sizes'])


class DragTests(unittest.TestCase):
    def test_images_can_be_dragged_out_of_the_grid(self):
        # Otherwise pywebview's page script cancels the drag of any image or link.
        with patch('webview.windows', []):
            self.assertTrue(window.Window('Orchard', 'http://127.0.0.1:1').view.draggable)


class AvailabilityTests(unittest.TestCase):
    def test_linux_without_a_display_uses_the_browser(self):
        with patch('server.window.sys.platform', 'linux'), patch.dict(os.environ, clear=True):
            self.assertEqual(window.unavailable(), 'there is no display')

    def test_a_missing_toolkit_is_explained_in_one_line(self):
        with patch('server.window.sys.platform', 'linux'), patch.dict(os.environ, {'DISPLAY': ':0'}), \
                patch('server.window.initialize', side_effect=window.webview.WebViewException('no GTK')):
            reason = window.unavailable()
        self.assertIn('sudo apt update && sudo apt install python3-gi gir1.2-webkit2-4.1', reason)
        self.assertNotIn('\n', reason)


if __name__ == '__main__':
    unittest.main()
