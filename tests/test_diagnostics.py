import logging
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from server.diagnostics import LastError, redact, report

HOME = Path('/Users/someone')
FOLDER = HOME / 'Pictures' / 'Family'


def library(**status):
    status = {'counts': {'images': 1200, 'files': 1210, 'duplicates': 10, 'nearDuplicates': 4, 'unreadable': 3},
              'skipped': {'raw': 312, 'video': 48}, 'scan': {'state': 'ready'}, 'updated': '2026-10-17T09:30:12.5+00:00',
              'search': {'state': 'ready', 'indexed': 1200, 'total': 1200, 'downloaded': True}, **status}
    return SimpleNamespace(folder=FOLDER, status=lambda: status)


def app(engine='Core ML', folder=None, window=None):
    return SimpleNamespace(library=folder, window=window, encoder=SimpleNamespace(engine=engine, downloaded=lambda: engine is not None))


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        for target, value in (('server.diagnostics.Path.home', HOME), ('server.diagnostics.preferred_engine', 'Core ML')):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.last = patch('server.diagnostics.LAST_ERROR', LastError())
        self.last.start()
        self.addCleanup(self.last.stop)

    def test_the_report_names_versions_the_encoder_and_the_library_s_counts_and_state(self):
        text = report(app(folder=library()), 'Orchard 0.1.0')
        lines = text.splitlines()
        self.assertEqual(lines[0], 'Orchard 0.1.0')
        for line in ('Image encoder: Core ML', 'Search model: downloaded', 'Shown in: browser',
                     'Images: 1,200, unreadable 3, RAW skipped 312, videos skipped 48',
                     'Scan: ready, last finished 2026-10-17 09:30 UTC', 'Visual search: ready, 1,200 of 1,200 prepared', 'Last error: none'):
            self.assertIn(line, lines)
        for prefix in ('System: ', 'Python: ', 'ONNX Runtime: '):
            self.assertTrue(any(line.startswith(prefix) for line in lines), prefix)

    def test_the_encoder_says_when_it_fell_back_or_has_not_loaded(self):
        self.assertIn('Image encoder: CPU, after Core ML failed', report(app('CPU'), 'Orchard'))
        text = report(app(None), 'Orchard')
        self.assertIn('Image encoder: not loaded yet, will try Core ML', text)
        self.assertIn('Search model: not downloaded', text)
        self.assertIn('Folder: none open', text)

    def test_the_window_is_named_with_its_toolkit_version(self):
        with patch('server.diagnostics.metadata.version', return_value='6.2.1'):
            self.assertIn('Shown in: window (pywebview 6.2.1)', report(app(window=Mock()), 'Orchard'))

    def logger(self):
        """A logger that passes everything to a fresh LastError, which keeps only warnings and errors."""
        handler, logger = LastError(), logging.getLogger('test.diagnostics')
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        return handler, logger

    def test_errors_keep_no_file_names_or_folder_paths(self):
        handler, logger = self.logger()
        try:
            raise OSError(f"cannot identify image file '{FOLDER}/Beach day.jpg'")
        except OSError:
            logger.exception('Scan failed')
        self.assertTrue(handler.message.startswith(f"Scan failed: OSError: cannot identify image file '{FOLDER}/Beach day.jpg' ("))
        with patch('server.diagnostics.LAST_ERROR', handler):
            text = report(app(folder=library(scan={'state': 'error', 'error': f'{FOLDER} is not available. Reconnect its drive.'})), 'Orchard')
        self.assertIn("Last error: Scan failed: OSError: cannot identify image file '<folder>' (", text)
        self.assertIn('Scan: error, <folder> is not available. Reconnect its drive.', text)
        self.assertNotIn('Beach', text)
        self.assertNotIn('Family', text)
        self.assertEqual(redact(f'{HOME}/Library/Application Support/orchard/models failed', None), '~/Library/Application Support/orchard/models failed')

    def test_only_warnings_and_errors_are_remembered_on_one_line(self):
        handler, logger = self.logger()
        logger.info('routine')
        self.assertIsNone(handler.message)
        logger.warning('Core ML could not run\nsecond line')
        self.assertRegex(handler.message, r'^Core ML could not run \(\d{4}-\d\d-\d\d \d\d:\d\d UTC\)$')


if __name__ == '__main__':
    unittest.main()
