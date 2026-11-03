"""Exercise the real command/gate bodies in memory; no imports of runtime adapters."""
import ast
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def function_from_source(filename, name, namespace):
    tree = ast.parse((ROOT / filename).read_text(encoding='utf-8-sig'))
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), filename, 'exec'), namespace)
    return namespace[name]


class ManualOriginalListingGateTests(unittest.TestCase):
    def setUp(self):
        self.product = {'id':'fixture-product','revision':6,'facts':{'store':'youhealth'},
                        'workflow':{'approvalPolicy':'single-hero-v1','status':'ACTIVE',
                                    'target':'DRAFT','listingMechanism':'original-skill-v1'},
                        'visual':{'revision':6},'hero_valid':True,'binding_valid':True,'visual_gaps':[]}
        self.payload = {'action':'product.run','id':self.product['id'],'revision':6,
                        'kind':'listing','acknowledgeExecution':True}
        self.enqueued = Mock(return_value={'id':'offline-only','kind':'listing'})
        self.store = SimpleNamespace(product=Mock(return_value=self.product),
                                     records=Mock(return_value=[]),enqueue=self.enqueued)
        def require_hero(product):
            if not product['hero_valid']:
                raise ValueError('首图签名失效')
        self.hero = Mock(side_effect=require_hero)
        self.facts = Mock(return_value=['原方案净重待核验'])
        listing = function_from_source('single_approval_flow.py', 'require_listing', {
            'require_hero':self.hero,'visual_gaps':lambda p:p['visual_gaps'],
            'fact_gaps':self.facts,'attribute_plan':SimpleNamespace(artifact_matches=lambda p,a:p['binding_valid'])})
        self.gate = Mock(wraps=listing)
        self.single = SimpleNamespace(enabled=lambda p:p['workflow']['approvalPolicy']=='single-hero-v1',
                                      apply_automatic=lambda _:self.product,
                                      require_hero=self.hero,require_listing=self.gate)
        self.command = function_from_source('operations_api.py','command',{
            'store':self.store,'weekly_update':SimpleNamespace(STORES={'youhealth':{}}),
            'skill_jobs':SimpleNamespace(missing=Mock(return_value=[]),capability=lambda:{'available':True})})

    def run_command(self, **changes):
        with patch.dict(sys.modules, {'single_approval_flow':self.single}):
            return self.command(dict(self.payload, **changes))

    def test_original_skill_manual_entry_uses_same_gate_mode_as_automatic_runner(self):
        before = copy.deepcopy(self.product)
        self.assertEqual(self.run_command()['id'],'offline-only')
        self.gate.assert_called_once_with(self.product,original_skill=True)
        self.facts.assert_not_called()
        self.assertGreaterEqual(self.hero.call_count,1)
        self.enqueued.assert_called_once_with('listing','product:fixture-product',{
            'product':'fixture-product','revision':6,'store':'youhealth',
            'imageProvider':'codex-native','selectionContinuation':False})
        self.assertEqual(self.product,before)

    def test_historical_mechanisms_keep_existing_fact_checks(self):
        for mechanism in (None,'legacy-browser','workctl-bridge-v1'):
            with self.subTest(mechanism=mechanism):
                self.product['workflow']['listingMechanism']=mechanism
                with self.assertRaisesRegex(ValueError,'净重'):
                    self.run_command()
                self.assertIs(self.gate.call_args.kwargs.get('original_skill'),False)
        self.enqueued.assert_not_called()

    def test_original_skill_cannot_skip_hero_visual_or_target_checks(self):
        cases=[('hero_valid',False,'首图签名'),('binding_valid',False,'完整套图'),
               ('visual_gaps',['模块规格失败'],'模块规格失败')]
        for key,value,reason in cases:
            with self.subTest(check=key):
                original=self.product[key];self.product[key]=value
                with self.assertRaisesRegex(ValueError,reason):self.run_command()
                self.product[key]=original
        self.product['workflow']['target']='VISUALS'
        with self.assertRaisesRegex(ValueError,'仅图片'):self.run_command()
        self.enqueued.assert_not_called()

    def test_revision_store_and_duplicate_guards_still_block_manual_listing(self):
        with self.assertRaisesRegex(ValueError,'资料已更新'):self.run_command(revision=5)
        self.product['draft']={'draft_id':'already-saved'}
        with self.assertRaisesRegex(ValueError,'已有草稿'):self.run_command()
        self.product.pop('draft')
        self.store.records.return_value=[{'product':self.product['id'],'recoveryRequired':True}]
        with self.assertRaisesRegex(ValueError,'待对账'):self.run_command()
        self.store.records.return_value=[]
        self.product['facts']['store']='unbound'
        with self.assertRaisesRegex(ValueError,'目标店铺未绑定'):self.run_command()
        self.product['facts']['store']='youhealth'
        with self.assertRaisesRegex(ValueError,'确认使用现有'):self.run_command(acknowledgeExecution=False)
        self.enqueued.assert_not_called()


if __name__=='__main__':unittest.main()
