import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from server.updates import CHECK_EVERY, LATEST, Updates

RELEASE = {'tag_name': 'v0.2.0', 'html_url': 'https://github.com/chaseleantj/orchard-photos/releases/tag/v0.2.0'}


def reply(body):
    return io.BytesIO(json.dumps(body).encode())


class UpdatesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'updates.json'
        self.updates = Updates(self.path, '0.1.0', 'Orchard/0.1.0')

    def test_github_is_never_asked_until_the_check_is_turned_on(self):
        with patch('urllib.request.urlopen') as urlopen:
            self.assertEqual(self.updates.status(), {'enabled': False, 'update': None})
            self.updates.turn(False)
            self.assertEqual(self.updates.status(), {'enabled': False, 'update': None})
        urlopen.assert_not_called()

    def test_a_newer_release_is_offered_with_its_page_and_asked_for_once_a_day(self):
        self.updates.turn(True)
        with patch('urllib.request.urlopen', side_effect=lambda *_, **__: reply(RELEASE)) as urlopen, patch('time.time', return_value=1_000_000):
            self.assertEqual(self.updates.status(), {'enabled': True, 'update': {'version': '0.2.0', 'url': RELEASE['html_url']}})
            # A restart reads the answer from the file.
            self.assertEqual(Updates(self.path, '0.1.0', 'Orchard/0.1.0').status()['update']['version'], '0.2.0')
        request = urlopen.call_args.args[0]
        self.assertEqual((request.full_url, request.get_header('User-agent'), urlopen.call_args.kwargs['timeout'] <= 5), (LATEST, 'Orchard/0.1.0', True))
        self.assertEqual(urlopen.call_count, 1)
        with patch('urllib.request.urlopen', side_effect=lambda *_, **__: reply({**RELEASE, 'tag_name': 'v0.3.0'})) as urlopen, \
                patch('time.time', return_value=1_000_000 + CHECK_EVERY):
            self.assertEqual(self.updates.status()['update']['version'], '0.3.0')
        self.assertEqual(urlopen.call_count, 1)

    def test_the_same_or_an_older_or_unreadable_version_offers_nothing(self):
        self.updates.turn(True)
        for tag in ('v0.1.0', '0.0.9', 'nightly', None):
            with self.subTest(tag=tag), patch('urllib.request.urlopen', return_value=reply({**RELEASE, 'tag_name': tag})):
                self.path.write_text(json.dumps({'enabled': True}))
                self.assertEqual(self.updates.status(), {'enabled': True, 'update': None})

    def test_a_link_off_github_s_release_pages_is_not_offered(self):
        self.updates.turn(True)
        with patch('urllib.request.urlopen', return_value=reply({**RELEASE, 'html_url': 'https://example.com/orchard'})):
            self.assertIsNone(self.updates.status()['update'])

    def test_failures_stay_silent_and_wait_a_day(self):
        not_found = urllib.error.HTTPError(LATEST, 404, 'Not Found', None, io.BytesIO(b'{"message": "Not Found"}'))
        for failure in (not_found, urllib.error.URLError('offline'), TimeoutError('timed out'), ValueError('not JSON')):
            with self.subTest(failure=failure):
                self.path.write_text(json.dumps({'enabled': True}))
                with patch('urllib.request.urlopen', side_effect=failure):
                    self.assertEqual(self.updates.status(), {'enabled': True, 'update': None})
                with patch('urllib.request.urlopen') as urlopen:
                    self.updates.status()
                urlopen.assert_not_called()

    def test_turning_it_off_keeps_the_last_answer_for_turning_it_back_on(self):
        self.updates.turn(True)
        with patch('urllib.request.urlopen', return_value=reply(RELEASE)):
            self.updates.status()
        self.updates.turn(False)
        self.updates.turn(True)
        with patch('urllib.request.urlopen') as urlopen:
            self.assertEqual(self.updates.status()['update']['version'], '0.2.0')
        urlopen.assert_not_called()

    def test_a_damaged_file_reads_as_off(self):
        self.path.write_text('[not a dict')
        self.assertFalse(self.updates.status()['enabled'])
        self.path.write_text('["enabled"]')
        self.assertFalse(self.updates.status()['enabled'])


if __name__ == '__main__':
    unittest.main()
