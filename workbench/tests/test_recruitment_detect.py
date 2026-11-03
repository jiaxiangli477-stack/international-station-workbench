"""Offline checks for account-bound, hash-backed draft eligibility diagnostics."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = Path('D:/Codex/国际站工作台/repair-chain-20261101/platform/tests')


class DetectionTests(unittest.TestCase):
    def setUp(self):
        BASE.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=BASE)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = ROOT / 'recruitment_detect.py'
        self.assertTrue(self.path.is_file(), 'The account-bound draft detector is not implemented')
        spec = importlib.util.spec_from_file_location('detection_fixture', self.path)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        self.product = {'id': 'P-fixture', 'revision': 6, 'facts': {'store': 'youhealth'},
                        'draft': {'status': 'completed', 'store': 'youhealth', 'revision': 6,
                                  'draft_id': '123', 'readback_verified': True},
                        'recruitment': {'store': 'youhealth', 'topicId': '456', 'fingerprint': 'a' * 64}}
        self.schema = {'success': True, 'command': 'workctl icbu recruitment-topic product-topic-detect',
                       'description': '检测草稿品', 'params': [
                           {'name': 'productId', 'type': 'integer', 'required': True, 'agent_flag': '--prod-id'},
                           {'name': 'topicId', 'type': 'integer', 'required': True, 'agent_flag': '--topic-id'},
                           {'name': 'productVersion', 'type': 'string', 'required': False, 'agent_flag': '--product-version'}]}
        self.response = {'success': True, 'meta': {'mode': 'live', 'mutating': False,
                          'path': 'icbu.recruitment-topic.product-topic-detect'},
                         'data': {'success': True, 'rc': 'SUCCESS', 'value': {'detectionResultDTO': {
                             'isChecked': True, 'meet': False, 'detectionItemDTOList': [
                                 {'itemCode': 'picture', 'itemName': '图片检测', 'type': 'NEED_PIC_MATCH',
                                  'meet': False, 'description': '<script>bad()</script>主体不符',
                                  'itemValue': ['要求相似<br><a href="https://example.invalid">查看图片</a>'],
                                  'extend': {'score': 0.22}}]}}}}
        self.calls = []
        self.identities = []

    def runner(self, command, **kwargs):
        self.calls.append(command)
        self.assertEqual(kwargs['env']['TMP'], kwargs['env']['TEMP'])
        self.assertEqual(Path(kwargs['env']['WORKCTL_CONFIG_DIR']).parent.resolve(), self.root.resolve())
        if command[1] == 'schema':
            return json.dumps(self.schema)
        self.assertEqual(command[1:4], ['icbu', 'recruitment-topic', 'product-topic-detect'])
        self.assertEqual(command[command.index('--product-version') + 1], 'draft')
        self.assertNotIn('--yes', command)
        Path(command[command.index('--output') + 1]).write_text(json.dumps(self.response), encoding='utf-8')
        return '{}'

    def identity(self, bridge, output, expected, **kwargs):
        self.identities.append(output)
        output.write_text(json.dumps({'CURRENT_SELF_ALIID': expected}), encoding='utf-8')

    def collect(self):
        return self.mod.collect(self.product, self.root, bridge=self.root / 'bridge',
                                run=self.runner, require_identity=self.identity)

    def test_successful_query_is_failed_eligibility_and_html_is_plain_text(self):
        result = self.collect()
        self.assertEqual(result['status'], 'FAILED')
        self.assertIs(result['meet'], False)
        self.assertEqual(result['items'][0]['score'], 0.22)
        self.assertNotIn('<', json.dumps(result['items']))
        self.assertNotIn('bad()', json.dumps(result['items']))
        self.assertEqual(len(self.identities), 2)
        self.product['platformDetection'] = result
        self.assertEqual(self.mod.current(self.product)['status'], 'FAILED')

    def test_all_pass_is_passed_and_current_reparses(self):
        dto = self.response['data']['value']['detectionResultDTO']
        dto['meet'] = dto['detectionItemDTOList'][0]['meet'] = True
        result = self.collect()
        self.product['platformDetection'] = result
        self.assertEqual(self.mod.current(self.product)['status'], 'PASSED')
        self.product['platformDetection']['status'] = 'FAILED'
        self.assertEqual(self.mod.current(self.product)['status'], 'STALE')

    def test_missing_or_unverified_draft_and_mismatched_bindings_block_before_calls(self):
        original = deepcopy(self.product)
        for key, value in [('draft', None), ('draft.readback_verified', False), ('draft.status', 'pending'),
                           ('draft.revision', 5), ('draft.store', 'lifeworthcn'), ('draft.draft_id', 'x'),
                           ('recruitment.store', 'lifeworthcn'), ('recruitment.topicId', 'x')]:
            with self.subTest(key=key):
                self.product = deepcopy(original)
                parts = key.split('.')
                if len(parts) == 1: self.product[key] = value
                else: self.product[parts[0]][parts[1]] = value
                with self.assertRaises(ValueError): self.collect()
        self.assertEqual(self.calls, [])

    def test_wrong_account_or_schema_does_not_call_detector(self):
        def wrong(*args, **kwargs): raise ValueError('wrong account')
        with self.assertRaises(ValueError):
            self.mod.collect(self.product, self.root, bridge=self.root / 'bridge',
                             run=self.runner, require_identity=wrong)
        self.schema['params'][2]['agent_flag'] = '--unknown'
        with self.assertRaises(ValueError): self.collect()
        self.assertTrue(all(c[1] == 'schema' for c in self.calls))

    def test_identity_output_itself_must_match_before_and_after(self):
        for failure in ('before', 'after'):
            self.calls.clear()
            def identity(bridge, output, expected, **kwargs):
                account = 'wrong' if failure in output.name else expected
                output.write_text(json.dumps({'CURRENT_SELF_ALIID': account}), encoding='utf-8')
            with self.assertRaises(ValueError):
                self.mod.collect(self.product, self.root, bridge=self.root / 'bridge',
                                 run=self.runner, require_identity=identity)
            if failure == 'before': self.assertEqual(self.calls, [])

    def test_response_requires_live_readonly_checked_strict_booleans(self):
        original = deepcopy(self.response)
        for mutate in [lambda x: x.update(success=False),
                       lambda x: x['meta'].update(mutating=True),
                       lambda x: x['meta'].update(mode='cached'),
                       lambda x: x['meta'].update(path='another.tool'),
                       lambda x: x['data'].update(success=False),
                       lambda x: x['data'].update(rc='FAIL'),
                       lambda x: x['data']['value']['detectionResultDTO'].update(isChecked=False),
                       lambda x: x['data']['value']['detectionResultDTO'].update(meet=0),
                       lambda x: x['data']['value']['detectionResultDTO']['detectionItemDTOList'][0].update(meet='false')]:
            self.response = deepcopy(original); mutate(self.response)
            with self.assertRaises(ValueError): self.collect()

    def test_changed_response_request_identity_or_scope_is_stale(self):
        for evidence in ['response', 'request', 'identityBefore', 'identityAfter', 'schema']:
            result = self.collect(); self.product['platformDetection'] = result
            Path(result['authority']['files'][evidence]['path']).write_text('{}', encoding='utf-8')
            self.assertEqual(self.mod.current(self.product)['status'], 'STALE', evidence)
        for mutate in [lambda p: p.update(revision=7),
                       lambda p: p['recruitment'].update(topicId='789'),
                       lambda p: p['recruitment'].update(fingerprint='b'*64),
                       lambda p: p['draft'].update(readback_verified=False)]:
            p = deepcopy(self.product); p['platformDetection'] = self.collect(); mutate(p)
            self.assertEqual(self.mod.current(p)['status'], 'STALE')

    def test_not_run_and_expired_or_future_timestamp(self):
        self.assertEqual(self.mod.current(self.product)['status'], 'NOT_RUN')
        result = self.collect(); self.product['platformDetection'] = result
        for hours in [-25, 1]:
            result['checkedAt'] = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
            record = result['authority']['files']['request']
            path = Path(record['path'])
            request = json.loads(path.read_text(encoding='utf-8'))
            request['checkedAt'] = result['checkedAt']
            path.write_text(json.dumps(request), encoding='utf-8')
            record['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(self.mod.current(self.product)['status'], 'STALE')


if __name__ == '__main__':
    unittest.main()
