import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from contextlib import closing

import server
import fact_archive


class FactHistoryTests(unittest.TestCase):
    def test_event_time_not_collection_time_and_exact_boundaries(self):
        now = '2026-09-13T12:00:00Z'
        stamps = {'recent':'2026-09-13T11:00:00Z', 'edge':'2026-09-06T12:00:00Z',
                  'outside':'2026-09-06T11:59:59.999Z', 'old':'2026-09-01T00:00:00Z',
                  'future':'2026-09-13T12:00:00.001Z', 'unknown':None}
        self.collect(now, items=[{'id':key,'title':key,'latestAt':stamp} for key,stamp in stamps.items()])
        from datetime import datetime
        ms = lambda value: str(round(datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()*1000))
        result = server.query_facts({'view':['events'],'from_ms':[ms(stamps['edge'])], 'to_ms':[ms(now)]})
        self.assertEqual({x['aihot_story_id'] for x in result['items']}, {'recent','edge'})
        self.assertEqual(server.query_fact_events()['count'], 6)
        self.collect('2026-09-14T00:00:00Z', items=[{'id':'recent','title':'新版本','latestAt':'2026-09-14T00:00:00Z'}])
        self.assertEqual(server.query_fact_events()['count'], 6)
        result = server.query_fact_events({'from_ms':[ms(stamps['edge'])], 'to_ms':[ms(now)]})
        self.assertEqual({x['aihot_story_id'] for x in result['items']}, {'edge'})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = patch.object(server, 'DB_PATH', Path(self.temp.name) / 'test.db')
        self.db.start()
        server.init_db()

    def tearDown(self):
        import gc
        gc.collect()
        self.db.stop()
        self.temp.cleanup()

    def collect(self, time, title='版本一', items=None):
        with patch.object(server, 'utc_now', return_value=time):
            server.upsert_facts({'items': items if items is not None else [{'id':'one', 'title':title, 'latestAt':time}]}, Mock())

    def test_daily_versions_empty_list_and_beijing_boundary(self):
        self.collect('2026-09-01T15:00:00Z')
        self.collect('2026-09-01T15:30:00Z', '版本二')
        self.collect('2026-09-01T16:01:00Z', '次日版本')
        self.collect('2026-09-02T01:00:00Z', items=[])
        self.assertEqual(server.query_facts()['count'], 0)
        self.assertEqual(server.query_facts()['dates'], ['2026-09-02','2026-09-01'])
        self.assertEqual(server.query_facts({'date':['2026-09-01']})['items'][0]['title'], '版本二')
        self.assertEqual(server.query_facts({'date':['2026-09-02']})['items'][0]['title'], '次日版本')
        self.assertEqual(server.query_facts({'date':['2026-08-01']})['count'], 0)
        with self.assertRaises(ValueError):
            server.query_facts({'date':['../../secret']})

    def test_durable_restore_without_database_and_public_only(self):
        self.collect('2026-09-01T08:00:00Z')
        directory = Path(self.temp.name) / 'archive'
        fact_archive.save(directory)
        text = (directory / '2026-09-01.json').read_text(encoding='utf-8')
        self.assertNotIn('raw_json', text)
        self.assertNotIn('sync_state', text)
        with patch.object(server, 'DB_PATH', Path(self.temp.name) / 'fresh.db'):
            server.init_db()
            self.assertEqual(fact_archive.restore(directory), 1)
            fact_archive.restore(directory)
            self.assertEqual(server.query_facts()['count'], 0)  # Never revive an old list as current.
            self.assertEqual(server.query_facts({'date':['2026-09-01']})['count'], 1)

    def test_recovery_does_not_invent_days_or_overwrite_observed_version(self):
        self.collect('2026-09-01T08:00:00Z')
        server.recover_fact_history()
        self.assertFalse(server.query_facts({'date':['2026-09-01']})['items'][0]['recovered'])
        with closing(server.connect()) as conn, conn:
            conn.execute('DELETE FROM fact_history')
        server.recover_fact_history()
        self.assertEqual(server.query_facts()['dates'], ['2026-09-01'])
        self.assertTrue(server.query_facts({'date':['2026-09-01']})['items'][0]['recovered'])

    def test_corrupt_archive_fails_before_partial_restore(self):
        directory = Path(self.temp.name) / 'archive'
        self.collect('2026-09-01T08:00:00Z')
        fact_archive.save(directory)
        (directory / '2026-09-02.json').write_text('{broken', encoding='utf-8')
        with patch.object(server, 'DB_PATH', Path(self.temp.name) / 'fresh.db'):
            server.init_db()
            with self.assertRaises(json.JSONDecodeError):
                fact_archive.restore(directory)
            self.assertEqual(server.query_facts()['dates'], [])

    def test_not_modified_confirms_new_day_but_error_does_not(self):
        self.collect('2026-09-01T08:00:00Z')
        with patch.object(server, 'utc_now', return_value='2026-09-02T08:00:00Z'):
            server.AIHotClient._state('hot-topics', None, 'error', 'offline')
            server.archive_unchanged_facts()
            self.assertEqual(server.query_facts()['dates'], ['2026-09-01'])
            server.AIHotClient._state('hot-topics', None, 'not-modified', None)
            server.archive_unchanged_facts()
            self.assertEqual(server.query_facts()['dates'], ['2026-09-02', '2026-09-01'])

    def test_all_history_and_range_deduplicate_after_filtering(self):
        self.collect('2026-09-01T08:00:00Z', '旧版本')
        self.collect('2026-09-02T08:00:00Z', '新版本')
        self.collect('2026-09-03T08:00:00Z', items=[{'id':'two','title':'另一个事件'}])
        all_items = server.query_facts({'view':['history']})['items']
        self.assertEqual(len(all_items), 2)
        self.assertEqual(next(x for x in all_items if x['aihot_story_id']=='one')['title'], '新版本')
        filtered = server.query_facts({'view':['history'], 'from':['2026-09-01'], 'to':['2026-09-01']})
        self.assertEqual(filtered['items'][0]['title'], '旧版本')
        self.assertEqual(server.query_fact_history(deduplicate=False)['count'], 3)
        with self.assertRaises(ValueError):
            server.query_fact_history({'from':['2026-09-03'], 'to':['2026-09-01']})
