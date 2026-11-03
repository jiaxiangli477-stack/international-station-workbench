"""Isolated controller acceptance; all executor receipts are synthetic, no platform writes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
import attribute_plan
import production_flow as flow
import single_approval_flow as single
import task_store as store


class BatchProductionGatesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = store.STATE, store.DB
        store.STATE = Path(self.tmp.name)
        store.DB = store.STATE / 'isolated.sqlite'
        self.patches = [patch('skill_jobs.capability', return_value={'available': True}),
                        patch('skill_jobs.missing', return_value=[]),
                        patch('listing_adapter.skill_contract', return_value={'synthetic': 'isolated-controller'})]
        for item in self.patches: item.start()

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        store.STATE, store.DB = self.old
        self.tmp.cleanup()

    def product(self, source='new', shop='youhealth'):
        index = len(store.records('products'))
        prefix = {'new': 'manual:', 'selection': 'selection:', 'recruitment': 'topic:'}[source]
        p = store.create_product(prefix + str(index), 'Synthetic original concept', facts={
            'mode': 'concept', 'market': 'INTERNAL_B2B', 'form': 'Powder',
            'design': 'Original synthetic concept', 'store': shop})
        if source == 'recruitment':
            p['recruitment'] = {'store': shop, 'topicId': 'synthetic-topic'}
            store.save_product(p)
        return p

    @staticmethod
    def items(products):
        return [{'id': p['id'], 'revision': p['revision']} for p in products]

    def start(self, products, key='youhealth', target='DRAFT'):
        return flow.start(self.items(products), key, True, target=target, approval_policy=single.POLICY)

    def test_draft_missing_store_rejected_before_any_charge_for_all_sources(self):
        for source in ('new', 'selection', 'recruitment'):
            for key in (None, 'youhealth'):
                with self.subTest(source=source, key=key):
                    p = self.product(source, '')
                    before = copy.deepcopy(p)
                    with self.assertRaisesRegex(ValueError, '店铺'):
                        self.start([p], key)
                    self.assertEqual(store.product(p['id']), before)
                    self.assertEqual(store.records('jobs'), [])

    def test_plan_blocks_missing_draft_store_before_attributes_packaging_or_hero(self):
        p = self.product(shop='')
        p['workflow'] = {'approvalPolicy': single.POLICY, 'target': 'DRAFT'}
        result = flow.plan(p)
        self.assertEqual(result['next'], 'input')
        self.assertIn('草稿目标店铺', result['gaps'])

    def test_draft_store_must_still_be_registered_without_explicit_key(self):
        p = self.product(shop='removed-store')
        with self.assertRaisesRegex(ValueError, '店铺'):
            self.start([p], None)
        self.assertEqual(store.records('jobs'), [])

    def test_recruitment_store_mismatch_rejected_even_without_explicit_key(self):
        p = self.product('recruitment')
        p['recruitment']['store'] = 'lifeworthcn'
        store.save_product(p)
        with self.assertRaisesRegex(ValueError, '征品来源'):
            self.start([p], None)
        self.assertEqual(store.records('jobs'), [])

    def test_old_draft_history_does_not_block_explicit_visuals_target(self):
        p = self.product(shop='')
        p['draftHistory'] = [{'draft_id': 'synthetic-old-draft'}]
        store.save_product(p)
        self.assertEqual(self.start([p], None, 'VISUALS')['started'], [p['id']])
        self.assertEqual(store.product(p['id'])['draftHistory'], p['draftHistory'])

    def test_visuals_only_can_start_without_any_store_for_all_sources(self):
        for source in ('new', 'selection', 'recruitment'):
            p = self.product(source, '')
            self.assertEqual(self.start([p], None, 'VISUALS')['started'], [p['id']])
            self.assertEqual(store.product(p['id'])['workflow']['target'], 'VISUALS')
        self.assertEqual([j['kind'] for j in store.records('jobs')], ['attributes'] * 3)

    def test_batch_checks_every_store_before_starting_first_item(self):
        products = [self.product(), self.product('selection', '')]
        with self.assertRaisesRegex(ValueError, '店铺'):
            self.start(products)
        self.assertEqual(store.records('jobs'), [])
        self.assertFalse(store.product(products[0]['id']).get('workflow'))

    def test_cross_store_stale_revision_and_batch_bounds_are_rejected(self):
        for size in (0, 11):
            with self.subTest(size=size), self.assertRaises(ValueError):
                self.start([self.product() for _ in range(size)])
        p = self.product()
        with self.assertRaisesRegex(ValueError, '跨店铺'):
            self.start([p], 'lifeworthcn')
        with self.assertRaisesRegex(ValueError, '资料已变化'):
            flow.preview([{'id': p['id'], 'revision': 999}], 'youhealth')
        self.assertEqual(store.records('jobs'), [])

    def test_draft_history_blocks_original_skill_before_new_paid_work(self):
        p = self.product()
        p['draftHistory'] = [{'draft_id': 'synthetic-old-draft'}]
        p['workflow'] = {'approvalPolicy': single.POLICY, 'target': 'DRAFT',
                         'listingMechanism': 'original-skill-v1'}
        result = flow.plan(p)
        self.assertEqual(result['next'], 'input')
        self.assertTrue(any('历史草稿' in gap for gap in result['gaps']))

    def execute_synthetic(self, job):
        """Commit local fixture receipts through real controllers; never execute a Skill."""
        p = store.product(job['product'])
        root = store.STATE / 'runs' / job['id']
        root.mkdir(parents=True)
        if job['kind'] == 'attributes':
            manifest = {'product_id': p['id'], 'category_dir': 'supplement',
                        'fields': {'product_name': 'Synthetic original concept', 'dosage_form': 'Powder'}}
            (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            with patch('listing_adapter.prepare_content', return_value=(manifest, [])):
                result = attribute_plan.install(p, job, root, {'status': 'completed', 'manifest_file': 'manifest.json',
                    'field_sources': {f'fields.{key}': {'kind': 'DESIGN', 'source': 'Synthetic internal brief'}
                                      for key in manifest['fields']}, 'unresolved': []})
            store.save_product(result)
        else:
            result = {'job': job['id'], 'revision': p['revision'],
                      'attributePlanFingerprint': p['attributePlan']['fingerprint']}
            if job['kind'] == 'listing':
                single.require_listing(p, original_skill=True)
                result.update(draft_id='synthetic-' + p['id'], readback_verified=True,
                              published=False, image_readback_verified=False, image_review_required=True)
            else:
                # One synthetic fixture file per job; module identity remains in each receipt.
                (root / 'images').mkdir()
                Image.new('RGB', (1000, 1000), 'white').save(root / 'images' / 'fixture.png')
                slots = ['A0'] if job['kind'] == 'packaging' else ['m1'] if job['kind'] == 'hero' else sorted(single.SLOTS)
                result['images'] = [{'slot': slot, 'file': 'images/fixture.png', 'specCheck': 'ok'} for slot in slots]
                if job['kind'] == 'hero': result['templateVerified'] = True
                if job['kind'] == 'visual': result['templateCount'] = 18
            if job['kind'] == 'hero':
                single.install_hero(p['id'], p['revision'], result)
            else:
                store.commit_output(p['id'], p['revision'], job['kind'], result)
        store.job_update(job['id'], status='SUCCESS', progress='Synthetic isolated receipt only')
        flow.advance(p['id'])

    def run_to_hero(self, p):
        for kind in ('attributes', 'packaging', 'hero'):
            job = next(j for j in store.records('jobs') if j['product'] == p['id'] and j['status'] == 'QUEUED')
            self.assertEqual(job['kind'], kind)
            self.execute_synthetic(job)
        p = store.product(p['id'])
        self.assertEqual(p['workflow']['status'], 'WAITING_HERO_REVIEW')
        self.assertFalse(any(j['kind'] in ('visual', 'listing') and j['product'] == p['id'] for j in store.records('jobs')))
        return p

    def approve_and_finish(self, p):
        h = p['hero']
        single.approve(p['id'], p['revision'], h['job'], p['attributePlan']['fingerprint'], h['pixelHash'], True)
        flow.advance(p['id'])
        for kind in ('visual', 'listing'):
            job = next(j for j in store.records('jobs') if j['product'] == p['id'] and j['status'] == 'QUEUED')
            self.assertEqual(job['kind'], kind)
            self.execute_synthetic(job)
        current = store.product(p['id'])
        self.assertEqual(current['workflow']['status'], 'DRAFT_SAVED')
        self.assertEqual(current['stage'], 'DRAFT_REVIEW')
        self.assertIs(current['draft']['published'], False)
        self.assertIs(current['draft']['image_readback_verified'], False)
        self.assertEqual(sum('用户确认正式m1' in e['message'] for e in current['events']), 1)
        return current

    def test_three_sources_full_controller_chain_for_batches_one_through_ten(self):
        for source in ('new', 'selection', 'recruitment'):
            for size in range(1, 11):
                with self.subTest(source=source, size=size):
                    store.DB = store.STATE / f'isolated-{source}-{size}.sqlite'
                    products = [self.product(source) for _ in range(size)]
                    self.assertEqual(self.start(products)['started'], [p['id'] for p in products])
                    # Repeating the same request creates no second job and no second approval.
                    before = len(store.records('jobs'))
                    self.start(products)
                    self.assertEqual(len(store.records('jobs')), before)
                    for p in products:
                        self.assertEqual(flow.source(p), source)
                        current = self.approve_and_finish(self.run_to_hero(p))
                        before = len(store.records('jobs'))
                        self.assertEqual(self.start([current])['started'], [])
                        self.assertEqual(len(store.records('jobs')), before)

    def test_duplicates_in_single_batch_start_only_once(self):
        p = self.product()
        result = self.start([p, p])
        self.assertEqual(result['started'], [p['id']])
        self.assertEqual(len(store.records('jobs')), 1)

    def test_failure_isolated_from_other_products_and_recovery_does_not_regenerate(self):
        failed, successful = self.product('selection'), self.product('recruitment')
        self.start([failed, successful])
        failed_hero = self.run_to_hero(failed)
        h = failed_hero['hero']
        single.approve(failed['id'], 1, h['job'], failed_hero['attributePlan']['fingerprint'], h['pixelHash'], True)
        flow.advance(failed['id'])
        visual = next(j for j in store.records('jobs') if j['product'] == failed['id'] and j['kind'] == 'visual')
        store.job_update(visual['id'], status='RUNNING', workerPid=99999999)
        flow.reconcile(alive=lambda _: False)
        failed_before = store.product(failed['id'])
        self.assertEqual(failed_before['workflow']['status'], 'NEEDS_ATTENTION')
        self.assertTrue(next(j for j in store.records('jobs') if j['id'] == visual['id'])['recoveryRequired'])
        self.approve_and_finish(self.run_to_hero(successful))
        before = len(store.records('jobs'))
        self.start([failed_before])
        self.assertEqual(len(store.records('jobs')), before)
        self.assertFalse(any(j['product'] == failed['id'] and j['kind'] == 'listing' for j in store.records('jobs')))
        # Reconcile preserved receipts from the original job, then continue that same scope.
        self.execute_synthetic(visual)
        store.job_update(visual['id'], recoveryRequired=False)
        self.start([store.product(failed['id'])])
        listing = next(j for j in store.records('jobs') if j['product'] == failed['id'] and j['status'] == 'QUEUED')
        self.assertEqual(listing['kind'], 'listing')
        self.execute_synthetic(listing)
        current = store.product(failed['id'])
        self.assertEqual(current['workflow']['status'], 'DRAFT_SAVED')
        self.assertEqual(sum(j['product'] == failed['id'] and j['kind'] == 'visual' for j in store.records('jobs')), 1)
        self.assertEqual(sum('用户确认正式m1' in e['message'] for e in current['events']), 1)

    def test_reconcile_does_not_restart_stopped_or_migration_held_history(self):
        for changes in ({'status': 'STOPPED'}, {'status': 'ACTIVE', 'migrationHold': True}):
            p = self.product()
            p['workflow'] = {'revision': 1, 'target': 'DRAFT', 'approvalPolicy': single.POLICY,
                             'imageProvider': 'codex-native', **changes}
            store.save_product(p)
            before = copy.deepcopy(p)
            flow.reconcile()
            self.assertEqual(store.product(p['id']), before)
        self.assertEqual(store.records('jobs'), [])


if __name__ == '__main__': unittest.main()
