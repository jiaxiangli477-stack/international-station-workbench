"""Offline file/identity provenance checks for the browser publication collector."""
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.find_spec('listing_browser_publication')
if SPEC:
    import listing_browser_publication as collector
else:
    collector = None


class BrowserPublicationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(collector, 'missing browser publication collector')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.target = {'store': 'fixture', 'product_id': '12345', 'draft_id': '12345', 'expected_account': 'owner-fixture'}
        self.calls = []

    def execute(self, args, **kwargs):
        self.calls.append((args, kwargs))
        root = Path(args[-1]).parent
        request = json.loads((root/'request.json').read_text(encoding='utf-8'))
        category = request['target'].get('category_id')
        identity = {'verified': True, 'account_id': 'owner-fixture', 'nested_account_id': '',
                    'source_url': ('https://post.alibaba.com/product/publish.htm?catId=' + category if category else
                                   'https://post.alibaba.com/product/publish.htm?itemId=12345&pubAction=draft'),
                    'observed_at': datetime.now(timezone.utc).isoformat()}
        dom = {'source_url': 'https://i.alibaba.com/prod/product_manage', 'queries': [{
            'tab': '全部(944)', 'queried_id': '12345', 'rows': [{'id_text': 'ID: 12345',
                'status_text': '审核通过\n已上架', 'edit_url': '', 'edit_conflict': False}],
            'response': {'host': 'hz-productposting.alibaba.com', 'path': '/product/managementproducts/asyQueryProductsList.do',
                         'status': 200, 'method': 'GET', 'request_product_id': '12345', 'request_status': 'all',
                         'repository_type': 'all', 'show_type': 'onlyMarket'}}]}
        for filename, data in [('identity-before.json', identity), ('identity-after.json', identity), ('manager-dom.json', dom)]:
            (root/filename).write_text(json.dumps(data), encoding='utf-8')
        def digest(filename):
            return hashlib.sha256((root/filename).read_bytes()).hexdigest()
        observation = {'source': {'kind': 'product_manager_row', 'method': 'GET',
            'url': dom['source_url'], 'evidence_root': str(root),
            'collector_sha256': request['collector_sha256'], 'python_sha256': request['python_sha256'],
            'request_sha256': digest('request.json'), 'dom_sha256': digest('manager-dom.json'),
            'identity_before_sha256': digest('identity-before.json'), 'identity_after_sha256': digest('identity-after.json')},
            'identity': {'verified': True, 'account_id': 'owner-fixture'},
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'row': {'item_id': '12345', 'draft_id': '12345', 'status_field': '商品状态', 'status_text': '已上架'}}
        (root/'observation.json').write_text(json.dumps(observation), encoding='utf-8')
        return SimpleNamespace(returncode=0, stdout='publication observation collected\n', stderr='')

    def collect(self):
        with patch('listing_adapter.environment', return_value={'NODE_PATH': 'D:/fixture/modules'}), \
                patch.object(collector.shutil, 'which', return_value='D:/fixture/node.exe'):
            return collector.collect(self.target, self.root, run=self.execute)

    def verify(self, value):
        return collector.verify_observation(value, '12345', '12345', 'owner-fixture')

    def rewrite(self, observation, filename, mutate, hash_key):
        path = self.root/filename
        data = json.loads(path.read_text(encoding='utf-8'))
        mutate(data)
        path.write_text(json.dumps(data), encoding='utf-8')
        observation['source'][hash_key] = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.root/'observation.json').write_text(json.dumps(observation), encoding='utf-8')

    def test_collect_uses_existing_node_and_json_request_without_inline_account(self):
        observation = self.collect()
        self.assertEqual(self.verify(observation)['status'], 'published')
        args, kwargs = self.calls[0]
        self.assertEqual(args[0], 'D:/fixture/node.exe')
        self.assertEqual(Path(args[-1]), self.root/'request.json')
        self.assertNotIn('owner-fixture', ' '.join(args))
        self.assertEqual(kwargs['env']['NODE_PATH'], 'D:/fixture/modules')

    def test_forged_claim_changed_dom_wrong_owner_and_changed_target_are_rejected(self):
        observation = self.collect()
        forged = copy.deepcopy(observation)
        forged['row']['status_text'] = '已下架'
        with self.assertRaises(ValueError): self.verify(forged)
        (self.root/'manager-dom.json').write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError): self.verify(observation)
        observation = self.collect()
        self.rewrite(observation, 'identity-after.json', lambda data: data.update(account_id='other'), 'identity_after_sha256')
        with self.assertRaises(ValueError): self.verify(observation)
        observation = self.collect()
        self.rewrite(observation, 'request.json', lambda data: data['target'].update(product_id='999'), 'request_sha256')
        with self.assertRaises(ValueError): self.verify(observation)

    def test_hash_consistent_status_injection_and_conflicting_rows_are_rejected(self):
        for change in ('pending', 'duplicate', 'foreign', 'wrong_tab'):
            with self.subTest(change=change):
                observation = self.collect()
                def mutate(data):
                    query = data['queries'][0]
                    if change == 'pending': query['rows'][0]['status_text'] = '审核中'
                    elif change == 'duplicate': query['rows'].append(copy.deepcopy(query['rows'][0]))
                    elif change == 'foreign': query['rows'][0]['id_text'] = 'ID: 912345'
                    else: query['tab'] = '草稿(46)'
                self.rewrite(observation, 'manager-dom.json', mutate, 'dom_sha256')
                with self.assertRaises(ValueError): self.verify(observation)

    def test_draft_requires_empty_all_query_then_exact_draft_tab_and_edit_link(self):
        observation = self.collect()
        def mutate(data):
            all_query = data['queries'][0]
            draft_query = copy.deepcopy(all_query)
            all_query['rows'] = []
            draft_query.update(tab='草稿(46)', rows=[{'id_text': 'ID: 12345', 'status_text': '',
                'edit_url': 'https://post.alibaba.com/product/publish.htm?itemId=12345&pubAction=draft'}])
            draft_query['response']['request_status'] = 'sketch'
            data['queries'].append(draft_query)
        self.rewrite(observation, 'manager-dom.json', mutate, 'dom_sha256')
        observation['row']['status_text'] = '草稿'
        (self.root/'observation.json').write_text(json.dumps(observation), encoding='utf-8')
        self.assertEqual(self.verify(observation)['status'], 'draft')
        self.rewrite(observation, 'manager-dom.json', lambda data: data['queries'].pop(0), 'dom_sha256')
        with self.assertRaises(ValueError): self.verify(observation)

    def test_invalid_target_and_failed_process_never_return_observation(self):
        self.target['product_id'] = 'invalid'
        with self.assertRaises(ValueError): self.collect()
        self.assertEqual(self.calls, [])
        self.target['product_id'] = '12345'
        with patch('listing_adapter.environment', return_value={}), \
                patch.object(collector.shutil, 'which', return_value='D:/fixture/node.exe'):
            with self.assertRaises(ValueError):
                collector.collect(self.target, self.root, run=lambda *args, **kwargs: SimpleNamespace(returncode=1))

    def test_missing_proof_hash_never_disables_hash_verification(self):
        observation = self.collect()
        observation['source'].pop('dom_sha256')
        (self.root/'observation.json').write_text(json.dumps(observation), encoding='utf-8')
        with self.assertRaises(ValueError): self.verify(observation)

    def test_owner_evidence_requires_the_actual_target_editor_url(self):
        observation = self.collect()
        self.rewrite(observation, 'identity-before.json', lambda data: data.update(
            source_url='https://post.alibaba.com/product/publish.htm'), 'identity_before_sha256')
        with self.assertRaises(ValueError): self.verify(observation)

    def test_category_is_optional_owner_probe_only_and_is_bound_to_request(self):
        self.target['category_id'] = '202029902'
        observation = self.collect()
        request = json.loads((self.root/'request.json').read_text(encoding='utf-8'))
        self.assertEqual(request['target']['category_id'], '202029902')
        self.assertEqual(self.verify(observation)['status'], 'published')
        self.assertNotIn('category_id', observation['row'])
        self.rewrite(observation, 'identity-before.json', lambda data: data.update(
            source_url='https://post.alibaba.com/product/publish.htm?catId=999'), 'identity_before_sha256')
        with self.assertRaises(ValueError): self.verify(observation)
        for category in ('0', '-1', 'cat?token=secret', '../123', '1&itemId=999'):
            self.target['category_id'] = category
            with self.subTest(category=category):
                with self.assertRaises(ValueError): self.collect()

    def test_query_response_must_belong_to_exact_product_and_requested_tab(self):
        for key, value in [('request_product_id', '999'), ('request_status', 'sketch'),
                           ('repository_type', 'other'), ('show_type', 'other'), ('method', 'POST')]:
            with self.subTest(key=key):
                observation = self.collect()
                self.rewrite(observation, 'manager-dom.json', lambda data: data['queries'][0]['response'].update(
                    {key: value}), 'dom_sha256')
                with self.assertRaises(ValueError): self.verify(observation)


if __name__ == '__main__': unittest.main()
