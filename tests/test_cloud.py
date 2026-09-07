import json
import gc
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import cloud_build
import server


class CloudExportTests(unittest.TestCase):
    def test_cadence_boundary_and_failed_attempt_are_persisted(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server, 'DB_PATH', Path(directory) / 'test.db'):
            server.init_db()
            self.assertTrue(cloud_build.is_due('github', 3))
            with patch.object(server, 'sync_github_trending', side_effect=RuntimeError('unavailable')) as fetch:
                self.assertFalse(cloud_build.attempt('github', fetch))
                self.assertFalse(cloud_build.attempt('github', fetch))
                self.assertEqual(fetch.call_count, 1)
            with server.connect() as conn:
                row = conn.execute("SELECT * FROM sync_state WHERE resource='cloud:github'").fetchone()
            conn.close()
            self.assertEqual(row['last_status'], 'error')
            started = datetime.fromisoformat(row['last_synced_at'].replace('Z', '+00:00'))
            self.assertFalse(cloud_build.is_due('github', 3, started + timedelta(hours=3, seconds=-1)))
            self.assertTrue(cloud_build.is_due('github', 3, started + timedelta(hours=3)))
            gc.collect()

    def test_producthunt_can_refresh_only_today(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server, 'DB_PATH', Path(directory) / 'test.db'):
            server.init_db()
            with patch.object(server, 'fetch_producthunt_range', return_value=([], 'start', 'end')) as fetch:
                server.sync_producthunt(('today',))
                fetch.assert_called_once_with('today')

    def test_export_has_all_views_and_never_accesses_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(server, 'DB_PATH', root / 'test.db'), \
                 patch.object(cloud_build, 'OUTPUT', root / 'site'), \
                 patch.object(server.urllib.request, 'urlopen', side_effect=AssertionError('network forbidden')), \
                 patch.object(server, 'NETWORK_ENABLED', False):
                server.init_db()
                cloud_build.export()
                data = json.loads((root / 'site/data/site.json').read_text(encoding='utf-8'))
                self.assertEqual(len([k for k in data if k.startswith('launches:')]), 18)
                self.assertEqual(len([k for k in data if k.startswith('xrank:')]), 10)
                self.assertEqual(len([k for k in data if k.startswith('hn:')]), 40)
                self.assertTrue(data['meta']['cloud'])
                html = (root / 'site/index.html').read_text(encoding='utf-8')
                self.assertIn('href="#/content"', html)
                self.assertIn('./cloud-api.js', html)
                for asset in ('app.js', 'cloud-api.js', 'styles.css'):
                    digest = cloud_build.hashlib.sha256((root / 'site' / asset).read_bytes()).hexdigest()[:12]
                    self.assertIn(f'./{asset}?v={digest}', html)
                self.assertFalse(list((root / 'site').rglob('*.db')))
                js = (root / 'site/app.js').read_text(encoding='utf-8')
                self.assertNotIn('location.pathname', js)
                self.assertNotIn('location.search', js)
                self.assertIn("|| '/content'", js)
                self.assertIn('当前暂无达到榜单门槛的热点事件', js)
                self.assertIn('去看内容', js)
                self.assertNotIn('selection-summary', js)


if __name__ == '__main__':
    unittest.main()
