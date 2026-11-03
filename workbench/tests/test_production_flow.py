import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

import task_store as store
import operations_api as api
import production_flow as flow
import attribute_plan
import single_approval_flow as single
import native_skill_jobs


class ProductionFlowTests(unittest.TestCase):
    def test_reconcile_ignores_null_and_absent_workflows_on_startup(self):
        products = [{'id':'legacy-null','workflow':None}, {'id':'legacy-absent'},
                    {'id':'active','workflow':{'status':'ACTIVE'}}]
        with patch.object(store,'records',side_effect=lambda table: products if table=='products' else []), patch.object(flow,'advance') as advance:
            self.assertEqual(flow.reconcile(), {'orphaned':0})
        advance.assert_called_once_with('active')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = store.STATE, store.DB
        store.STATE = Path(self.tmp.name)
        store.DB = store.STATE / 'test.sqlite'

    def tearDown(self):
        store.STATE, store.DB = self.old
        self.tmp.cleanup()

    def product(self, source='manual:test'):
        return store.create_product(source, 'New powder', facts={
            'mode': 'concept', 'market': 'INTERNAL_B2B', 'form': 'Powder',
            'design': 'Original powder sachet', 'store': 'youhealth'})

    def ready_images(self, p):
        p.update(packaging={'job': 'pack', 'revision': p['revision'], 'images': []},
                 approvedPackaging='pack', visual={'job': 'visual', 'revision': p['revision'], 'images': []},
                 approvedVisual='visual')
        for key in ('packaging', 'visual'):
            p[key]['factDependencies'] = ['market', 'form', 'spec', 'formula', 'mode', 'design', 'own_image']
        return store.save_product(p)

    def proposal(self, p):
        root = store.STATE / 'runs' / 'attributes'
        root.mkdir(parents=True)
        manifest = {'product_id': p['id'], 'fields': {'product_name': 'New Powder', 'dosage_form': 'Powder'},
                    'category_dir': 'supplement'}
        (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        installed = attribute_plan.install(p, {'id': 'attributes', 'revision': p['revision']}, root, {
            'status': 'completed', 'manifest_file': 'manifest.json',
            'field_sources': {'fields.product_name': {'kind': 'DESIGN', 'source': 'Original design'},
                              'fields.dosage_form': {'kind': 'REFERENCE', 'source': 'Reference category'}},
            'unresolved': []})
        # Synthetic reviewed artifacts in this unit fixture use this exact proposal.
        for key in ('packaging', 'visual'):
            if installed.get(key):
                installed[key]['attributePlanFingerprint'] = installed['attributePlan']['fingerprint']
        return store.save_product(installed)

    def fresh_visual_fixture(self):
        legacy_slots=[f'm{i}' for i in range(1,8)]+['d1','d2','d3','d4','df','d5','d6','dfac','d7','dc','drev','d9']
        p=self.product('manual:fresh-'+str(len(store.records('products'))))
        p['facts']['mode']='real'
        plan={'revision':1,'manifest':{'fields':{'product_name':'New Powder'}},
            'field_sources':{'fields.product_name':{'kind':'DESIGN','source':'Current approved product brief'}},'unresolved':[]}
        plan['fingerprint']=attribute_plan.fingerprint(plan)
        p['attributePlan']=plan
        old=store.enqueue('visual','product:'+p['id'],{'product':p['id'],'revision':1,'store':'youhealth',
            'imageProvider':'codex-native','workflowContinuation':True})
        store.job_update(old['id'],status='NEEDS_ATTENTION',progress='legacy partial')
        old_root=store.STATE/'runs'/old['id'];old_root.mkdir(parents=True)
        sample_m2=self.reference_sample('m2')
        sample_d2=self.reference_sample('d2')
        binding={'job':old['id'],'product':p['id'],'revision':1,
                 'attributePlanFingerprint':plan['fingerprint']}
        (old_root/'input.json').write_text(json.dumps({
            'id':p['id'],'revision':1,
            'executionBinding':binding,
            'nativeTemplateContract':{'templates':{slot:{} for slot in legacy_slots}}}),encoding='utf-8')
        (old_root/'product-concept.json').write_text(json.dumps({
            'product':{'name':'New powder'},'m2':{'sampleReference':sample_m2},
            'm7':{'facts':self.reference_nutrition()['facts']}},ensure_ascii=False),encoding='utf-8')
        (old_root/'detail-concept.json').write_text(json.dumps({
            'product':{'name':'New powder'},'d2':{'sampleReference':sample_d2}},ensure_ascii=False),encoding='utf-8')
        receipts=old_root/'template-receipts';receipts.mkdir()
        (receipts/'m7.json').write_text('{"slot":"m7","legacy":true}',encoding='utf-8')
        partial={'job':old['id'],'revision':1,'templateCount':19,'images':[{'slot':slot,'file':'images/'+slot+'.png'} for slot in legacy_slots[:9]],
            'attributePlanFingerprint':'','complete':False}
        hero_job='confirmed-'+p['id']
        hero_root=store.STATE/'runs'/hero_job/'images';hero_root.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(1000,1000),'blue').save(hero_root/'m1.png')
        hero={'job':hero_job,'revision':1,'attributePlanFingerprint':plan['fingerprint'],'templateVerified':True,'packagingJob':'old-package',
            'images':[{'slot':'m1','file':'images/m1.png','specCheck':'ok'}]}
        partial['attributePlanFingerprint']=plan['fingerprint']
        p.update(packaging={'job':'old-package','revision':1,'attributePlanFingerprint':plan['fingerprint']},hero=hero,visualPartial=partial,
            workflow={'revision':1,'status':'NEEDS_ATTENTION','target':'DRAFT','imageProvider':'codex-native',
                'approvalPolicy':single.POLICY,'job':old['id'],'next':'resume_native'})
        hero['pixelHash']=single.pixel_hash(hero,hero['images'][0])
        scope=single.hero_scope(p)
        p['heroApproval']={**scope,'signature':single.signature(scope),'approvedAt':store.now()}
        return store.save_product(p),old,legacy_slots

    @staticmethod
    def reference_sample(slot):
        mappings={
            'm2':{'ITEM_1':'Whey Protein Isolate','ITEM_2':'Natural Flavors','ITEM_3':'Malic Acid'},
            'd2':{'D2_ING1_NAME':'Whey Protein Isolate','D2_ING2_NAME':'Natural Flavors',
                  'D2_ING3_NAME':'Malic Acid'}}
        return {
            'mode':'sample',
            'source':{'brand':'Example','product':'Protein','variant':'One flavor',
                      'url':'https://example.com/product','accessed':'2026-10-25',
                      'evidenceSection':'Ingredient label'},
            'ingredients':['Whey Protein Isolate','Natural Flavors','Malic Acid'],
            'evidenceText':'Whey Protein Isolate, Natural Flavors, Malic Acid',
            'modules':{slot:mappings[slot]},
            'disclaimer':"Competitor reference only; not this product's formula."}

    @staticmethod
    def reference_nutrition():
        source=('https://example.com/product; Nutrition Facts, One flavor column, '
            'accessed 2026-10-25. Competitor reference for sample display only. Row: Protein 22 g.')
        return {'source':ProductionFlowTests.reference_sample('m2')['source'],'facts':{
            'mode':'sample','facts_title':'Nutrition Facts','facts_header_name':'Nutrition Facts',
            'serving_size':'1 stick (28 g)','source_copy':False,'other_ingredients':'',
            'rows':[{'name':'Protein','amount':22,'unit':'g','dv':'44%','source':source}]}}

    def start_fresh(self,p,**changes):
        args={'items':[{'id':p['id'],'revision':p['revision']}],'key':'youhealth','acknowledge':True,
              'provider':'codex-native','target':'DRAFT','approval_policy':single.POLICY,'fresh_visual_contract':True}
        args.update(changes)
        with patch('skill_jobs.capability',return_value={'available':True}),patch('skill_jobs.missing',return_value=[]):
            return flow.start(**args)

    def fresh_visual18_fixture(self):
        import skill_jobs,native_skill_jobs
        p,old,_=self.fresh_visual_fixture()
        policy=native_skill_jobs.contract(skill_jobs.SKILLS)
        policy['scriptHashes'].pop('reference_sample.py')
        policy['scriptHashes']['build.py']='obsolete-build-hash'
        policy['templates']['m2']['sha256']='obsolete-m2-template-hash'
        policy['templates']['d2']['sha256']='obsolete-d2-template-hash'
        old_root=store.STATE/'runs'/old['id']
        previous=json.loads((old_root/'input.json').read_text(encoding='utf-8'))
        previous['nativeTemplateContract']=policy
        (old_root/'input.json').write_text(json.dumps(previous),encoding='utf-8')
        from production_flow import FRESH_VISUAL_SLOTS
        slots=sorted(FRESH_VISUAL_SLOTS)[:14]
        p['visualPartial'].update(templateCount=18,images=[{'slot':slot,'file':'images/'+slot+'.png'} for slot in slots])
        store.save_product(p)
        return p,old,slots

    def test_fresh_18_contract_archives_legacy_partial_and_queues_distinct_job_via_api(self):
        p,old,legacy_slots=self.fresh_visual_fixture()
        p['visualPartial'].pop('templateCount')
        store.save_product(p)
        old_before=next(j for j in store.records('jobs') if j['id']==old['id'])
        old_input_before=(store.STATE/'runs'/old['id']/'input.json').read_bytes()
        old_receipt_before=(store.STATE/'runs'/old['id']/'template-receipts'/'m7.json').read_bytes()
        with patch('skill_jobs.capability',return_value={'available':True}),patch('skill_jobs.missing',return_value=[]):
            result=api.command({'action':'workflow.start','items':[{'id':p['id'],'revision':1}],
                'store':'youhealth','acknowledgeExecution':True,'imageProvider':'codex-native','target':'DRAFT',
                'approvalPolicy':single.POLICY,'freshVisualContract':True})
        current=store.product(p['id']);jobs=store.records('jobs')
        new=next(j for j in jobs if j['id']!=old['id'])
        archive=current['visualHistory'][-1]
        self.assertEqual(result['started'],[p['id']])
        self.assertNotEqual(new['id'],old['id'])
        self.assertEqual(new['kind'],'visual')
        self.assertEqual(new['imageProvider'],'codex-native')
        self.assertEqual(new['freshVisualContract'],'six-main-twelve-detail-reference-sample-v1')
        self.assertEqual(new['revision'],p['revision'])
        self.assertEqual(new['store'],'youhealth')
        self.assertEqual(new['referenceSamples'],{'m2':self.reference_sample('m2'),'d2':self.reference_sample('d2')})
        self.assertIn('referenceAssets',new)
        self.assertEqual(new['referenceNutrition'],self.reference_nutrition())
        self.assertEqual(archive['job'],old['id'])
        self.assertEqual(archive['revision'],1)
        self.assertEqual(archive['modules'],legacy_slots[:9])
        self.assertTrue(archive['archivedAt'])
        self.assertEqual(archive['asset'],p['visualPartial'])
        self.assertIsNone(current['visualPartial'])
        self.assertEqual(current['workflow']['job'],new['id'])
        self.assertEqual(current['workflow']['next'],'visual')
        self.assertEqual(next(j for j in store.records('jobs') if j['id']==old['id']),old_before)
        self.assertEqual((store.STATE/'runs'/old['id']/'input.json').read_bytes(),old_input_before)
        self.assertEqual((store.STATE/'runs'/old['id']/'template-receipts'/'m7.json').read_bytes(),old_receipt_before)

    def test_updated_18_slot_skill_contract_archives_old_partial_and_queues_new_contract(self):
        p,old,slots=self.fresh_visual18_fixture()
        old_input=(store.STATE/'runs'/old['id']/'input.json').read_bytes()
        result=self.start_fresh(p)
        current=store.product(p['id']);new=next(j for j in store.records('jobs') if j['id']!=old['id'])
        archive=current['visualHistory'][-1]
        self.assertEqual(result['started'],[p['id']])
        self.assertEqual(archive['modules'],slots)
        self.assertEqual((store.STATE/'runs'/old['id']/'input.json').read_bytes(),old_input)
        self.assertEqual(new['freshVisualContract'],'six-main-twelve-detail-reference-sample-v1')
        self.assertEqual(new['referenceSamples'],{'m2':self.reference_sample('m2'),'d2':self.reference_sample('d2')})
        self.assertIn('referenceAssets',new)
        self.assertEqual(new['referenceNutrition'],self.reference_nutrition())
        self.assertIsNone(current['visualPartial'])

    def test_reference_contract_rejects_migration_when_either_module_sample_is_missing(self):
        for missing in ('m2','d2'):
            with self.subTest(missing=missing):
                p,old,_=self.fresh_visual_fixture()
                old_root=store.STATE/'runs'/old['id']
                spec_file=old_root/('product-concept.json' if missing=='m2' else 'detail-concept.json')
                spec=json.loads(spec_file.read_text(encoding='utf-8'))
                del spec[missing]['sampleReference']
                spec_file.write_text(json.dumps(spec),encoding='utf-8')
                before=store.product(p['id'])
                partial=before['visualPartial']
                old_job_before=next(j for j in store.records('jobs') if j['id']==old['id'])
                old_input=(old_root/'input.json').read_bytes()
                with self.assertRaises(ValueError):self.start_fresh(p)
                current=store.product(p['id'])
                self.assertEqual(current,before)
                self.assertEqual(current['visualPartial'],partial)
                self.assertFalse(current.get('visualHistory'))
                self.assertEqual([j['id'] for j in store.records('jobs') if j.get('product')==p['id']],[old['id']])
                self.assertEqual(next(j for j in store.records('jobs') if j['id']==old['id']),old_job_before)
                self.assertEqual((old_root/'input.json').read_bytes(),old_input)

    def test_same_18_contract_without_bound_reference_payload_can_be_migrated(self):
        p,old,_=self.fresh_visual18_fixture()
        import skill_jobs,native_skill_jobs
        policy=native_skill_jobs.contract(skill_jobs.SKILLS)
        old_root=store.STATE/'runs'/old['id']
        previous=json.loads((old_root/'input.json').read_text(encoding='utf-8'))
        previous['nativeTemplateContract']=policy
        previous['referenceSamples']={'m2':self.reference_sample('m2'),'d2':self.reference_sample('d2')}
        previous.pop('referenceNutrition',None)
        (old_root/'input.json').write_text(json.dumps(previous),encoding='utf-8')
        migrated={'referenceSamples':previous['referenceSamples'],'referenceAssets':{},
                  'referenceNutrition':self.reference_nutrition()}
        with patch('visual_reference.migrate',return_value=migrated):
            result=self.start_fresh(p)
        current=store.product(p['id'])
        new=next(j for j in store.records('jobs') if j['id']!=old['id'])
        self.assertEqual(result['started'],[p['id']])
        self.assertEqual(new['referenceSamples'],{'m2':self.reference_sample('m2'),'d2':self.reference_sample('d2')})
        self.assertIn('referenceAssets',new)
        self.assertEqual(new['referenceNutrition'],self.reference_nutrition())
        self.assertIsNone(current['visualPartial'])

    def test_same_18_contract_with_identical_reference_payload_is_not_requeued(self):
        p,old,_=self.fresh_visual18_fixture()
        import skill_jobs,native_skill_jobs
        policy=native_skill_jobs.contract(skill_jobs.SKILLS)
        old_root=store.STATE/'runs'/old['id']
        previous=json.loads((old_root/'input.json').read_text(encoding='utf-8'))
        previous['nativeTemplateContract']=policy
        previous['referenceSamples']={'m2':self.reference_sample('m2'),'d2':self.reference_sample('d2')}
        previous['referenceNutrition']=self.reference_nutrition()
        (old_root/'input.json').write_text(json.dumps(previous),encoding='utf-8')
        partial=store.product(p['id'])['visualPartial']
        jobs=[j['id'] for j in store.records('jobs') if j.get('product')==p['id']]
        with self.assertRaisesRegex(ValueError,'无需切换或重复生成'):
            self.start_fresh(p)
        self.assertEqual(store.product(p['id'])['visualPartial'],partial)
        self.assertEqual([j['id'] for j in store.records('jobs') if j.get('product')==p['id']],jobs)

    def test_fresh_contract_rejects_old_executor_still_running_even_without_recovery_flag(self):
        p,old,_=self.fresh_visual18_fixture()
        store.job_update(old['id'],executorStillRunning=True,recoveryRequired=False)
        with self.assertRaisesRegex(ValueError,'执行器仍在运行'):
            self.start_fresh(p)
        self.assertIsNotNone(store.product(p['id'])['visualPartial'])
        self.assertEqual([j['id'] for j in store.records('jobs') if j.get('product')==p['id']],[old['id']])

    def test_normal_start_still_resumes_legacy_partial_without_new_job(self):
        p,old,_=self.fresh_visual_fixture()
        with patch('skill_jobs.missing',return_value=[]):
            self.assertEqual(flow.plan(p)['next'],'visual')
        before=store.product(p['id'])['visualPartial']
        with patch('skill_jobs.capability',return_value={'available':True}),patch('skill_jobs.missing',return_value=[]):
            flow.start([{'id':p['id'],'revision':1}],'youhealth',True,'codex-native','DRAFT',single.POLICY)
        self.assertEqual([j['id'] for j in store.records('jobs') if j.get('product')==p['id']],[old['id']])
        current=store.product(p['id'])
        self.assertEqual(current['visualPartial'],before)
        self.assertEqual(current['workflow']['next'],'resume_native')

    def test_fresh_contract_rejects_wrong_scope_and_missing_current_approval(self):
        cases=(('target',{'target':'VISUALS'}),('provider',{'provider':'configured'}),
               ('policy',{'approval_policy':None}))
        for label,changes in cases:
            with self.subTest(label=label):
                p,old,_=self.fresh_visual_fixture()
                with self.assertRaises(ValueError):self.start_fresh(p,**changes)
                self.assertEqual([j['id'] for j in store.records('jobs') if j.get('product')==p['id']],[old['id']])
        p,old,_=self.fresh_visual_fixture();p['heroApproval']=None;store.save_product(p)
        with self.assertRaises(ValueError):self.start_fresh(p)
        self.assertEqual([j['id'] for j in store.records('jobs') if j.get('product')==p['id']],[old['id']])

    def test_fresh_contract_rejects_stale_revision_or_nonlegacy_partial(self):
        p,old,_=self.fresh_visual_fixture()
        with self.assertRaises(ValueError):self.start_fresh(p,items=[{'id':p['id'],'revision':2}])
        p,old,_=self.fresh_visual_fixture()
        p['visualPartial']['templateCount']=18
        p['visualPartial']['images']=[row for row in p['visualPartial']['images'] if row['slot']!='m7']
        store.save_product(p)
        with self.assertRaises(ValueError):self.start_fresh(p)
        self.assertEqual([j['id'] for j in store.records('jobs') if j.get('product')==p['id']],[old['id']])

    def test_fresh_contract_rejects_active_old_job_and_non_18_installed_skill(self):
        p,old,_=self.fresh_visual_fixture()
        active=store.enqueue('attributes','product:'+p['id'],{'product':p['id'],'revision':1,'store':'youhealth'})
        with self.assertRaises(ValueError):self.start_fresh(p)
        self.assertEqual(len(store.records('jobs')),2)
        store.job_update(active['id'],status='NEEDS_ATTENTION')
        p,old,_=self.fresh_visual_fixture()
        bad={'templates':{**{f'm{i}':{} for i in range(1,8)},**{k:{} for k in ('d1','d2','d3','d4','df','d5','d6','dfac','d7','dc','drev','d9')}}}
        with patch.object(native_skill_jobs,'contract',return_value=bad):
            with self.assertRaises(ValueError):self.start_fresh(p)
        self.assertEqual([j['id'] for j in store.records('jobs') if j.get('product')==p['id']],[old['id']])

    def test_fresh_contract_rejects_old_task_status_and_prior_workflow_scope_mismatch(self):
        for mismatch in ('old-status','workflow-target','workflow-provider'):
            with self.subTest(mismatch=mismatch):
                p,old,_=self.fresh_visual_fixture()
                if mismatch=='old-status':store.job_update(old['id'],status='SUCCESS')
                elif mismatch=='workflow-target':p['workflow']['target']='VISUALS'
                else:p['workflow']['imageProvider']='configured'
                store.save_product(p)
                with self.assertRaises(ValueError):self.start_fresh(p)
                self.assertEqual([j['id'] for j in store.records('jobs') if j.get('product')==p['id']],[old['id']])

    def test_fresh_contract_enqueue_failure_rolls_back_archive(self):
        p,old,_=self.fresh_visual_fixture()
        enqueue=store.enqueue_in
        def enqueue_then_fail(conn,*args,**kwargs):
            enqueue(conn,*args,**kwargs)
            raise RuntimeError('queue failed')
        with patch('skill_jobs.capability',return_value={'available':True}),patch('skill_jobs.missing',return_value=[]),patch.object(store,'enqueue_in',side_effect=enqueue_then_fail):
            with self.assertRaisesRegex(RuntimeError,'queue failed'):
                flow.start([{'id':p['id'],'revision':1}],'youhealth',True,'codex-native','DRAFT',single.POLICY,True)
        current=store.product(p['id'])
        self.assertEqual(current['visualPartial'],p['visualPartial'])
        self.assertFalse(current.get('visualHistory'))
        self.assertEqual([j['id'] for j in store.records('jobs') if j.get('product')==p['id']],[old['id']])

    def test_three_sources_prepare_shared_new_product_parameters_before_images(self):
        for source in ('manual:a', 'selection:b', 'topic:youhealth:CUSTOMIZATION_PRODUCT:123'):
            p = self.product(source)
            with patch('skill_jobs.capability', return_value={'available': True}):
                flow.start([{'id': p['id'], 'revision': 1}], 'youhealth', True)
            current = store.product(p['id'])
            self.assertEqual(current['workflow']['target'], 'DRAFT')
            self.assertEqual(current['facts']['mode'], 'concept')
            job = next(j for j in store.records('jobs') if j['product'] == p['id'])
            self.assertEqual(job['kind'], 'attributes')
            self.assertEqual(job['imageProvider'], 'codex-native')

    def test_start_is_idempotent_but_a_changed_active_request_conflicts(self):
        p = self.product()
        with patch('skill_jobs.capability', return_value={'available': True}):
            for _ in range(2):
                flow.start([{'id': p['id'], 'revision': 1}], 'youhealth', True)
        self.assertEqual(len(store.records('jobs')), 1)
        with self.assertRaises(ValueError):
            store.enqueue('listing', 'product:' + p['id'], {'product': p['id'], 'revision': 1})

    def test_approved_visuals_continue_to_proposed_attributes_then_wait_for_review(self):
        p = self.ready_images(self.product())
        with patch('skill_jobs.capability', return_value={'available': True}):
            flow.start([{'id': p['id'], 'revision': 1}], 'youhealth', True)
        job = store.records('jobs')[0]
        self.assertEqual(job['kind'], 'attributes')
        self.proposal(store.product(p['id']))
        store.job_update(job['id'], status='SUCCESS')
        flow.advance(p['id'])
        self.assertEqual(store.product(p['id'])['workflow']['status'], 'WAITING_ATTRIBUTES_REVIEW')
        self.assertFalse(any(j['kind'] == 'listing' for j in store.records('jobs')))

    def test_concept_can_reach_listing_only_with_explicit_plan_approval(self):
        p = self.ready_images(self.product())
        self.proposal(p)
        p = store.product(p['id'])
        self.assertIn('新品属性方案审核', flow.plan(p)['gaps'])
        with self.assertRaises(ValueError):
            attribute_plan.approve(p['id'], 1, 'attributes', p['attributePlan']['fingerprint'], False)
        p = attribute_plan.approve(p['id'], 1, 'attributes', p['attributePlan']['fingerprint'], True)
        self.assertEqual(flow.plan(p)['next'], 'listing')
        self.assertEqual(p['facts']['mode'], 'concept')

    def test_review_rejects_different_output_with_same_product_revision(self):
        p = self.product()
        p.update(packaging={'job': 'new-output', 'revision': 1, 'images': []})
        store.save_product(p)
        with self.assertRaises(ValueError):
            api.command({'action': 'product.approve', 'id': p['id'], 'revision': 1,
                         'phase': 'packaging', 'artifactJob': 'old-output'})
        self.assertFalse(store.product(p['id']).get('approvedPackaging'))

    def test_business_only_edit_preserves_visual_approval_and_draft_history(self):
        p = self.ready_images(self.product())
        p['draft'] = {'draft_id': 'saved', 'readback_verified': True}
        store.save_product(p)
        p = store.amend_product(p['id'], {**p['facts'], 'price': '3.00', 'moq': '1000'}, 1)
        self.assertEqual(p['revision'], 2)
        self.assertEqual(p['approvedVisual'], 'visual')
        self.assertEqual(p['visual']['revision'], 2)
        self.assertIsNone(p['draft'])
        self.assertEqual(p['draftHistory'][-1]['draft_id'], 'saved')

    def test_stop_is_not_rearmed_by_later_review_and_resume_is_explicit(self):
        p = self.product()
        with patch('skill_jobs.capability', return_value={'available': True}):
            flow.start([{'id': p['id'], 'revision': 1}], 'youhealth', True)
        flow.stop(p['id'])
        job = store.records('jobs')[0]
        store.job_update(job['id'], status='SUCCESS')
        p = store.product(p['id'])
        p.update(packaging={'job': job['id'], 'revision': 1}, approvedPackaging=job['id'])
        store.save_product(p)
        flow.advance(p['id'])
        self.assertEqual(len(store.records('jobs')), 1)
        self.assertEqual(store.product(p['id'])['workflow']['status'], 'STOPPED')

    def test_reconcile_does_not_blindly_retry_orphan_running_task(self):
        p = self.product()
        job = store.enqueue('packaging', 'product:' + p['id'], {'product': p['id'], 'revision': 1})
        store.claim()
        summary = flow.reconcile(alive=lambda _: False)
        self.assertEqual(store.records('jobs')[0]['status'], 'NEEDS_ATTENTION')
        self.assertTrue(store.records('jobs')[0]['recoveryRequired'])
        self.assertEqual(summary['orphaned'], 1)
        self.assertIsNone(store.claim())

    def test_saved_draft_stops_chain_and_is_not_recreated(self):
        p = self.product()
        p['draft'] = {'draft_id': 'saved', 'readback_verified': True, 'revision': 1}
        store.save_product(p)
        with patch('skill_jobs.capability', return_value={'available': True}):
            result = flow.start([{'id': p['id'], 'revision': 1}], 'youhealth', True)
        self.assertFalse(result['started'])
        self.assertEqual(store.records('jobs'), [])

    def test_stop_between_planning_and_enqueue_prevents_next_stage(self):
        p=self.product();p['workflow']={'revision':1,'status':'ACTIVE','imageProvider':'codex-native'};store.save_product(p)
        def stop_before_enqueue(_):
            flow.stop(p['id'])
            return {'next':'packaging','gaps':[],'message':'test'}
        with patch.object(flow,'plan',side_effect=stop_before_enqueue):flow.advance(p['id'])
        self.assertEqual(store.records('jobs'),[])
        self.assertEqual(store.product(p['id'])['workflow']['status'],'STOPPED')

    def test_worker_pipeline_crosses_review_gates_in_one_master_task(self):
        p=self.product()
        def executor(job):
            current=store.product(p['id'])
            if job['kind']=='attributes':self.proposal(current)
            elif job['kind']=='listing':store.commit_output(p['id'],1,'listing',{'draft_id':'fixture-draft','readback_verified':True,'published':False})
            else:store.commit_output(p['id'],1,job['kind'],{'job':job['id'],'revision':1,'images':[],
                        'attributePlanFingerprint':current['attributePlan']['fingerprint']})
            return {'product':p['id']}
        with patch('skill_jobs.capability',return_value={'available':True}),patch('skill_jobs.run',side_effect=executor):
            flow.start([{'id':p['id'],'revision':1}],'youhealth',True);api.worker()
            current=store.product(p['id'])
            self.assertEqual(current['workflow']['status'],'WAITING_PACKAGING_REVIEW')
            api.command({'action':'product.approve','id':p['id'],'revision':1,'phase':'packaging','artifactJob':current['packaging']['job']});api.worker()
            current=store.product(p['id'])
            self.assertEqual(current['workflow']['status'],'WAITING_VISUAL_REVIEW')
            api.command({'action':'product.approve','id':p['id'],'revision':1,'phase':'visual','artifactJob':current['visual']['job']});api.worker()
            current=store.product(p['id'])
            self.assertEqual(current['workflow']['status'],'WAITING_ATTRIBUTES_REVIEW')
            api.command({'action':'attributes.approve','id':p['id'],'revision':1,'job':'attributes','fingerprint':current['attributePlan']['fingerprint'],'acknowledgeSpecifications':True});api.worker()
        current=store.product(p['id'])
        self.assertEqual(current['workflow']['status'],'DRAFT_SAVED')
        self.assertEqual(current['facts']['mode'],'concept')
        self.assertEqual(sorted(j['kind'] for j in store.records('jobs')),['attributes','listing','packaging','visual'])

    def test_template_comparison_exposes_only_bound_images_inside_the_job(self):
        from PIL import Image
        import native_template_runner
        p=self.product();identity='a'*32
        root=store.STATE/'runs'/identity;(root/'native-requests').mkdir(parents=True)
        scene=root/'scene.png';Image.new('RGB',(20,20),'blue').save(scene)
        p['visualPending']={'job':identity,'revision':1,'images':[{'slot':'m1','file':'m1.png'}]};store.save_product(p)
        request={'scene':str(scene),'scenePixelHash':native_template_runner.image_hash(scene)}
        (root/'native-requests/m1.json').write_text(json.dumps(request),encoding='utf-8')
        self.assertEqual(api.template_file(identity,'m1'),scene)
        Image.new('RGB',(20,20),'red').save(scene)
        with self.assertRaises(ValueError):api.template_file(identity,'m1')
        with self.assertRaises(ValueError):api.template_file(identity,'m2')

    def test_stale_proposal_form_cannot_overwrite_newer_edits(self):
        p=self.product();self.proposal(p);p=store.product(p['id'])
        plan=p['attributePlan'];manifest=copy.deepcopy(plan['manifest'])
        manifest['fields']['product_name']='Revised New Powder'
        updated=attribute_plan.edit(p['id'],1,manifest,plan['field_sources'],[],plan['fingerprint'])
        self.assertEqual(updated['attributePlan']['field_sources']['fields.product_name']['kind'],'DESIGN')
        with self.assertRaises(ValueError):
            attribute_plan.edit(p['id'],1,plan['manifest'],plan['field_sources'],[],plan['fingerprint'])


if __name__ == '__main__':
    unittest.main()
