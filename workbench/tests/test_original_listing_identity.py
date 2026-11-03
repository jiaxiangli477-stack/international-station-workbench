"""Run actual adapter/receipt bodies offline, without production stores or processes."""
import ast
from contextlib import nullcontext
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
SANDBOX=ROOT.parents[0]/'docs/original-listing-identity-test'


def load_function(name,namespace):
    tree=ast.parse((ROOT/'listing_adapter.py').read_text(encoding='utf-8-sig'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'listing_adapter.py','exec'),namespace)
    return namespace[name]


class OriginalListingIdentityTests(unittest.TestCase):
    def setUp(self):
        SANDBOX.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=SANDBOX)
        self.root=Path(self.tmp.name)
        self.product={'id':'fixture-product','revision':6,'facts':{'store':'fixture-store'},
                      'workflow':{'listingMechanism':'original-skill-v1'},
                      'attributePlan':{'manifest':{'fields':{'product_name':'Fixture'}},'skillContract':{'fixture':'hash'}}}
        self.job={'id':'fixture-listing','product':self.product['id'],'revision':6}
        self.delivery=[{'slot':'m1','section':'main','exportHash':'fixture-hash'}]
        self.receipt={'draft_id':'123','draft_url':'https://post.alibaba.com/product/publish.htm?itemId=123',
                      'store':'fixture-store','published':False,'actualAccountVerified':True,'category_id':'fixture-category',
                      'fields':{'product_name':{'actual':'Fixture','matched':True}},
                      'acceptancePolicy':'original-skill-draft-review','image_review_required':True,'image_readback_verified':False,
                      'image_checks':[{'slot':'m1','exportHash':'fixture-hash','uploadInvoked':True,'reviewRequired':True}]}
        self.report={'status':'completed','category_routing':{'selected_cat_id':'fixture-category'},
                     'post_save_verification':{'status':'verified','missing_required':[],'structure_mismatches':[]},
                     'images':{'main_count':1,'detail_count':0}}
        self.bridge=SimpleNamespace(current_bridge=Mock(return_value='fixture-bridge'))
        self.identity=Mock()
        self.browser_ready=Mock()
        self.weekly=SimpleNamespace(STORES={'fixture-store':{'expected_id':'fixture-account'}},require_identity=self.identity)
        self.store=SimpleNamespace(job_update=Mock())
        self.persist=Mock()
        self.preparation=Mock()
        def prepare(product,root,skills):
            (root/'listing-context.json').write_text(json.dumps({'listingMechanism':'original-skill-v1'}),encoding='utf-8')
            return {'status':'READY'}
        self.prepare=Mock(side_effect=prepare)
        def execute(command,**kwargs):
            if command[-1]=='preflight':
                (self.root/'listing-preflight.json').write_text(json.dumps({'category':'fixture-category'}),encoding='utf-8')
            else:
                context=json.loads((self.root/'listing-context.json').read_text(encoding='utf-8'))
                self.assertEqual(context['expectedAccount'],'fixture-account')
                (self.root/'reports').mkdir(exist_ok=True)
                (self.root/'reports/run-all-report.json').write_text(json.dumps(self.report),encoding='utf-8')
                (self.root/'readback.json').write_text(json.dumps(self.receipt),encoding='utf-8')
            return SimpleNamespace(returncode=0)
        self.process=Mock(side_effect=execute)
        validate=load_function('validate_receipt',{'urlsplit':urlsplit})
        self.run=load_function('run',{
            'json':json,'store':self.store,'skill_contract':lambda _: {'fixture':'hash'},
            'prepare_original_skill':self.prepare,'export_images':lambda *_:self.delivery,
            'persist_skill_preparation':self.preparation,
            'session_lock':lambda _:nullcontext(),'subprocess':SimpleNamespace(run=self.process),
            'command':lambda root,skills,mode:['offline-runner',mode],'environment':lambda:{},
            'persist_attempt':self.persist,'validate_receipt':validate})
        self.modules={'attribute_plan':SimpleNamespace(blockers=lambda _:[]),
                      'bridge_catalog':self.bridge,'weekly_update':self.weekly,
                      'listing_browser':SimpleNamespace(ensure_ready=self.browser_ready),
                      'topic_workflow':SimpleNamespace(handoff=lambda _:None)}

    def tearDown(self):self.tmp.cleanup()

    def execute(self):
        with patch.dict(sys.modules,self.modules):
            return self.run(self.job,self.product,self.root,Path('offline-skills'))

    def test_original_skill_never_requires_independent_accio_bridge(self):
        self.bridge.current_bridge.side_effect=AssertionError('Accio bridge unavailable')
        self.identity.side_effect=AssertionError('Accio is signed into a different store')
        before=copy.deepcopy(self.product)
        result=self.execute()
        self.assertTrue(result['readback_verified'])
        self.assertTrue(result['image_review_required'])
        self.assertFalse(result['image_readback_verified'])
        self.bridge.current_bridge.assert_not_called();self.identity.assert_not_called()
        self.assertEqual([call.args[0][-1] for call in self.process.call_args_list],['preflight','execute'])
        self.assertEqual(self.product,before)

    def test_legacy_flow_preserves_both_accio_identity_checks(self):
        self.product['workflow']['listingMechanism']='legacy'
        self.execute()
        self.bridge.current_bridge.assert_called_once_with()
        self.assertEqual(self.identity.call_count,2)
        self.assertEqual([call.args[1].name for call in self.identity.call_args_list],['identity.json','identity-after.json'])
        self.assertTrue(all(call.args[2]=='fixture-account' for call in self.identity.call_args_list))
        self.browser_ready.assert_not_called()

    def test_original_skill_still_rejects_actual_browser_identity_category_or_field_failure(self):
        for key,value in [('actualAccountVerified',False),('store','wrong-store'),('category_id','wrong-category')]:
            with self.subTest(check=key):
                previous=self.receipt[key];self.receipt[key]=value
                with self.assertRaisesRegex(ValueError,'实际店铺、类目、身份'):self.execute()
                self.receipt[key]=previous
        self.receipt['fields']['product_name']['matched']=False
        with self.assertRaisesRegex(ValueError,'草稿字段'):self.execute()
        self.bridge.current_bridge.assert_not_called();self.identity.assert_not_called()

    def test_original_skill_still_blocks_preflight_gaps_and_duplicate_drafts(self):
        self.prepare.side_effect=None
        self.prepare.return_value={'status':'BLOCKED','content_preflight':{'blockingDiagnostics':['净重待核验']},'pending_requirements':[]}
        with self.assertRaisesRegex(ValueError,'净重待核验'):self.execute()
        self.preparation.assert_called_once_with(self.product,self.prepare.return_value)
        self.product['draft']={'draft_id':'existing'}
        with self.assertRaisesRegex(ValueError,'已有草稿线索'):self.execute()
        self.process.assert_not_called();self.bridge.current_bridge.assert_not_called();self.identity.assert_not_called()

    def test_changed_preparation_scope_stops_before_any_browser_execution(self):
        self.preparation.side_effect=ValueError('属性方案或图片已变化')
        with self.assertRaisesRegex(ValueError,'已变化'):self.execute()
        self.process.assert_not_called();self.bridge.current_bridge.assert_not_called();self.identity.assert_not_called()

    def test_original_skill_browser_not_ready_cannot_create_an_uncertain_save_attempt(self):
        self.browser_ready.side_effect=ValueError('原Skill CDP 未就绪')
        with self.assertRaisesRegex(ValueError,'CDP 未就绪'):self.execute()
        self.assertEqual([call.args[0][-1] for call in self.process.call_args_list],['preflight'])
        self.persist.assert_not_called();self.store.job_update.assert_not_called()
        self.assertFalse((self.root/'readback.json').exists())


if __name__=='__main__':unittest.main()
