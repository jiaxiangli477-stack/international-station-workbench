"""Offline draft invalidation regressions; SQLite lives only in memory."""
import ast
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import task_store as store
import concept_direction
import topic_workflow
import production_flow


class DraftHistoryRegression(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('CREATE TABLE products(id TEXT PRIMARY KEY, source TEXT UNIQUE, data TEXT);'
                               'CREATE TABLE jobs(id TEXT, scope TEXT, status TEXT, data TEXT);')

        @contextmanager
        def memory_db():
            with self.conn:
                yield self.conn
        self.db_patch = patch.object(store, 'db', memory_db)
        self.db_patch.start()
        self.addCleanup(self.conn.close)
        self.addCleanup(self.db_patch.stop)

    def product(self, uncertain=False):
        p = store.create_product('mock:history', 'Protein powder', facts={'mode': 'concept', 'store': 'mock-store'})
        p['draft'] = {'draft_id': 'mock-existing', 'readback_verified': not uncertain,
                      'uncertain': uncertain, 'receipt': {'path': 'mock-readback.json'}, 'revision': 1}
        p['draftHistory'] = [{'draft_id': 'older-draft', 'store': 'older-store'}]
        p['recruitment'] = {'conceptDesign': {'sourceFingerprint': 'mock', 'form': 'Gummy'},
                            'entries': {}, 'snapshot': {'requirements': [], 'categoryIds': ['123']}}
        return store.save_product(p)

    def assert_history(self, p, original):
        self.assertIsNone(p['draft'])
        self.assertEqual(p['draftHistory'][0], {'draft_id': 'older-draft', 'store': 'older-store'})
        old = p['draftHistory'][-1]
        for key, value in original.items():
            self.assertEqual(old[key], value)
        self.assertEqual(old['store'], 'mock-store')
        self.assertTrue(old['invalidatedAt'])
        self.assertTrue(old['invalidationReason'])

    def test_all_invalidation_paths_preserve_saved_and_uncertain_drafts(self):
        for uncertain in (False, True):
            for path in ('packaging', 'visual', 'topic', 'concept', 'facts'):
                with self.subTest(path=path, uncertain=uncertain):
                    self.conn.execute('DELETE FROM products')
                    self.conn.commit()
                    p = self.product(uncertain)
                    original = copy.deepcopy(p['draft'])
                    if path in ('packaging', 'visual'):
                        p = store.commit_output(p['id'], 1, path, {'revision': 1, 'job': 'new'})
                    elif path == 'topic':
                        p = topic_workflow.save(p['id'], 1, {'category': {'actual': '123', 'evidence': 'mock'}})
                    elif path == 'concept':
                        with patch.dict(sys.modules, {'packaging_design': SimpleNamespace(digest=lambda _: 'mock')}):
                            p = concept_direction.resolve(p['id'], 1, 'title')
                    else:
                        p = store.amend_product(p['id'], dict(p['facts'], design='new'), 1)
                    self.assert_history(p, original)
                    self.assert_history(store.product(p['id']), original)

    def test_regeneration_keeps_both_duplicate_draft_guards(self):
        p = self.product()
        p['draftHistory'] = []  # Existing installations may never have archived a draft.
        store.save_product(p)
        p = store.commit_output(p['id'], 1, 'visual', {'revision': 1, 'job': 'visual'})
        import attribute_plan
        plan = {'revision': 1, 'manifest': {'fields': {'product_name': 'Mock'}}}
        plan['fingerprint'] = attribute_plan.fingerprint(plan)
        p['visual']['attributePlanFingerprint'] = plan['fingerprint']
        p.update(attributePlan=plan, packaging={'revision': 1, 'job': 'pack', 'attributePlanFingerprint': plan['fingerprint']},
                 approvedPackaging='pack', approvedVisual='visual')
        store.save_product(p)
        with patch.dict(sys.modules, {'skill_jobs': SimpleNamespace(missing=lambda *_: [])}), \
                patch.object(production_flow.attribute_plan, 'blockers', return_value=[]), \
                patch.object(concept_direction, 'conflict', return_value=''):
            self.assertEqual(production_flow.plan(p)['next'], 'input')
        node = next(n for n in ast.parse((ROOT/'operations_api.py').read_text(encoding='utf-8')).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'command')
        env = {'store': store}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT/'operations_api.py'), 'exec'), env)
        with self.assertRaisesRegex(ValueError, '已有草稿记录'):
            env['command']({'action': 'product.run', 'id': p['id'], 'revision': 1, 'kind': 'listing'})

    def test_first_output_does_not_create_history_or_change_listing_commit(self):
        p = store.create_product('mock:first', 'Mock', facts={'mode': 'concept'})
        p = store.commit_output(p['id'], 1, 'packaging', {'revision': 1})
        self.assertFalse(p.get('draftHistory'))
        result = {'draft_id': 'new-draft', 'readback_verified': True}
        self.assertEqual(store.commit_output(p['id'], 1, 'listing', result)['draft'], result)

    def test_listing_success_keeps_uncertain_attempt_history(self):
        p = self.product()
        attempt = {'attempt_id': 'mock-attempt', 'store': 'mock-store',
                   'reconciliationRequired': True, 'readback': {'draft_id': 'existing'}}
        p['draft'] = attempt
        store.save_product(p)
        saved = store.commit_output(p['id'], 1, 'listing', {'draft_id': 'existing', 'readback_verified': True})
        self.assertEqual(saved['draft']['draft_id'], 'existing')
        self.assertEqual(saved['draftHistory'][-1]['attempt_id'], 'mock-attempt')
        self.assertEqual(saved['draftHistory'][-1]['readback']['draft_id'], 'existing')

    def test_recruitment_reference_refresh_archives_without_mutating_input(self):
        p = self.product(True)
        target = {'id': '123', 'businessType': 'HOT_PRODUCT', 'title': 'Powder', 'requirements': []}
        node = next(n for n in ast.parse((ROOT/'recruitment_images.py').read_text(encoding='utf-8')).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'prepare')
        env = {'copy': copy, 'json': json, 'store': store, 'topic': topic_workflow}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROOT/'recruitment_images.py'), 'exec'), env)
        changed = env['prepare'](target, 'mock-store', p)
        self.assert_history(changed, p['draft'])
        self.assertEqual(p['draft']['draft_id'], 'mock-existing')

    def test_output_bound_to_old_attribute_plan_is_rejected(self):
        import attribute_plan
        p = self.product()
        plan = {'revision': 1, 'manifest': {'fields': {'product_name': 'New'}}}
        plan['fingerprint'] = attribute_plan.fingerprint(plan)
        p['attributePlan'] = plan
        store.save_product(p)
        for kind in ('packaging', 'visual'):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, '属性'):
                store.commit_output(p['id'], 1, kind, {'revision': 1, 'attributePlanFingerprint': 'old'})
        self.assertEqual(store.product(p['id'])['draft'], p['draft'])

    def test_attempt_without_draft_id_is_archived_as_independent_snapshot(self):
        p = self.product(True)
        p['draft'] = {'attempt_id': 'mock-attempt', 'store': 'original-store',
                      'uncertain': True, 'receipt': {'path': 'before.json'}}
        original = p['draft']
        store.archive_draft(p, 'mock_invalidation')
        original['receipt']['path'] = 'after.json'
        self.assertEqual(p['draftHistory'][-1]['receipt']['path'], 'before.json')
        self.assertEqual(p['draftHistory'][-1]['store'], 'original-store')
        self.assertEqual(p['draftHistory'][-1]['attempt_id'], 'mock-attempt')
        p['draft'] = None
        store.archive_draft(p, 'no_second_draft')
        self.assertEqual(len(p['draftHistory']), 2)


if __name__ == '__main__':
    unittest.main()
