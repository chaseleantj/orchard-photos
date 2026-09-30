from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

from PIL import Image

from server.library import Library
from server.scanner import preview_path
from server.semantic import Encoder


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'photos'
        self.folder.mkdir()
        self.library = Library(self.folder, Path(self.temp.name) / 'cache', Encoder(Path(self.temp.name) / 'models'))

    def image(self, number, path=None, modified='2026-09-20T12:00:00Z', taken=None, mime='image/jpeg'):
        image_id = f'{number:064x}'
        path = path or f'photo-{number}.jpg'
        with self.library.scanner.connect() as db:
            db.execute('INSERT OR IGNORE INTO images VALUES (?,?,?,?,?,?,?)', (image_id, 32, 24, mime, 100, taken, None))
            db.execute('INSERT INTO files VALUES (?,?,?,?,?,?,?)', (path, path.rpartition('/')[0], image_id, 100, 0, modified, None))
        return image_id

    def ids(self, params):
        return [row['id'] for row in self.library.pictures(params)['items']]

    def test_folder_filter_includes_subfolders_but_not_similar_names(self):
        trip = self.image(1, 'Trips/Japan/a.jpg')
        top = self.image(2, 'Trips/b.jpg')
        self.image(3, 'Trips 2/c.jpg')
        self.image(4, 'd.jpg')
        self.assertEqual(set(self.ids({'folder': 'Trips'})), {trip, top})
        self.assertEqual(self.ids({'folder': 'Trips/Japan'}), [trip])
        self.assertEqual(len(self.ids({})), 4)

    def test_one_entry_per_image_described_by_its_newest_matching_copy(self):
        shared = self.image(1, 'old/a.jpg', modified='2026-01-01T12:00:00Z')
        self.image(1, 'new/a.jpg', modified='2026-09-01T12:00:00Z')
        row = self.library.pictures({})['items'][0]
        self.assertEqual((row['id'], row['path'], row['copies'], row['dated']), (shared, 'new/a.jpg', 2, 'modified'))
        row = self.library.pictures({'folder': 'old'})['items'][0]
        self.assertEqual((row['path'], row['copies']), ('old/a.jpg', 1))

    def test_capture_date_wins_over_modification_date(self):
        photo = self.image(1, modified='2026-09-01T12:00:00Z', taken='2020-06-01T12:00:00Z')
        self.image(2, modified='2026-08-01T12:00:00Z')
        items = self.library.pictures({})['items']
        self.assertEqual([row['id'] for row in items][-1], photo)
        self.assertEqual((items[-1]['date'], items[-1]['dated']), ('2020-06-01T12:00:00Z', 'taken'))
        self.assertEqual(self.ids({'to': '2020-12-31'}), [photo])

    def test_type_filter(self):
        png = self.image(1, mime='image/png')
        self.image(2)
        self.assertEqual(self.ids({'type': 'image/png'}), [png])

    def test_name_search_treats_wildcards_as_literal_characters(self):
        literal = self.image(1, r'Export at 100%/photo_final C:\images.jpg')
        self.image(2, 'Export at 1000/photoXfinal C:images.jpg')
        for query in ('100%', 'photo_final', r'C:\images', '100% photo_final'):
            with self.subTest(query=query):
                self.assertEqual(self.ids({'q': query, 'mode': 'name'}), [literal])

    def test_pagination_has_stable_order_for_equal_dates(self):
        expected = [self.image(number) for number in (3, 1, 2)]
        first = self.library.pictures({'limit': '2'})
        second = self.library.pictures({'limit': '2', 'offset': '2'})
        self.assertEqual([row['id'] for row in first['items'] + second['items']], sorted(expected))
        self.assertEqual((first['total'], first['hasMore'], second['offset'], second['hasMore']), (3, True, 2, False))
        self.assertEqual(self.library.pictures({'offset': '3'})['items'], [])
        self.assertEqual(first, self.library.pictures({'limit': '2'}))

    def test_dates_follow_the_viewers_timezone(self):
        self.image(1, modified='2026-09-20T23:30:00Z')
        self.assertEqual(self.library.pictures({'from': '2026-09-21', 'to': '2026-09-21'})['total'], 0)
        self.assertEqual(self.library.pictures({'from': '2026-09-21', 'to': '2026-09-21', 'tz': '120'})['total'], 1)
        self.assertEqual(self.library.pictures({'from': '2026-09-20', 'to': '2026-09-20', 'tz': '-600'})['total'], 1)

    def test_invalid_filters_are_rejected(self):
        for params in ({'from': '2026-02-30'}, {'to': 'yesterday'}, {'tz': 'later'},
                       {'from': '2026-09-21', 'to': '2026-09-20'}, {'offset': 'bad'}, {'similar': '../private'}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.library.pictures(params)

    def test_visual_ranking_retains_filters_and_excludes_reference(self):
        reference = self.image(1, 'a/ref.jpg')
        match = self.image(2, 'a/match.jpg')
        elsewhere = self.image(3, 'b/other.jpg')
        self.library.semantic = SimpleNamespace(status=lambda: {'indexed': 3},
                                                search=lambda **kwargs: [(reference, 1), (elsewhere, .9), (match, .8)])
        self.assertEqual(self.ids({'similar': reference, 'folder': 'a'}), [match])
        self.assertEqual(self.ids({'similar': reference}), [elsewhere, match])

    def test_image_similarity_returns_only_the_closest_hundred_but_text_is_not_capped(self):
        ids = [self.image(number) for number in range(1, 106)]
        ranking = [(image_id, 1 - index / 200) for index, image_id in enumerate(ids)]
        self.library.semantic = SimpleNamespace(status=lambda: {'indexed': 105}, search=lambda **kwargs: ranking)
        result = self.library.pictures({'similar': ids[0], 'limit': '200'})
        self.assertEqual((result['total'], result['hasMore']), (100, False))
        self.assertEqual([row['id'] for row in result['items']][:2], ids[1:3])
        self.assertEqual(self.library.pictures({'q': 'x', 'mode': 'visual', 'limit': '200'})['total'], 105)

    def test_visual_search_before_preparation_explains_itself(self):
        self.image(1)
        with self.assertRaisesRegex(ValueError, 'not ready'):
            self.library.pictures({'q': 'sunset', 'mode': 'visual'})
        self.assertEqual(self.library.pictures({'q': 'photo', 'mode': 'name'})['total'], 1)

    def test_facets_count_distinct_images_beneath_each_folder(self):
        self.image(1, 'a/b/one.jpg')
        self.image(1, 'a/copy.jpg')
        self.image(2, 'a/b/c/two.jpg', mime='image/png')
        self.image(3, 'top.jpg')
        facets = self.library.facets()
        self.assertEqual(facets['folders'], [{'path': 'a', 'count': 2}, {'path': 'a/b', 'count': 2}, {'path': 'a/b/c', 'count': 1}])
        self.assertEqual(facets['types'], [{'mime': 'image/jpeg', 'count': 2}, {'mime': 'image/png', 'count': 1}])

    def test_originals_resolve_only_to_copies_of_that_image(self):
        image = self.image(1, 'a/one.jpg')
        self.image(2, 'b/two.jpg')
        self.assertEqual(self.library.original(image), self.folder / 'a/one.jpg')
        self.assertEqual(self.library.original(image, 'a/one.jpg'), self.folder / 'a/one.jpg')
        self.assertIsNone(self.library.original(image, 'b/two.jpg'))
        self.assertIsNone(self.library.original(image, '../../etc/passwd'))

    def test_formats_browsers_cannot_show_get_a_cached_preview(self):
        Image.new('RGB', (40, 30), 'blue').save(self.folder / 'scan.tif')
        tiff = self.image(1, 'scan.tif', mime='image/tiff')
        Image.new('RGB', (40, 30), 'red').save(self.folder / 'web.png')
        png = self.image(2, 'web.png', mime='image/png')
        self.assertEqual(self.library.display(png), self.folder / 'web.png')
        self.assertEqual(self.library.display(tiff), preview_path(self.library.directory, tiff))
        with Image.open(self.library.display(tiff)) as preview:
            self.assertEqual((preview.format, preview.size), ('JPEG', (40, 30)))
        self.assertTrue(self.library.details(tiff)['preview'])

    def test_map_follows_filters_and_omits_images_not_yet_indexed(self):
        first = self.image(1, 'a/one.jpg')
        other = self.image(2, 'b/two.jpg')
        waiting = self.image(3, 'a/three.jpg')
        self.library.semantic = SimpleNamespace(status=lambda: {'indexed': 2})
        self.library.layout = SimpleNamespace(positions=lambda: {first: (0.1234567, -0.5), other: (1.0, 0.25)})
        self.library.atlas = SimpleNamespace(ensure=lambda: {first: 0, other: 1, waiting: 2}, versions=lambda: ['v1'])
        result = self.library.map({'folder': 'a'})
        self.assertEqual([point['id'] for point in result['points']], [first])
        self.assertEqual((result['points'][0]['x'], result['points'][0]['y'], result['points'][0]['slot']), (0.1235, -0.5, 0))
        self.assertEqual((result['pending'], result['sheets']), (1, ['v1']))
        self.assertEqual({point['id'] for point in self.library.map({})['points']}, {first, other})

    def test_map_waits_for_its_first_fit_then_serves_positions(self):
        first = self.image(1)
        self.library.semantic = SimpleNamespace(status=lambda: {'indexed': 1})
        self.library.atlas = SimpleNamespace(ensure=lambda: {first: 0}, versions=lambda: ['v1'])
        positions = [None, {first: (0.5, -0.5)}]
        self.library.layout = Mock(positions=lambda: positions.pop(0), status=lambda: {'state': 'computing', 'stage': 'Laying out the map'})
        waiting = self.library.map({})
        self.assertEqual((waiting['points'], waiting['layout']['state']), ([], 'computing'))
        self.library.layout.start.assert_called_once()
        ready = self.library.map({})
        self.assertEqual((ready['points'][0]['x'], ready['layout']), (0.5, {'state': 'ready'}))

    def test_map_requires_prepared_visual_search(self):
        self.image(1)
        self.library.semantic = SimpleNamespace(status=lambda: {'indexed': 0})
        with self.assertRaisesRegex(ValueError, 'not ready'):
            self.library.map({})

    def test_scan_counts_revisions_and_reports_a_missing_folder(self):
        Image.new('RGB', (8, 8)).save(self.folder / 'one.png')
        self.library.scan()
        self.assertGreater(self.library.revision, 0)
        self.assertEqual(self.library.status()['counts']['images'], 1)
        (self.folder / 'one.png').unlink()
        self.folder.rmdir()
        self.library.scan()
        self.assertEqual(self.library.scan_state['state'], 'error')
        self.assertIn('not available', self.library.scan_state['error'])
        self.assertEqual(self.library.status()['counts']['images'], 1)

    def test_a_closed_library_stops_scanning(self):
        for number in range(3):
            Image.new('RGB', (8, 8), (number, 0, 0)).save(self.folder / f'{number}.png')
        self.library.close()
        self.library.scan()
        self.assertEqual((self.library.scan_state['state'], self.library.status()['counts']['images']), ('ready', 0))


if __name__ == '__main__':
    unittest.main()
