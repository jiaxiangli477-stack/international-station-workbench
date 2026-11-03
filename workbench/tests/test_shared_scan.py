import json
from pathlib import Path
import tempfile
import unittest
import shared_scan as scan


class SharedScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old = (scan.SHARE, scan.STATE, scan.CACHE, scan.INDEX)
        scan.SHARE = self.root / 'share'; scan.SHARE.mkdir()
        scan.STATE = self.root / 'state'; scan.CACHE = scan.STATE / 'cache'; scan.INDEX = scan.STATE / 'index.json'
        for name in ('1901', '1903', 'Lifeworth', 'Lifeworthcn', 'Youhealth'):
            (scan.SHARE / name).mkdir()

    def tearDown(self):
        scan.SHARE, scan.STATE, scan.CACHE, scan.INDEX = self.old
        self.tmp.cleanup()

    def dataset(self, folder, value=10, generated='2026-10-16 09:00:00', name='Lifeworthcn'):
        folder.mkdir(parents=True, exist_ok=True)
        d = {'meta': {'store_name': name, 'week_start': '2026-10-05', 'week_end': '2026-10-11', 'generated_at': generated},
             'weeks': [{'week_start': '2026-10-05', 'week_end': '2026-10-11', 'se_imps': value, 'se_clk': 2}],
             'months': [{'month_start': '2026-09-01', 'month_end': '2026-09-30', 'se_imps': 500}]}
        (folder / 'dashboard_data.js').write_text('window.V4_DATA = ' + json.dumps(d) + ';', encoding='utf-8')
        (folder / 'app.js').write_text('// fixture renderer', encoding='utf-8')
        (folder / 'index.html').write_text('<html><head><script src="dashboard_data.js"></script><script src="app.js"></script></head><body>经营看板</body></html>', encoding='utf-8')

    def test_empty_share_has_five_stores_and_no_fabricated_reports(self):
        self.assertEqual(scan.scan()['status'], 'SUCCESS')
        index = scan.read_index()
        self.assertEqual(len(index['stores']), 5)
        self.assertEqual(index['records'], [])
        self.assertEqual(index['periods'], [])

    def test_duplicates_are_not_counted_twice_and_sources_are_unchanged(self):
        folder = scan.SHARE / 'Lifeworthcn'
        self.dataset(folder / 'a'); self.dataset(folder / 'b')
        original = (folder / 'a' / 'index.html').read_bytes()
        scan.scan(); index = scan.read_index()
        self.assertEqual(len(index['records']), 1)
        self.assertEqual(index['duplicateCount'], 1)
        self.assertEqual(len(index['periods']), 2)
        self.assertEqual((folder / 'a' / 'index.html').read_bytes(), original)

    def test_same_period_revision_uses_newer_version_without_summing(self):
        folder = scan.SHARE / 'Lifeworthcn'
        self.dataset(folder / 'a', 10, '2026-10-15 09:00:00')
        self.dataset(folder / 'b', 20, '2026-10-16 09:00:00')
        scan.scan(); rows = scan.read_index()['periods']
        weekly = next(r for r in rows if r['kind'] == 'week')
        self.assertEqual(weekly['values']['se_imps'], 20)
        self.assertEqual(weekly['versions'], 2)
        self.assertTrue(weekly['conflict'])
        self.assertEqual(len([r for r in rows if r['kind'] == 'month']), 1)

    def test_known_cross_store_mismatch_is_quarantined(self):
        self.dataset(scan.SHARE / 'Youhealth' / 'wrong')
        scan.scan(); index = scan.read_index()
        self.assertEqual(index['records'], [])
        self.assertTrue(any('店名' in i['reason'] for i in index['issues']))

    def test_missing_dependencies_are_not_selected_as_complete(self):
        folder = scan.SHARE / 'Lifeworthcn'
        (folder / '报告_2026-10-01_2026-10-07.html').write_text('<html><head><script src="missing.js"></script></head><body>经营看板</body></html>', encoding='utf-8')
        scan.scan(); record = scan.read_index()['records'][0]
        self.assertFalse(record['complete'])
        self.assertEqual(record['start'], '2026-10-01')

    def test_network_failure_keeps_last_successful_cache(self):
        self.dataset(scan.SHARE / 'Lifeworthcn' / 'a')
        scan.scan(); previous = scan.read_index()
        scan.SHARE = self.root / 'unavailable'
        self.assertEqual(scan.scan()['status'], 'FAILED')
        retained = scan.read_index()
        self.assertEqual(retained['lastSuccess'], previous['lastSuccess'])
        self.assertEqual(retained['records'], previous['records'])

    def test_cached_routes_are_allowlisted_and_cannot_traverse(self):
        self.dataset(scan.SHARE / 'Lifeworthcn' / 'a'); scan.scan()
        record = scan.read_index()['records'][0]
        self.assertTrue(scan.resolve_cached(record['id'], 'index.html').is_file())
        self.assertIsNone(scan.resolve_cached(record['id'], '../index.json'))
        self.assertIsNone(scan.resolve_cached(record['id'], 'unlisted.json'))

    def test_unsupported_excel_is_reported_instead_of_claiming_import(self):
        (scan.SHARE / '1901' / '面板.xlsx').write_bytes(b'fixture')
        scan.scan(); index = scan.read_index()
        self.assertEqual(index['records'], [])
        self.assertTrue(any(i['file'] == '面板.xlsx' for i in index['issues']))


if __name__ == '__main__':
    unittest.main()
