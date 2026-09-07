import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cloud_build
import server


class CloudExportTests(unittest.TestCase):
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
                self.assertFalse(list((root / 'site').rglob('*.db')))
                js = (root / 'site/app.js').read_text(encoding='utf-8')
                self.assertNotIn('location.pathname', js)
                self.assertNotIn('location.search', js)


if __name__ == '__main__':
    unittest.main()
