"""Offline data evidence regressions; synthetic fixtures only, no service imports."""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]
SANDBOX = ROOT / 'docs/repair10/R09-sandbox'
SANDBOX.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / 'workbench'))
import dashboard_native_week as native
import inquiry_calendar as inquiry


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def prepare_function():
    tree = ast.parse((ROOT / 'workbench/weekly_update.py').read_text('utf-8-sig'))
    tree.body = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'prepare_dashboard']
    ns = dict(Path=Path, shutil=shutil, json=json, SyncError=ValueError,
              catalog=types.SimpleNamespace(atomic_json=put))
    exec(compile(tree, 'weekly_update.py', 'exec'), ns)
    return ns['prepare_dashboard']


class DataEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=SANDBOX)
        self.root = Path(self.tmp.name)
        self.period = {'start': '2026-10-12', 'end': '2026-10-18'}
        self.binding = dict(self.period, statDate='2026-10-17', source='platform-date-picker',
                            confirmed=True, evidence='SYNTHETIC ONLY')

    def tearDown(self):
        self.tmp.cleanup()

    def dashboard(self, bindings=None, store='123'):
        source = self.root / 'source'
        put(source / 'engine/workspace/stores.json', {'active': 'fixture', 'stores': {'fixture': {'store_id': store}}})
        if bindings is not None:
            put(source / 'engine/workspace/raw/platform_native_week_windows.json', {'windows': bindings})
        put(source / 'engine/workspace/raw/private.json', {'never': 'copy'})
        put(source / 'settings.json', {})
        (source / 'engine/pipeline').mkdir(parents=True)
        for name in ('make_dashboard.py', 'setup_env.py'):
            (source / name).write_text('# fixture', encoding='utf-8')
        return {'dashboard': source, 'expected_id': '123', 'label': 'fixture'}

    def prepared(self, cfg, **kwargs):
        destination = self.root / 'isolated'
        prepare_function()(destination, cfg, **kwargs)
        return destination / 'engine/workspace'

    def test_legacy_source_binding_survives_without_claiming_store_evidence(self):
        cfg = self.dashboard([self.binding])
        ws = self.prepared(cfg)
        self.assertEqual(native.confirmation(ws, **self.period), self.binding)
        proof = native.read(ws / 'raw/platform_native_week_windows.json')
        self.assertEqual(proof['provenance']['storeBinding'], 'source_config_only')
        self.assertEqual(proof['provenance']['sourceSha256'], hashlib.sha256(
            (cfg['dashboard'] / 'engine/workspace/raw/platform_native_week_windows.json').read_bytes()).hexdigest())
        self.assertFalse((ws / 'raw/private.json').exists())

    def test_store_mismatch_cannot_be_relabelled(self):
        cfg = self.dashboard([self.binding], store='999')
        with self.assertRaises(ValueError):
            self.prepared(cfg)

    def test_binding_store_mismatch_rejected(self):
        cfg = self.dashboard([dict(self.binding, store='999')])
        with self.assertRaises(ValueError):
            self.prepared(cfg)

    def test_requested_windows_allowlist_and_mock_native_week_only(self):
        prior = dict(self.binding, start='2026-10-05', end='2026-10-11', statDate='2026-10-10')
        cfg = self.dashboard([dict(self.binding, store_id='123'), prior])
        ws = self.prepared(cfg, windows=[self.period])
        self.assertEqual(len(native.read(ws / 'raw/platform_native_week_windows.json')['windows']), 1)
        put(ws / 'raw/_window.json', {'as_of': '2026-10-21', 'weeks': [
            {'week_start': self.period['start'], 'week_end': self.period['end']}]})
        calls = []
        def call(tool, payload):
            calls.append(payload['shopProductQueryParam'])
            return {'success': True, 'data': {'recordCount': 0, 'data': [], 'downloadUrl':
                    'https://example.invalid/?statisticsType=week&statDate=2026-10-17'}}
        self.assertEqual(len(native.collect_all(ws, '123', call)), 1)
        self.assertEqual([c['statisticsType'] for c in calls], ['week'])

    def test_missing_or_wrong_window_stops_before_platform_call(self):
        cfg = self.dashboard([dict(self.binding, start='2026-10-05', end='2026-10-11')])
        with self.assertRaises(ValueError):
            self.prepared(cfg, windows=[self.period])

    def test_all_requested_proofs_are_required_before_any_collection(self):
        cfg = self.dashboard([self.binding])
        prior = {'start': '2026-10-05', 'end': '2026-10-11'}
        with self.assertRaises(ValueError):
            self.prepared(cfg, windows=[self.period, prior])
        self.assertFalse((self.root / 'isolated').exists())

    def test_conflicting_proofs_and_unconfirmed_proof_rejected(self):
        cfg = self.dashboard([self.binding, dict(self.binding, statDate='2026-10-16')])
        with self.assertRaises(ValueError):
            self.prepared(cfg, windows=[self.period])
        put(cfg['dashboard'] / 'engine/workspace/raw/platform_native_week_windows.json',
            {'windows': [dict(self.binding, confirmed=False)]})
        with self.assertRaises(ValueError):
            self.prepared(cfg, windows=[self.period])

    def test_missing_file_remains_fail_closed(self):
        ws = self.prepared(self.dashboard())
        put(ws / 'raw/_window.json', {'as_of': '2026-10-21', 'weeks': [
            {'week_start': self.period['start'], 'week_end': self.period['end']}]})
        calls = []
        with self.assertRaises(ValueError):
            native.collect_all(ws, '123', lambda *a: calls.append(a))
        self.assertEqual(calls, [])

    def segment(self, raw_messages, normalized=None, period=None, name='part'):
        period = period or self.period
        folder = self.root / name
        raw_path = (folder / '.work/conversations_all.json').resolve()
        meta = dict(startDate=period['start'], endDate=period['end'], failureRatio=0)
        put(raw_path, {'meta': dict(meta, totalAccounts=1, totalFailedAccounts=0, totalConversations=1),
                       'conversations': [{'conversationId': 'c1', 'sellerAliId': 'fixture-seller'}]})
        raw_rows = [{'conversationId': 'c1', 'messages': raw_messages}] if raw_messages else []
        put(folder / '.work/messages_all.json', {'meta': dict(meta, sourceConversationFile=str(raw_path),
            sourceTotalConversations=1, totalInputConversations=1, totalMessages=len(raw_messages),
            totalConversationsWithMessages=len(raw_rows)), 'conversations': raw_rows})
        if normalized is None:
            normalized = [{'sendTime': m['time'], 'senderRole': 'buyer' if m['from'] == 'buyer' else 'seller',
                           'content': m.get('text') or ''} for m in raw_messages]
        put(folder / 'conversations.json', {'window': {'since': period['start']+'T00:00:00',
            'until': period['end']+'T23:59:59'}, 'store': {'aliId': '123', 'accountCount': 1},
            'conversations': [{'conversationId': 'c1', 'sellerAliId': 'fixture-seller', 'messages': normalized}]})
        put(folder / 'buyers.json', [])
        return folder

    def merge(self, folder):
        return inquiry.merge_parts([(folder, self.period)], self.root / 'out', '123', **self.period)

    def test_omitted_raw_message_rejected_before_verified_output(self):
        folder = self.segment([{'time': '2026-10-13 10:00:00', 'from': 'buyer', 'text': 'question'}], [])
        with self.assertRaises(ValueError):
            self.merge(folder)
        self.assertFalse((self.root / 'out/calendar-collection.json').exists())

    def test_duplicate_occurrence_cannot_disappear(self):
        m = {'time': '2026-10-13 10:00:00', 'from': 'buyer', 'text': 'same'}
        folder = self.segment([m, m])
        p = folder / 'conversations.json';data = native.read(p)
        data['conversations'][0]['messages'].pop();put(p, data)
        with self.assertRaises(ValueError):
            self.merge(folder)

    def test_true_empty_and_only_outside_messages_are_valid(self):
        for index, messages in enumerate(([], [{'time': '2026-10-01', 'from': 'buyer', 'text': 'outside'}])):
            folder = self.segment(messages, [], name='part'+str(index))
            self.assertEqual(self.merge(folder)['messages'], 0)

    def test_timezone_role_and_same_segment_duplicates_reconcile(self):
        m = {'time': '2026-10-12T16:00:00Z', 'from': 'operator', 'text': 'answer'}
        normalized = [{'sendTime': '2026-10-13 00:00:00', 'senderRole': 'seller', 'content': 'answer'}] * 2
        folder = self.segment([m, m], normalized)
        self.assertEqual(self.merge(folder)['messages'], 2)
        receipt = native.read(self.root / 'out/calendar-collection.json')
        self.assertEqual(receipt['sources'][0]['rawTotalMessages'], 2)
        self.assertEqual(receipt['sources'][0]['sha256']['messages_all.json'], hashlib.sha256(
            (folder / '.work/messages_all.json').read_bytes()).hexdigest())

    def test_tampered_content_role_time_and_extra_message_rejected(self):
        m = {'time': '2026-10-13 10:00:00', 'from': 'buyer', 'text': 'question'}
        for index, change in enumerate(({'content': 'different'}, {'senderRole': 'seller'},
                                         {'sendTime': '2026-10-13 11:00:00'})):
            norm = dict(sendTime=m['time'], senderRole='buyer', content=m['text'], **{})
            norm.update(change)
            folder = self.segment([m], [norm], name='bad'+str(index))
            with self.assertRaises(ValueError):
                self.merge(folder)
        folder = self.segment([m], name='extra')
        p = folder / 'conversations.json'; data = native.read(p)
        data['conversations'][0]['messages'] *= 2; put(p, data)
        with self.assertRaises(ValueError):
            self.merge(folder)

    def test_overlapping_fetched_histories_filter_per_segment_and_keep_occurrences(self):
        periods = inquiry.chunks('2026-10-01', '2026-10-31')
        messages = [{'time': p['start']+' 12:00:00', 'from': 'buyer', 'text': 'same'}
                    for p in periods for _ in range(2)]
        parts = [(self.segment(messages, period=p, name=p['start']), p) for p in periods]
        stats = inquiry.merge_parts(parts, self.root / 'month', '123', '2026-10-01', '2026-10-31')
        self.assertEqual(stats['messages'], 10)
        receipt = native.read(self.root / 'month/calendar-collection.json')
        self.assertEqual([s['rawTotalMessages'] for s in receipt['sources']], [10]*5)
        self.assertEqual([s['windowMessages'] for s in receipt['sources']], [2]*5)

    def test_missing_raw_role_matches_upstream_seller_default(self):
        folder = self.segment([{'time': '2026-10-13 10:00:00'}],
                              [{'sendTime': '2026-10-13 10:00:00', 'senderRole': 'seller', 'content': ''}])
        self.assertEqual(self.merge(folder)['messages'], 1)

    def test_cross_store_segment_rejected(self):
        folder = self.segment([])
        with self.assertRaises(ValueError):
            inquiry.verified_part(folder, '999', self.period)


if __name__ == '__main__':
    unittest.main()
