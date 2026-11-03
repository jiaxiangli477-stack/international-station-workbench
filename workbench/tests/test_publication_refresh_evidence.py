"""Offline publication evidence and bounded polling; never calls the platform."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import listing_adapter as adapter
import listing_publication as publication
import task_store as store


class PublicationEvidenceTests(unittest.TestCase):
    product = {'id': 'P-fixture', 'revision': 1, 'facts': {'store': 'fixture'},
               'draft': {'draft_id': '123', 'store': 'fixture'}}

    def payload(self, identity=123):
        return {'success': True, 'data': {'productQueryResult': json.dumps(
            {'productId': identity, 'status': 1, 'auditStatus': 1})}}

    def observation(self, root):
        schema = {'success': True, 'command': 'workctl icbu product query-product-by-id',
                  'params': [{'name': 'productId', 'agent_flag': '--prod-id', 'type': 'integer', 'required': True}]}
        for name, value in [('schema.json', schema), ('query-product.json', self.payload())]:
            (root / name).write_text(json.dumps(value), encoding='utf-8')
        digest = lambda name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        row = publication.parse_product(self.payload(), '123')
        return {'identity': {'verified': True, 'account_id': 'account'},
                'source': {'kind': 'workctl-tool', 'method': 'TOOLS/CALL', 'command': publication.COMMAND,
                           'read_only': True, 'schema_verified': True,
                           'schema_file': str(root / 'schema.json'), 'schema_sha256': digest('schema.json'),
                           'evidence_file': str(root / 'query-product.json'), 'payload_sha256': digest('query-product.json')},
                'observed_at': datetime.now(timezone.utc).isoformat(), 'row': dict(row, draft_id='123')}

    def temporary(self):
        root = Path(__file__).resolve().parents[2] / 'docs/audit-20261029/publication-tests'
        root.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=root)

    def test_real_nested_json_shape_binds_response_id_without_guessing_numeric_status(self):
        row = publication.parse_product(self.payload(), '123')
        self.assertEqual(row['status_values'], {'status': 1, 'auditStatus': 1})
        self.assertEqual(row['item_id'], '123')
        self.assertEqual(row['status'], 'unknown')
        self.assertIs(row['mapping_verified'], False)
        with self.assertRaises(ValueError):
            publication.parse_product(self.payload(124), '123')

    def test_refresh_consumes_verified_workctl_observation_even_when_enum_unknown(self):
        with self.temporary() as directory:
            root = Path(directory); observation = self.observation(root)
            with patch('weekly_update.STORES', {'fixture': {'expected_id': 'account'}}), \
                    patch.object(publication, 'collect', return_value=observation):
                result = adapter.refresh_publication(self.product, root)
            self.assertEqual(result['status'], 'unknown')
            self.assertIsNone(result['published'])
            self.assertEqual(result['authority']['source_kind'], 'workctl-tool')
            self.assertTrue(result['authority']['identity_verified'])
            self.assertEqual(result['evidence']['status_values'], {'status': 1, 'auditStatus': 1})
            self.assertTrue(result['evidence']['sha256'])
            self.assertNotIn('account', json.dumps(result))

    def test_tampered_hash_identity_row_and_stale_observation_remain_unknown(self):
        for failure in ('hash', 'identity', 'row', 'stale'):
            with self.subTest(failure=failure), self.temporary() as directory:
                root = Path(directory); observation = self.observation(root)
                if failure == 'hash': (root / 'query-product.json').write_text('{}', encoding='utf-8')
                if failure == 'identity': observation['identity']['account_id'] = 'other'
                if failure == 'row': observation['row'].update(status='published', mapping_verified=True)
                if failure == 'stale': observation['observed_at'] = (datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat()
                result = adapter.read_publication_status(self.product, lambda _: observation, expected_account='account')
                self.assertEqual(result['status'], 'unknown')
                self.assertIsNone(result['published'])
                self.assertEqual(result['authority'], {})

    def test_poller_skips_absent_invalid_or_unbound_drafts_and_isolates_failures(self):
        products = [self.product, dict(self.product, id='P-second'),
                    dict(self.product, draft=None), dict(self.product, draft={'draft_id': '../bad'}),
                    dict(self.product, facts={'store': 'unbound'})]
        calls = []
        def refresh(payload):
            calls.append(payload)
            if len(calls) == 1: raise ValueError('isolated failure')
        with patch('weekly_update.STORES', {'fixture': {'expected_id': 'account'}}):
            result = publication.poll_once(products=products, refresh=refresh)
        self.assertEqual([row['id'] for row in calls], ['P-fixture', 'P-second'])
        self.assertEqual(result, {'refreshed': 1, 'failed': 1, 'skipped': 3})

    def test_poller_start_is_idempotent_and_never_runs_the_loop_in_the_caller(self):
        with patch.object(publication, '_poll_thread', None), patch('threading.Thread') as thread:
            thread.return_value.is_alive.return_value = True
            publication.start_polling(); publication.start_polling()
            self.assertEqual(thread.call_count, 1)
            self.assertEqual(thread.call_args.kwargs['daemon'], True)
            thread.return_value.start.assert_called_once()

    def test_collector_never_reuses_a_stale_output_when_cli_returns_without_writing(self):
        with self.temporary() as directory:
            root = Path(directory); self.observation(root)
            schema = json.loads((root / 'schema.json').read_text(encoding='utf-8'))
            def run(command, **kwargs):
                return json.dumps(schema) if command[1] == 'schema' else '{}'
            with self.assertRaises(FileNotFoundError):
                publication.collect({'store': 'fixture', 'expected_account': 'account',
                                     'product_id': '123', 'draft_id': '123'}, root,
                                    bridge=root / 'bridge', run=run, require_identity=lambda *a, **k: None)

    def test_refresh_api_refuses_to_overwrite_a_changed_revision_or_draft(self):
        import operations_api
        for changed in ('revision', 'draft'):
            with self.subTest(changed=changed), self.temporary() as directory:
                root = Path(directory)
                with patch.multiple(store, STATE=root, DB=root / 'fixture.sqlite'):
                    product = store.create_product('publication:fixture', 'Fixture', facts={'store': 'youhealth'})
                    product.update(draft={'draft_id': '123'}, publication={'status': 'previous'})
                    store.save_product(product)
                    def query(snapshot):
                        current = store.product(snapshot['id'])
                        if changed == 'revision': current['revision'] += 1
                        else: current['draft']['draft_id'] = '124'
                        store.save_product(current)
                        return {'status': 'unknown', 'checked_at': 'fixture'}
                    with patch.object(adapter, 'refresh_publication', side_effect=query):
                        with self.assertRaises(ValueError):
                            operations_api.command({'action': 'publication.refresh', 'id': product['id']})
                    self.assertEqual(store.product(product['id'])['publication'], {'status': 'previous'})

    def test_poll_loop_waits_sixty_seconds_after_failures_without_immediate_retry(self):
        with patch.object(publication, '_poll_thread', None), patch('threading.Thread') as thread:
            publication.start_polling()
            loop = thread.call_args.kwargs['target']
        with patch.object(publication, 'poll_once', side_effect=ValueError('fixture failure')) as poll, \
                patch('threading.Event') as event:
            event.return_value.wait.side_effect = SystemExit
            with self.assertRaises(SystemExit): loop()
            poll.assert_called_once_with()
            event.return_value.wait.assert_called_once_with(60)


if __name__ == '__main__': unittest.main()
