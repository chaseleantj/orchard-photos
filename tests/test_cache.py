import unittest
from unittest.mock import Mock, patch

from server.cache import while_open


class CacheTests(unittest.TestCase):
    def test_windows_waits_for_a_reader_before_replacing_a_file(self):
        change = Mock(side_effect=[PermissionError, PermissionError, None])
        with patch('server.cache.sys.platform', 'win32'), patch('server.cache.time.sleep'):
            while_open(change, 'target')
        self.assertEqual(change.call_count, 3)
        with patch('server.cache.sys.platform', 'darwin'), self.assertRaises(PermissionError):
            while_open(Mock(side_effect=PermissionError))


if __name__ == '__main__':
    unittest.main()
