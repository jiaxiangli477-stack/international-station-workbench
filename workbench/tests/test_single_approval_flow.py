"""Single m1 approval policy: local files and SQLite memory, no external calls."""
import copy
import ast
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import task_store as store
import attribute_plan
import production_flow as flow
try:
    import single_approval_flow as single
except ImportError:
    single = None

POLICY = 'single-hero-v1'


class SingleApprovalTests(unittest.TestCase):
    def setUp(self):
        sandbox = Path(__file__).resolve().parents[2] / 'docs/single-approval/backend-sandbox'
        sandbox.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=sandbox)
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('CREATE TABLE products(id TEXT PRIMARY KEY,source TEXT UNIQUE,data TEXT);'
            'CREATE TABLE jobs(id TEXT PRIMARY KEY,kind TEXT,scope TEXT,status TEXT,data TEXT,created TEXT,updated TEXT);')
        @contextmanager
        def db():
            try:
                yield self.conn
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise
        self.patches = [patch.object(store,'db',db), patch.object(store,'STATE',Path(self.tmp.name)),
            patch.dict(sys.modules, {'skill_jobs': SimpleNamespace(missing=lambda *_: [])})]
        for item in self.patches: item.start()
        proposal = {'revision':1,'job':'attrs','manifest':{'fields':{'product_name':'Synthetic Powder'}},
            'field_sources':{'fields.product_name':{'kind':'DESIGN','source':'synthetic original design'}},'unresolved':[]}
        proposal['fingerprint'] = attribute_plan.fingerprint(proposal)
        self.p = store.create_product('mock:single','Synthetic',facts={'mode':'concept','store':'youhealth','design':'Original design'})
        self.p.update(attributePlan=proposal, approvedAttributes=None,
            packaging={'job':'pack','revision':1,'attributePlanFingerprint':proposal['fingerprint'],'images':[{'slot':'A0','file':'images/A0.png'}]},
            approvedPackaging=None, workflow={'revision':1,'status':'ACTIVE','target':'DRAFT','approvalPolicy':POLICY,'imageProvider':'codex-native'})
        self.image('pack','A0')
        store.save_product(self.p)

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.conn.close()
        self.tmp.cleanup()

    def image(self,job,name='m1',color='white'):
        path = store.STATE/'runs'/job/'images'/(name+'.png')
        path.parent.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(1000,1000),color).save(path)
        return 'images/'+name+'.png'

    def hero(self):
        asset = {'job':'hero-job','revision':1,'attributePlanFingerprint':self.p['attributePlan']['fingerprint'],
            'templateVerified':True,'images':[{'slot':'m1','file':self.image('hero-job'),'specCheck':'ok'}]}
        self.p = single.install_hero(self.p['id'],1,asset)
        return self.p

    def confirm(self):
        self.hero()
        h=self.p['hero']
        self.p=single.approve(self.p['id'],1,h['job'],self.p['attributePlan']['fingerprint'],h['pixelHash'],True)
        return self.p

    def visuals(self, unchecked=False):
        slots=[f'm{i}' for i in range(1,7)]+['d1','d2','d3','d4','df','d5','d6','dfac','d7','dc','drev','d9']
        self.p['visual']={'job':'visual-job','revision':1,'attributePlanFingerprint':self.p['attributePlan']['fingerprint'],
            'templateCount':18,
            'images':[{'slot':key,'file':self.image('visual-job',key),'specCheck':'unchecked' if unchecked and key=='m2' else 'ok'} for key in slots]}
        self.p['approvedVisual']=None
        store.save_product(self.p)

    def test_policy_bypasses_packaging_human_review_but_only_generates_hero_first(self):
        self.assertEqual(flow.plan(self.p)['next'],'hero')

    def test_a0_is_never_accepted_as_formal_m1(self):
        asset=dict(self.p['packaging'],templateVerified=True)
        with self.assertRaises(ValueError): single.install_hero(self.p['id'],1,asset)

    def test_hero_waits_for_exact_pixel_confirmation(self):
        self.hero()
        self.assertEqual(flow.plan(self.p)['next'],'hero_review')
        with self.assertRaises(ValueError): single.approve(self.p['id'],1,'hero-job',self.p['attributePlan']['fingerprint'],'wrong',True)
        self.assertIsNone(store.product(self.p['id']).get('heroApproval'))

    def test_confirmed_hero_unlocks_automatic_visuals_attributes_and_draft(self):
        self.confirm()
        single.require_hero(self.p)
        self.assertEqual(flow.plan(self.p)['next'],'visual')
        self.visuals()
        self.p=single.apply_automatic(self.p['id'])
        self.assertEqual(self.p['approvedVisual'],'visual-job')
        self.assertEqual(self.p['approvedAttributes'],self.p['attributePlan']['fingerprint'])
        self.assertEqual(flow.plan(self.p)['next'],'listing')
        self.assertNotEqual(self.p.get('stage'),'PUBLISHED')

    def test_new_visual_contract_accepts_exactly_18_modules_without_m7(self):
        self.confirm()
        self.visuals()
        self.assertEqual(single.visual_gaps(self.p), [])

    def test_legacy_19_module_receipt_does_not_satisfy_new_visual_contract(self):
        self.confirm()
        self.visuals()
        self.p['visual']['images'].append({'slot':'m7','file':self.image('visual-job','m7'),'specCheck':'ok'})
        self.p['visual']['templateCount']=19
        self.assertIn('新版固定6张主图与12项详情（18项）', single.visual_gaps(self.p))

    def test_pixel_changes_and_attribute_changes_revoke_approval(self):
        self.confirm()
        self.image('hero-job',color='black')
        with self.assertRaises(ValueError): single.require_hero(self.p)
        self.image('hero-job',color='white')
        self.p['attributePlan']['manifest']['fields']['product_name']='Changed'
        self.p['attributePlan']['fingerprint']=attribute_plan.fingerprint(self.p['attributePlan'])
        with self.assertRaises(ValueError): single.require_hero(self.p)

    def test_unchecked_other_module_never_auto_approves(self):
        self.confirm()
        self.visuals(unchecked=True)
        self.p=single.apply_automatic(self.p['id'])
        self.assertIsNone(self.p.get('approvedVisual'))
        result=flow.plan(self.p)
        self.assertEqual(result['next'],'input')
        self.assertTrue(any('质检' in gap or '规格' in gap for gap in result['gaps']))

    def test_unknown_facts_remain_blockers_after_hero_confirmation(self):
        self.p['attributePlan']['unresolved']=['TO_CONFIRM formula']
        self.p['attributePlan']['fingerprint']=attribute_plan.fingerprint(self.p['attributePlan'])
        self.p['packaging']['attributePlanFingerprint']=self.p['attributePlan']['fingerprint']
        store.save_product(self.p)
        self.confirm()
        self.visuals()
        self.p=single.apply_automatic(self.p['id'])
        self.assertIsNone(self.p.get('approvedAttributes'))
        self.assertEqual(flow.plan(self.p)['next'],'input')
        self.assertIn('TO_CONFIRM formula',flow.plan(self.p)['gaps'])

    def test_stopped_or_legacy_products_are_not_automatically_approved(self):
        for mode in ('stopped','legacy'):
            with self.subTest(mode=mode):
                self.p['approvedPackaging']=None
                if mode=='stopped': self.p['workflow']['status']='STOPPED'
                else: self.p['workflow'].pop('approvalPolicy',None)
                store.save_product(self.p)
                updated=single.apply_automatic(self.p['id'])
                self.assertIsNone(updated.get('approvedPackaging'))

    def test_full_visual_cannot_replace_confirmed_m1(self):
        self.confirm()
        self.visuals()
        self.image('visual-job',color='black')
        self.p=single.apply_automatic(self.p['id'])
        self.assertIsNone(self.p.get('approvedVisual'))
        self.assertEqual(flow.plan(self.p)['next'],'input')

    def test_legacy_policy_still_requires_packaging_review(self):
        self.p['workflow'].pop('approvalPolicy')
        self.assertEqual(flow.plan(self.p)['next'],'packaging_review')

    def test_attribute_edit_invalidates_hero_even_commerce_independent_packaging(self):
        self.confirm()
        self.p['packaging']['attributeDependencies']=['fields']
        store.save_product(self.p)
        proposal=self.p['attributePlan']
        manifest=copy.deepcopy(proposal['manifest'])
        manifest['pricing']={'moq':200}
        updated=attribute_plan.edit(self.p['id'],1,manifest,proposal['field_sources'],[],proposal['fingerprint'])
        self.assertIsNone(updated['heroApproval'])
        self.assertEqual(updated['workflow']['status'],'STALE')
        with self.assertRaises(ValueError): single.require_hero(updated)

    def test_stopped_hero_cannot_be_confirmed_to_restart_old_task(self):
        self.hero()
        self.p['workflow']['status']='STOPPED'
        store.save_product(self.p)
        with self.assertRaises(ValueError):
            single.approve(self.p['id'],1,self.p['hero']['job'],self.p['attributePlan']['fingerprint'],self.p['hero']['pixelHash'],True)
        self.assertEqual(store.product(self.p['id'])['workflow']['status'],'STOPPED')

    def test_bad_hero_or_no_real_template_cannot_be_accepted(self):
        for metadata in ({'templateVerified':False},{'specCheck':'bad'}):
            with self.subTest(metadata=metadata):
                asset={'job':'bad-hero','revision':1,'attributePlanFingerprint':self.p['attributePlan']['fingerprint'],
                    'templateVerified':metadata.get('templateVerified',True),
                    'images':[{'slot':'m1','file':self.image('bad-hero'),'specCheck':metadata.get('specCheck','ok')}]}
                with self.assertRaises(ValueError): single.install_hero(self.p['id'],1,asset)

    def test_visual_target_stops_before_attributes_and_draft(self):
        self.confirm()
        self.visuals()
        self.p['workflow']['target']='VISUALS'
        self.assertEqual(flow.plan(self.p)['status'],'VISUALS_READY')

    def command(self,payload):
        path=Path(__file__).resolve().parents[1]/'operations_api.py'
        node=next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='command')
        env={'store':store,'single_approval_flow':single,'production_flow':flow,'attribute_plan':attribute_plan,
            'skill_jobs':SimpleNamespace(missing=lambda *_:[],capability=lambda:{'available':True}),
            'weekly_update':SimpleNamespace(STORES={'youhealth':{}}),'json':json}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),env)
        return env['command'](payload)

    def test_api_rejects_remaining_visuals_before_hero_confirmation(self):
        self.hero()
        with self.assertRaisesRegex(ValueError,'首图'):
            self.command({'action':'product.run','id':self.p['id'],'revision':1,'kind':'visual','acknowledgeExecution':True})
        self.assertEqual(store.records('jobs'),[])

    def test_api_hero_confirmation_queues_only_remaining_visual_job(self):
        self.hero()
        h=self.p['hero']
        updated=self.command({'action':'hero.approve','id':self.p['id'],'revision':1,'artifactJob':h['job'],
            'fingerprint':self.p['attributePlan']['fingerprint'],'pixelHash':h['pixelHash'],'acknowledgeHero':True})
        self.assertTrue(updated['heroApproval']['signature'])
        self.assertEqual([j['kind'] for j in store.records('jobs')],['visual'])

    def test_preview_new_policy_is_read_only(self):
        self.p['workflow'].pop('approvalPolicy')
        store.save_product(self.p)
        with patch.dict(sys.modules,{'weekly_update':SimpleNamespace(STORES={'youhealth':{}})}):
            checked=flow.preview([{'id':self.p['id'],'revision':1}],'youhealth','DRAFT',POLICY)
        self.assertEqual(checked['items'][0]['next'],'hero')
        self.assertNotIn('approvalPolicy',store.product(self.p['id'])['workflow'])

    def test_single_policy_local_lifecycle_needs_only_hero_confirmation(self):
        flow.advance(self.p['id'])
        first=store.records('jobs')[0]
        self.assertEqual(first['kind'],'hero')
        self.p=store.product(self.p['id'])
        self.assertEqual(self.p['approvedPackaging'],'pack')
        self.hero()
        store.job_update(first['id'],status='SUCCESS')
        flow.advance(self.p['id'])
        self.p=store.product(self.p['id'])
        self.assertEqual(self.p['workflow']['status'],'WAITING_HERO_REVIEW')
        h=self.p['hero']
        self.p=self.command({'action':'hero.approve','id':self.p['id'],'revision':1,'artifactJob':h['job'],
            'fingerprint':self.p['attributePlan']['fingerprint'],'pixelHash':h['pixelHash'],'acknowledgeHero':True})
        visual_job=next(j for j in store.records('jobs') if j['kind']=='visual')
        self.visuals()
        store.job_update(visual_job['id'],status='SUCCESS')
        flow.advance(self.p['id'])
        current=store.product(self.p['id'])
        single.require_listing(current)
        listing=next(j for j in store.records('jobs') if j['kind']=='listing')
        # Synthetic readback demonstrates orchestration only, never platform execution.
        store.commit_output(self.p['id'],1,'listing',{'job':listing['id'],'revision':1,
            'readback_verified':True,'published':False,'draft_id':'mock-draft'})
        store.job_update(listing['id'],status='SUCCESS')
        flow.advance(self.p['id'])
        current=store.product(self.p['id'])
        self.assertEqual(current['workflow']['status'],'DRAFT_SAVED')
        self.assertEqual(current['stage'],'DRAFT_REVIEW')
        self.assertIs(current['draft']['published'],False)

    def test_old_visual_approval_cannot_survive_new_quality_failure(self):
        self.confirm()
        self.visuals(unchecked=True)
        self.p['approvedVisual']='visual-job'
        store.save_product(self.p)
        current=single.apply_automatic(self.p['id'])
        self.assertIsNone(current['approvedVisual'])
        with self.assertRaises(ValueError): single.require_listing(current)

    def test_active_legacy_policy_cannot_be_silently_migrated(self):
        self.p['workflow'].pop('approvalPolicy')
        store.save_product(self.p)
        capability=SimpleNamespace(missing=lambda *_:[],capability=lambda:{'available':True})
        with patch.dict(sys.modules,{'weekly_update':SimpleNamespace(STORES={'youhealth':{}}),'skill_jobs':capability}):
            with self.assertRaisesRegex(ValueError,'策略'):
                flow.start([{'id':self.p['id'],'revision':1}],'youhealth',True,'codex-native','DRAFT',POLICY)
        self.assertNotIn('approvalPolicy',store.product(self.p['id'])['workflow'])

    def with_content(self, content, sources=None):
        self.p['attributePlan']['manifest'].update(content)
        self.p['attributePlan']['field_sources'].update(sources or {})
        self.p['attributePlan']['fingerprint']=attribute_plan.fingerprint(self.p['attributePlan'])
        return self.p

    def test_nonfield_business_content_requires_sources_for_all_six_blocks(self):
        self.with_content({'selling_points':['Proposed citrus flavor'], 'faqs':[{'question':'Format?', 'answer':'Proposed sachet'}],
            'company_intro':'Private-label concept project','pricing':{'unit':'pouch','tiers':[{'qty':500,'price':1.2}]},
            'lead_time':{'quantity':500,'days':35},'logistics':{'weight':1,'length':10,'width':10,'height':10}})
        gaps=single.fact_gaps(self.p)
        for field in ('selling_points','faqs','company_intro','pricing','lead_time','logistics'):
            with self.subTest(field=field):
                self.assertTrue(any(field in gap for gap in gaps),gaps)

    def test_leaf_source_does_not_cover_other_claims(self):
        self.with_content({'selling_points':['Proposed citrus flavor','Proposed pouch format']},
            {'selling_points.0':{'kind':'DESIGN','source':'Internal concept brief section 1'}})
        gaps=single.fact_gaps(self.p)
        self.assertTrue(any('selling_points.1' in gap for gap in gaps),gaps)
        self.assertFalse(any('selling_points.0' in gap for gap in gaps),gaps)

    def test_design_or_reference_source_cannot_confirm_certificates_and_measured_claims(self):
        for kind in ('DESIGN','REFERENCE'):
            with self.subTest(kind=kind):
                self.with_content({'selling_points':['Facility operates under NSF-GMP, FSSC 22000 and HACCP.'],
                    'faqs':[{'question':'Quality?', 'answer':'Clinically tested, 5000+ formulations, samples in 1-7 days.'}]},
                    {'selling_points':{'kind':kind,'source':'Internal concept brief; competitor context only'},
                     'faqs':{'kind':kind,'source':'Internal concept brief; competitor context only'}})
                gaps=single.fact_gaps(self.p)
                self.assertTrue(any('selling_points' in gap and 'CONFIRMED' in gap for gap in gaps),gaps)
                self.assertTrue(any('faqs' in gap and 'CONFIRMED' in gap for gap in gaps),gaps)

    def test_sourced_internal_concept_and_confirmed_business_data_are_not_reapproved_manually(self):
        self.with_content({'selling_points':['Proposed citrus flavor in original private-label concept'],
            'company_intro':'Packaging design proposed for this internal concept',
            'pricing':{'unit':'pouch','tiers':[{'qty':500,'price':1.2}], 'source':'synthetic quotation'},
            'faqs':[{'question':'Quality?', 'answer':'Facility operates under GMP.'}]},
            {'selling_points':{'kind':'DESIGN','source':'Internal concept design brief section 2'},
             'company_intro':{'kind':'DESIGN','source':'Internal concept design brief section 3'},
             'pricing':{'kind':'CONFIRMED','source':'Seller quotation fixture Q-2026'},
             'faqs.0.question':{'kind':'DESIGN','source':'Internal concept FAQ outline'},
             'faqs.0.answer':{'kind':'CONFIRMED','source':'Seller facility certificate fixture C-2026'}})
        self.assertEqual(single.fact_gaps(self.p),[])

    def test_real_normalizer_hardcoded_claim_fixture_fails_without_claim_sources(self):
        # Snapshot of R06's real v9.2.38 content-only synthetic fixture. No runtime dependency on its sandbox.
        manifest={'fields':{'product_name':'Synthetic Powder'},'selling_points':[
            'Factory Quality Systems: The facility operates under NSF-GMP, FSSC 22000, and HACCP systems.',
            'Formula sampling is generally supported in 1-7 days; bulk production is about 25-30 days after artwork approval.',
            'OEM/ODM Project Support: Backed by 5,000+ formulation references.'],
            'faqs':[{'question':'What quality documents are available?',
                     'answer':'Batch COA and third-party testing reports can be arranged per project. The facility operates under GMP, FSSC 22000, and HACCP quality systems.'}]}
        proposal=self.p['attributePlan']
        proposal['manifest']=manifest
        proposal['field_sources']={'fields.'+key:{'kind':'DESIGN','source':'Synthetic original input fixture'} for key in manifest['fields']}
        proposal['fingerprint']=attribute_plan.fingerprint(proposal)
        gaps=single.fact_gaps(self.p)
        self.assertTrue(any('selling_points' in gap for gap in gaps),gaps)
        self.assertTrue(any('faqs' in gap for gap in gaps),gaps)

    def test_effective_default_override_does_not_inherit_stale_confirmed_source(self):
        self.with_content({'company_intro':'Original profile default quality systems',
            '_adapter_effective_defaults':{'company_intro':{'status':'TO_CONFIRM','source':'Original Skill profile default'}}},
            {'company_intro':{'kind':'CONFIRMED','source':'Earlier seller introduction document'}})
        self.assertTrue(any('默认覆盖' in gap and 'company_intro' in gap for gap in single.fact_gaps(self.p)))

    def test_hardcoded_skill_source_cannot_be_relabelled_confirmed(self):
        self.with_content({'selling_points':['Factory operates under GMP.']},
            {'selling_points':{'kind':'CONFIRMED','source':'原Skill默认生成器中的公司常量'}})
        self.assertTrue(any('selling_points' in gap for gap in single.fact_gaps(self.p)))

    def test_hero_reuse_keeps_original_unchecked_source_and_actual_approval_scope(self):
        import hero_execution
        self.hero()
        self.p['hero']['images'][0].update(specCheck='unchecked',quality={'reviewRequired':True})
        store.save_product(self.p)
        h=self.p['hero']
        self.p=single.approve(self.p['id'],1,h['job'],self.p['attributePlan']['fingerprint'],h['pixelHash'],True)
        root=store.STATE/'reuse-check'
        policy={}
        hero_execution.prepare_reuse(self.p,root,policy)
        with patch.dict(sys.modules,{'skill_jobs':SimpleNamespace(artifact=lambda base,relative:base/relative)}):
            row=hero_execution.verify_reuse(self.p,root,{'slot':'m1','file':'images/m1.png'},policy)
            self.assertEqual(row['sourceSpecCheck'],'unchecked')
            self.assertEqual(row['quality']['reviewSource'],'explicit-hero-approval')
            self.assertIs(row['quality']['reviewRequired'],False)
            self.image('hero-job',color='black')
            with self.assertRaises(ValueError): hero_execution.verify_reuse(self.p,root,{'slot':'m1','file':'images/m1.png'},policy)

    def test_hero_aggregate_failed_quality_cannot_be_signed(self):
        self.hero()
        self.p['hero']['quality']={'failed':True}
        store.save_product(self.p)
        h=self.p['hero']
        with self.assertRaises(ValueError):
            single.approve(self.p['id'],1,h['job'],self.p['attributePlan']['fingerprint'],h['pixelHash'],True)

    def test_malformed_effective_default_metadata_is_a_gap_not_an_exception(self):
        self.with_content({'_adapter_effective_defaults':['not-a-mapping']})
        self.assertTrue(single.fact_gaps(self.p))

    def test_visual_aggregate_failed_quality_cannot_be_auto_approved(self):
        self.confirm()
        self.visuals()
        self.p['visual']['quality']={'failed':True}
        self.assertTrue(single.visual_gaps(self.p))

    def test_original_skill_blocked_preflight_is_bound_to_current_plan_and_images(self):
        self.confirm()
        self.visuals()
        self.p['workflow']['listingMechanism']='original-skill-v1'
        self.p['listingSkill']={'revision':1,'attributePlanFingerprint':self.p['attributePlan']['fingerprint'],
            'visualJob':self.p['visual']['job'],'status':'BLOCKED',
            'content_preflight':{'blockingDiagnostics':['synthetic required field']}}
        self.assertEqual(flow.plan(self.p)['next'],'input')
        self.p['listingSkill']['visualJob']='old-image-job'
        self.assertEqual(flow.plan(self.p)['next'],'listing')
        self.p['listingSkill']['visualJob']=self.p['visual']['job']
        self.p['listingSkill']['attributePlanFingerprint']='old-plan'
        self.assertEqual(flow.plan(self.p)['next'],'listing')


if __name__=='__main__': unittest.main()
