"""Preflight visibility CAS uses SQLite memory, never the production store."""
import ast
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]


def load_function(filename,name,namespace):
    tree=ast.parse((ROOT/filename).read_text(encoding='utf-8-sig'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),filename,'exec'),namespace)
    return namespace[name]


class ListingSkillVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.connection=sqlite3.connect(':memory:');self.connection.row_factory=sqlite3.Row
        self.connection.execute('CREATE TABLE products(id TEXT PRIMARY KEY,data TEXT)')
        self.product={'id':'fixture','revision':6,'facts':{'mode':'concept','design':'Original'},
                      'attributePlan':{'fingerprint':'current-fingerprint'},'packaging':{'revision':6},
                      'visual':{'job':'current-visual','revision':6},
                      'workflow':{'listingMechanism':'original-skill-v1','status':'ACTIVE'}}
        self.prepared={'revision':6,'attributePlanFingerprint':'current-fingerprint','visualJob':'current-visual',
                       'status':'BLOCKED','content_preflight':{'blockingDiagnostics':['net_weight is missing']},
                       'pending_requirements':[{'name':'Function','code':'option pending'}],'draftSaved':False}
        @contextmanager
        def db():
            try:yield self.connection;self.connection.commit()
            except BaseException:self.connection.rollback();raise
        self.store=SimpleNamespace(db=db,product=Mock(return_value=self.product),STATE=ROOT/'offline-unused')
        self.save(self.product)
        self.persist=load_function('listing_adapter.py','persist_skill_preparation',{'store':self.store,'json':json})

    def tearDown(self):self.connection.close()

    def save(self,product):
        self.connection.execute('INSERT OR REPLACE INTO products VALUES(?,?)',(product['id'],json.dumps(product)))
        self.connection.commit()

    def current(self):return json.loads(self.connection.execute('SELECT data FROM products').fetchone()['data'])

    def test_blocked_result_is_visible_to_existing_plan_without_overwriting_concurrent_product_data(self):
        current=copy.deepcopy(self.product);current['facts']['design']='Concurrent saved design'
        current['approvedVisual']='approved-existing';self.save(current)
        result=self.persist(self.product,self.prepared)
        self.assertEqual(result['listingSkill'],self.prepared)
        current['listingSkill']=self.prepared;self.assertEqual(self.current(),current)
        self.assertFalse(result['listingSkill']['draftSaved']);self.assertNotIn('draft',result)
        plan=load_function('single_approval_flow.py','plan',{
            'attribute_plan':SimpleNamespace(artifact_matches=lambda *_:True),'packaging_gaps':lambda _:[],
            'hero_scope':lambda _:None,'require_hero':lambda _:None,'visual_gaps':lambda _:[]})
        with patch.dict(sys.modules,{'skill_jobs':SimpleNamespace()}):
            next_step=plan(result,'DRAFT')
        self.assertEqual(next_step['next'],'input')
        self.assertIn('net_weight is missing',next_step['gaps'])
        self.assertTrue(any('Function' in gap for gap in next_step['gaps']))

    def test_changed_revision_attribute_or_visual_cannot_overwrite_new_scope(self):
        for change in ('revision','attribute','visual'):
            with self.subTest(change=change):
                current=copy.deepcopy(self.product);current['listingSkill']={'message':'New scope result'}
                if change=='revision':current['revision']=7
                elif change=='attribute':current['attributePlan']['fingerprint']='new-fingerprint'
                else:current['visual']['job']='new-visual'
                self.save(current)
                with self.assertRaisesRegex(ValueError,'变化'):self.persist(self.product,self.prepared)
                self.assertEqual(self.current(),current)

    def test_ready_preparation_is_diagnostic_only_and_does_not_create_a_draft(self):
        ready=copy.deepcopy(self.prepared)
        ready.update(status='READY',content_preflight={'status':'PASS','blockingDiagnostics':[]},pending_requirements=[])
        before=copy.deepcopy(self.product)
        self.persist(self.product,ready)
        current=self.current();self.assertEqual(current.pop('listingSkill'),ready)
        self.assertEqual(current,before);self.assertFalse(ready['draftSaved'])

    def test_manual_prepare_uses_the_same_persistence_boundary(self):
        persist=Mock(wraps=self.persist)
        adapter=SimpleNamespace(prepare_original_skill=Mock(return_value=self.prepared),persist_skill_preparation=persist)
        command=load_function('operations_api.py','command',{'store':self.store})
        modules={'single_approval_flow':SimpleNamespace(),'listing_adapter':adapter,
                 'project_paths':SimpleNamespace(skill_root=lambda _:Path('offline-skills/attribute'))}
        with patch.dict(sys.modules,modules):
            result=command({'action':'listing.skill.prepare','id':'fixture','revision':6})
        persist.assert_called_once_with(self.product,self.prepared)
        self.assertEqual(result['listingSkill'],self.prepared)


if __name__=='__main__':unittest.main()
