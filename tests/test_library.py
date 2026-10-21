import errno
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from server.cache import connect, preview_path
from server.library import Library
from server.semantic import MODEL, Encoder


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
        with connect(self.library.directory, rows=True) as db:
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

    def group(self, *members):
        """Store near-duplicates as the grouping would, best first."""
        with connect(self.library.directory, rows=True) as db:
            db.executemany('INSERT INTO image_groups VALUES (?,?,?)',
                           [(image_id, members[0], len(members) - place) for place, image_id in enumerate(members)])

    def test_near_duplicates_share_one_tile_fronted_by_the_best_match(self):
        best = self.image(1, 'a/best.jpg', modified='2026-09-01T12:00:00Z')
        blurry = self.image(2, 'b/blurry.jpg', modified='2026-09-02T12:00:00Z')
        alone = self.image(3, 'b/alone.jpg')
        self.group(best, blurry)
        items = self.library.pictures({})['items']
        self.assertEqual([(row['id'], row['members']) for row in items], [(alone, 1), (best, 2)])
        self.assertEqual(self.library.status()['counts']['nearDuplicates'], 1)
        # When the best is filtered out, the next one fronts what is left of the group.
        self.assertEqual([(row['id'], row['members']) for row in self.library.pictures({'folder': 'b'})['items']], [(alone, 1), (blurry, 1)])

    def test_a_group_lists_its_matching_members_best_first(self):
        members = [self.image(number, f'{folder}/{number}.jpg') for number, folder in ((1, 'a'), (2, 'b'), (3, 'a'))]
        self.group(*members)
        self.assertEqual(self.ids({'group': members[0]}), members)
        self.assertEqual(self.ids({'group': members[0], 'folder': 'a'}), [members[0], members[2]])
        self.assertEqual(self.ids({'group': self.image(4)}), [f'{4:064x}'])
        with self.assertRaises(ValueError):
            self.library.pictures({'group': '../x'})

    def test_finding_similar_starts_with_the_references_own_stack(self):
        reference, twin, other = (self.image(number) for number in (1, 2, 3))
        self.group(twin, reference)
        # The stack's cover scores below another image, yet still leads.
        self.library.semantic = SimpleNamespace(status=lambda: {'indexed': 3},
                                                search=lambda **kwargs: [(reference, 1), (other, .97), (twin, .96)])
        self.assertEqual(self.ids({'similar': reference}), [twin, other])
        # A text search has no reference, so the stack ranks by its cover's score.
        self.assertEqual(self.ids({'q': 'x', 'mode': 'visual'}), [other, twin])

    def test_dates_follow_the_viewers_timezone(self):
        self.image(1, modified='2026-09-20T23:30:00Z')
        self.assertEqual(self.library.pictures({'from': '2026-09-21', 'to': '2026-09-21'})['total'], 0)
        self.assertEqual(self.library.pictures({'from': '2026-09-21', 'to': '2026-09-21', 'tz': '120'})['total'], 1)
        self.assertEqual(self.library.pictures({'from': '2026-09-20', 'to': '2026-09-20', 'tz': '-600'})['total'], 1)

    def test_timeline_counts_tiles_per_month_in_grid_order(self):
        self.image(1, modified='2026-09-20T12:00:00Z')
        self.image(2, modified='2026-09-02T12:00:00Z')
        self.image(3, modified='2026-07-14T12:00:00Z')
        self.image(4, modified='2025-12-31T23:30:00Z')
        timeline = self.library.timeline({})
        self.assertEqual(timeline, {'months': [{'month': '2026-09', 'count': 2}, {'month': '2026-07', 'count': 1}, {'month': '2025-12', 'count': 1}], 'total': 4})
        self.assertEqual(timeline['total'], self.library.pictures({})['total'])
        # Half an hour before New Year in UTC is already January in Berlin, and stays December in New York.
        self.assertEqual(self.library.timeline({'zone': 'Europe/Berlin'})['months'][-1], {'month': '2026-01', 'count': 1})
        self.assertEqual(self.library.timeline({'zone': 'America/New_York'})['months'][-1], {'month': '2025-12', 'count': 1})
        self.assertEqual(self.library.timeline({'zone': 'Nowhere/Invalid', 'tz': '60'})['months'][-1], {'month': '2026-01', 'count': 1})
        self.assertEqual(self.library.timeline({'type': 'image/png'}), {'months': [], 'total': 0})

    def test_invalid_filters_are_rejected(self):
        for params in ({'from': '2026-02-30'}, {'to': 'yesterday'}, {'tz': 'later'},
                       {'from': '2026-09-21', 'to': '2026-09-20'}, {'offset': 'bad'}, {'similar': '../private'}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.library.pictures(params)

    def test_visual_ranking_retains_filters_and_leads_with_the_reference(self):
        reference = self.image(1, 'a/ref.jpg')
        match = self.image(2, 'a/match.jpg')
        elsewhere = self.image(3, 'b/other.jpg')
        self.library.semantic = SimpleNamespace(status=lambda: {'indexed': 3},
                                                search=lambda **kwargs: [(reference, 1), (elsewhere, .9), (match, .8)])
        self.assertEqual(self.ids({'similar': reference, 'folder': 'a'}), [reference, match])
        self.assertEqual(self.ids({'similar': reference}), [reference, elsewhere, match])

    def test_every_visual_match_is_returned(self):
        ids = [self.image(number) for number in range(1, 106)]
        ranking = [(image_id, 1 - index / 200) for index, image_id in enumerate(ids)]
        self.library.semantic = SimpleNamespace(status=lambda: {'indexed': 105}, search=lambda **kwargs: ranking[:-5])
        for params in ({'similar': ids[0]}, {'q': 'x', 'mode': 'visual'}):
            result = self.library.pictures({**params, 'limit': '200'})
            self.assertEqual((result['total'], result['hasMore']), (100, False))
            self.assertEqual([row['id'] for row in result['items']][:2], ids[:2])

    def test_visual_search_before_preparation_explains_itself(self):
        self.image(1)
        with self.assertRaisesRegex(ValueError, 'not set up'):
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

    def test_map_shows_only_the_newest_images_beyond_its_limit(self):
        ids = [self.image(number, modified=f'2026-09-{number:02d}T12:00:00Z') for number in range(1, 4)]
        self.library.semantic = SimpleNamespace(status=lambda: {'indexed': 3})
        self.library.layout = SimpleNamespace(positions=lambda: {image_id: (0.0, 0.0) for image_id in ids})
        self.library.atlas = SimpleNamespace(ensure=lambda: {image_id: n for n, image_id in enumerate(ids)}, versions=lambda: ['v1'])
        with patch('server.library.MAP_LIMIT', 2):
            result = self.library.map({})
        self.assertEqual(([point['id'] for point in result['points']], result['omitted']), ([ids[2], ids[1]], 1))

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
        self.library.semantic = SimpleNamespace(status=lambda: {'indexed': 0, 'state': 'idle'})
        with self.assertRaisesRegex(ValueError, 'not set up'):
            self.library.map({})

    def test_reopening_after_a_model_change_drops_the_old_vectors_and_map(self):
        old, kept = self.image(1), self.image(2)
        with connect(self.library.directory, rows=True) as db:
            db.executemany('INSERT INTO semantic_embeddings VALUES (?,?,?)', [(old, 'another/model', b'old'), (kept, MODEL, b'new')])
            db.executemany('INSERT INTO umap_positions VALUES (?,?,?,1)', [(old, 0.1, 0.2), (kept, 0.3, 0.4)])
            db.execute('INSERT INTO image_groups VALUES (?,?,1)', (old, kept))
        reopened = Library(self.folder, self.library.directory, self.library.semantic.encoder)
        with connect(reopened.directory, rows=True) as db:
            self.assertEqual([tuple(row) for row in db.execute('SELECT image_id, model FROM semantic_embeddings')], [(kept, MODEL)])
            self.assertEqual(db.execute('SELECT count(*) FROM umap_positions').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM image_groups').fetchone()[0], 0)
        # Without the model on disk, a scan doesn't start preparing: setting up is the user's choice.
        with patch('server.library.threading.Thread') as thread:
            reopened.scan()
        thread.assert_not_called()
        # Reopening once the vectors all match keeps the map.
        with connect(reopened.directory, rows=True) as db:
            db.execute('INSERT INTO umap_positions VALUES (?,?,?,1)', (kept, 0.3, 0.4))
        Library(self.folder, self.library.directory, self.library.semantic.encoder)
        with connect(reopened.directory, rows=True) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM umap_positions').fetchone()[0], 1)

    def test_preparing_asked_for_midway_runs_again_afterwards(self):
        runs = []
        # A scan finishing during the first run asks again; that request is folded into a second round.
        self.library.semantic = SimpleNamespace(index=lambda cancelled: (runs.append(1), len(runs) == 1 and self.library.index()))
        self.library.groups = SimpleNamespace(update=lambda: False)
        self.library.index()
        self.assertEqual(len(runs), 2)

    def test_visual_search_is_not_ready_while_the_scan_has_files_to_read(self):
        image = self.image(1)
        with connect(self.library.directory, rows=True) as db:
            db.execute('INSERT INTO semantic_embeddings VALUES (?,?,?)', (image, MODEL, b'vector'))
        self.assertEqual(self.library.status()['search']['state'], 'ready')
        self.library.scan_state = {'state': 'scanning', 'found': 1000, 'done': 144, 'changed': 1000}
        self.assertEqual(self.library.status()['search']['state'], 'idle')
        # A rescan that finds nothing new leaves it ready.
        self.library.scan_state = {'state': 'scanning', 'found': 1000, 'done': 0, 'changed': 0}
        self.assertEqual(self.library.status()['search']['state'], 'ready')

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

    def test_only_a_retry_reads_again_the_files_that_could_not_be_read(self):
        Image.new('RGB', (8, 8)).save(self.folder / 'one.png')
        with patch('pathlib.Path.open', side_effect=PermissionError(errno.EACCES, 'Permission denied')):
            self.library.scan()
        self.library.scan()
        self.assertEqual(self.library.status()['counts']['unreadable'], 1)
        self.library.scan(retry=True)
        self.assertEqual((self.library.status()['counts']['images'], self.library.status()['counts']['unreadable']), (1, 0))

    def test_pages_follow_the_revision_a_scan_commits(self):
        Image.new('RGB', (8, 8), 'red').save(self.folder / 'one.png')
        self.library.scan()
        self.assertEqual(self.library.pictures({})['total'], 1)
        Image.new('RGB', (8, 8), 'blue').save(self.folder / 'two.png')
        self.library.scan()
        self.assertEqual(self.library.pictures({'offset': '1'})['total'], 2)

    def test_a_closed_library_stops_scanning(self):
        for number in range(3):
            Image.new('RGB', (8, 8), (number, 0, 0)).save(self.folder / f'{number}.png')
        self.library.close()
        self.library.scan()
        self.assertEqual((self.library.scan_state['state'], self.library.status()['counts']['images']), ('ready', 0))


if __name__ == '__main__':
    unittest.main()
