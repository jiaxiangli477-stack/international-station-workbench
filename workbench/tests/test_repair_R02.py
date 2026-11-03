"""Attribute/artifact binding regression; SQLite memory only, no executors."""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import task_store as store
import attribute_plan
import production_flow as flow


class AttributeBindingTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('CREATE TABLE products(id TEXT PRIMARY KEY,source TEXT UNIQUE,data TEXT);'
            'CREATE TABLE jobs(id TEXT PRIMARY KEY,kind TEXT,scope TEXT,status TEXT,data TEXT,created TEXT,updated TEXT);')

        @contextmanager
        def memory_db():
            try:
                yield self.conn
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise

        self.db_patch = patch.object(store, 'db', memory_db)
        self.db_patch.start()
        self.skill_patch = patch.dict(sys.modules, {'skill_jobs': SimpleNamespace(missing=lambda *_: [])})
        self.skill_patch.start()
        self.p = store.create_product('mock:R02', 'Mock Powder', facts={'mode':'concept','store':'mock'})
        proposal = {'revision':1, 'job':'attrs', 'manifest':{'fields':{
            'product_name':'Mock Powder', 'dosage_form':'Powder'}, 'pricing':{'moq':100}},
            'field_sources':{'fields.product_name':{'kind':'DESIGN','source':'mock'},
                             'fields.dosage_form':{'kind':'DESIGN','source':'mock'}}, 'unresolved':[]}
        proposal['fingerprint'] = attribute_plan.fingerprint(proposal)
        self.p.update(attributePlan=proposal, approvedAttributes=proposal['fingerprint'],
            packaging={'revision':1,'job':'pack','attributePlanFingerprint':proposal['fingerprint']},
            approvedPackaging='pack', workflow={'revision':1,'status':'WAITING_PACKAGING_REVIEW'})
        store.save_product(self.p)

    def tearDown(self):
        self.skill_patch.stop()
        self.db_patch.stop()
        self.conn.close()

    def edit(self, manifest=None):
        proposal = self.p['attributePlan']
        return attribute_plan.edit(self.p['id'], 1, manifest or proposal['manifest'],
            proposal['field_sources'], proposal['unresolved'], proposal['fingerprint'])

    def test_packaging_edit_revokes_approval_and_requires_preflight(self):
        manifest = copy.deepcopy(self.p['attributePlan']['manifest'])
        manifest['fields'].update(product_name='Mock Gummies', dosage_form='Gummy')
        updated = self.edit(manifest)
        self.assertIsNone(updated.get('approvedPackaging'))
        self.assertTrue(updated['packaging']['needsRegeneration'])
        self.assertEqual(updated['workflow']['status'], 'STALE')
        self.assertEqual(flow.plan(updated)['next'], 'packaging')
        self.assertEqual(updated['revision'], 1)

    def test_planner_rejects_legacy_mismatched_approved_packaging(self):
        self.p['packaging']['attributePlanFingerprint'] = 'old'
        self.assertEqual(flow.plan(self.p)['next'], 'packaging')

    def test_planner_rejects_mismatched_visual(self):
        self.p.update(visual={'revision':1,'job':'visual','attributePlanFingerprint':'old'}, approvedVisual='visual')
        self.assertEqual(flow.plan(self.p)['next'], 'visual')

    def test_active_jobs_block_edits_atomically(self):
        for status in ('QUEUED', 'RUNNING'):
            with self.subTest(status=status):
                job = store.enqueue('visual','product:'+self.p['id'], {'product':self.p['id'],'revision':1})
                store.job_update(job['id'], status=status)
                manifest = copy.deepcopy(self.p['attributePlan']['manifest'])
                manifest['fields']['dosage_form'] = 'Gummy'
                with self.assertRaisesRegex(ValueError, '执行|活动'):
                    self.edit(manifest)
                self.assertEqual(store.product(self.p['id']), self.p)
                store.job_update(job['id'], status='SUCCESS')

    def test_commerce_reuses_only_explicit_independent_artifacts(self):
        self.p['packaging']['attributeDependencies'] = ['fields']
        self.p.update(visual={'revision':1,'job':'visual', 'attributePlanFingerprint':self.p['attributePlan']['fingerprint'],
            'attributeDependencies':['fields']}, approvedVisual='visual')
        store.save_product(self.p)
        manifest = copy.deepcopy(self.p['attributePlan']['manifest'])
        manifest['pricing']['moq'] = 200
        updated = self.edit(manifest)
        self.assertEqual(updated['approvedPackaging'], 'pack')
        self.assertEqual(updated['approvedVisual'], 'visual')
        for name in ('packaging','visual'):
            self.assertEqual(updated[name]['attributePlanFingerprint'], updated['attributePlan']['fingerprint'])
        self.assertEqual(flow.plan(updated)['next'], 'attributes_review')

    def test_unknown_commerce_dependencies_invalidate_artifacts(self):
        manifest = copy.deepcopy(self.p['attributePlan']['manifest'])
        manifest['pricing']['moq'] = 200
        updated = self.edit(manifest)
        self.assertIsNone(updated.get('approvedPackaging'))
        self.assertEqual(flow.plan(updated)['next'], 'packaging')

    def test_noop_preserves_packaging_and_stopped_flow(self):
        self.p['workflow']['status'] = 'STOPPED'
        store.save_product(self.p)
        updated = self.edit()
        self.assertEqual(updated['approvedPackaging'], 'pack')
        self.assertEqual(updated['workflow']['status'], 'STOPPED')
        self.assertEqual(flow.plan(updated)['next'], 'visual')

    def test_artifact_contract_preserves_legacy_but_requires_current_binding(self):
        self.assertTrue(attribute_plan.artifact_matches({'revision':1}, {'job':'legacy'}))
        self.assertTrue(attribute_plan.artifact_matches(self.p, self.p['packaging']))
        self.assertFalse(attribute_plan.artifact_matches(self.p, {'revision':1,'job':'no-fingerprint'}))
        self.p['attributePlan']['manifest']['fields']['dosage_form'] = 'Gummy'
        self.assertFalse(attribute_plan.artifact_matches(self.p, self.p['packaging']))

    def test_commerce_dependencies_include_descendants_and_unknown_paths_do_not_authorize_reuse(self):
        for dependencies in (['pricing.moq'], ['unknown']):
            with self.subTest(dependencies=dependencies):
                self.p['packaging']['attributeDependencies'] = dependencies
                store.save_product(self.p)
                manifest = copy.deepcopy(self.p['attributePlan']['manifest'])
                manifest['pricing']['moq'] = 200
                updated = self.edit(manifest)
                self.assertIsNone(updated.get('approvedPackaging'))
                self.assertTrue(updated['packaging']['needsRegeneration'])

    def test_stopped_flow_stays_stopped_when_parameters_change(self):
        self.p['workflow']['status'] = 'STOPPED'
        store.save_product(self.p)
        manifest = copy.deepcopy(self.p['attributePlan']['manifest'])
        manifest['fields']['dosage_form'] = 'Gummy'
        updated = self.edit(manifest)
        self.assertEqual(updated['workflow']['status'], 'STOPPED')
        self.assertIsNone(updated.get('approvedPackaging'))

    def test_partial_without_current_binding_never_automatically_restarts_generation(self):
        self.p['workflow'].update(status='ACTIVE', imageProvider='codex-native')
        self.p['visualPartial'] = {'revision':1,'job':'partial-old'}
        store.save_product(self.p)
        flow.advance(self.p['id'])
        updated = store.product(self.p['id'])
        self.assertEqual(updated['workflow']['status'], 'NEEDS_ATTENTION')
        self.assertEqual(updated['workflow']['next'], 'input')
        self.assertEqual(store.records('jobs'), [])


if __name__ == '__main__':
    unittest.main()
