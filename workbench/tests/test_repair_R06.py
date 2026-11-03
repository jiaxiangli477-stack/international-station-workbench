"""Offline listing recovery regression: no application imports or external calls."""
import ast
from contextlib import contextmanager, nullcontext
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[2]
SANDBOX = BASE / 'docs/repair10/R06-sandbox'

class RecoveryTests(unittest.TestCase):
    def test_uncertain_execution_blocks_second_save_and_keeps_clues(self):
        for failure in ('timeout', 'identity', 'missing', 'malformed'):
            with self.subTest(failure=failure):
                root = SANDBOX / failure
                root.mkdir(parents=True, exist_ok=True)
                for file in (root/'readback.json', root/'reports/run-all-report.json'):
                    if file.exists(): file.unlink()
                conn = sqlite3.connect(':memory:'); conn.row_factory = sqlite3.Row
                conn.execute('CREATE TABLE products(id TEXT PRIMARY KEY, data TEXT)')
                @contextmanager
                def db():
                    with conn: yield conn
                product = {'id':'P', 'revision':1, 'facts':{'store':'fixture'}, 'attributePlan':{'manifest':{}, 'skillContract':{}}}
                conn.execute('INSERT INTO products VALUES(?,?)', ('P',json.dumps(product))); conn.commit()
                def current(): return json.loads(conn.execute('SELECT data FROM products').fetchone()['data'])
                calls = []; updates = []
                def execute(args, **kwargs):
                    if args[0] == 'preflight':
                        (root/'listing-preflight.json').write_text('{"category":"123"}',encoding='utf-8')
                        return SimpleNamespace(returncode=0)
                    calls.append('save')
                    # The marker must exist BEFORE any possible remote side effect.
                    self.assertTrue(current().get('draft',{}).get('reconciliationRequired'))
                    if failure != 'missing':
                        (root/'readback.json').write_text('{bad' if failure=='malformed' else '{"draft_id":"saved"}',encoding='utf-8')
                    if failure in ('timeout','malformed'): raise subprocess.TimeoutExpired('fixture',1)
                    return SimpleNamespace(returncode=0)
                identities = [0]
                def identity(*args):
                    identities[0] += 1
                    if failure=='identity' and identities[0]>1: raise ValueError('identity mismatch')
                modules = {name:ModuleType(name) for name in ('attribute_plan','bridge_catalog','weekly_update','topic_workflow')}
                modules['attribute_plan'].blockers=lambda p:[]
                modules['bridge_catalog'].current_bridge=lambda:'fixture'
                modules['weekly_update'].STORES={'fixture':{'expected_id':'fixture'}}
                modules['weekly_update'].require_identity=identity
                modules['topic_workflow'].handoff=lambda p:None
                env={'__name__':'fixture','store':SimpleNamespace(db=db, now=lambda:'fixture', job_update=lambda *a,**k:updates.append(k))}
                tree=ast.parse((BASE/'workbench/listing_adapter.py').read_text(encoding='utf-8-sig'))
                tree.body=[n for n in tree.body if not (isinstance(n,ast.Import) and any(a.name=='task_store' for a in n.names))]
                exec(compile(tree,'listing_adapter.py','exec'),env)
                env.update(skill_contract=lambda s:{}, export_images=lambda *a:[], session_lock=lambda j:nullcontext(),command=lambda r,s,m:[m])
                with patch.dict(sys.modules,modules),patch.object(env['subprocess'],'run',side_effect=execute):
                    with self.assertRaises((subprocess.TimeoutExpired,ValueError)):
                        env['run']({'id':'J','revision':1},product,root,None)
                    clue=current()['draft']
                    self.assertTrue(clue['reconciliationRequired'])
                    if failure in ('timeout','identity'): self.assertEqual(clue['draft_id'],'saved')
                    if failure=='malformed': self.assertTrue(clue['evidenceErrors'])
                    with self.assertRaises(ValueError): env['run']({'id':'J2','revision':1},current(),root,None)
                self.assertEqual(calls,['save'])
                self.assertTrue(any(row.get('recoveryRequired') for row in updates))
                conn.close()

    def test_19_images_need_file_asset_section_order_and_reconcile_never_saves(self):
        env={'__name__':'fixture'}
        tree=ast.parse((BASE/'workbench/listing_adapter.py').read_text(encoding='utf-8-sig'))
        tree.body=[n for n in tree.body if not (isinstance(n,ast.Import) and any(a.name=='task_store' for a in n.names))]
        exec(compile(tree,'listing_adapter.py','exec'),env)
        positions={}; images=[]; delivery=[]
        for slot in env['SLOTS']:
            section='parameters' if slot=='m7' else 'main' if slot.startswith('m') else 'detail'
            index=positions.get(section,0); positions[section]=index+1
            images.append({'slot':slot,'section':section,'index':index,'actual':'https://cdn.test/'+slot,
                'assetId':slot,'expectedAssetId':slot,'evidenceVersion':1,'exportHash':'hash-'+slot,
                'uploaded':True,'matched':True})
            delivery.append({'slot':slot,'exportHash':'hash-'+slot})
        report={'status':'completed','post_save_verification':{'status':'verified'},'category_routing':{'selected_cat_id':'123'}}
        receipt={'draft_id':'draft','draft_url':'https://post.alibaba.com/p?itemId=draft','published':False,
            'store':'fixture','actualAccountVerified':True,'category_id':'123',
            'fields':{'title':{'actual':'Test','matched':True}},'image_checks':images}
        self.assertTrue(env['validate_receipt'](report,receipt,'fixture','123',delivery))
        for field,value in [('evidenceVersion',None),('section','detail'),('index',1),('expectedAssetId','wrong'),('exportHash','wrong')]:
            invalid=json.loads(json.dumps(receipt)); invalid['image_checks'][0][field]=value
            with self.assertRaises(ValueError): env['validate_receipt'](report,invalid,'fixture','123',delivery)
        root=SANDBOX/'reconcile'; (root/'reports').mkdir(parents=True,exist_ok=True)
        for file,data in [('reports/run-all-report.json',report),('readback.json',receipt),('upload-map.json',delivery),('listing-preflight.json',{'category':'123'})]:
            (root/file).write_text(json.dumps(data),encoding='utf-8')
        product={'draft':{'attempt_id':'J','run_directory':str(root)},'attributePlan':{'skillContract':{}},'facts':{'store':'fixture'}}
        env['skill_contract']=lambda _:{}
        with patch.object(env['subprocess'],'run',side_effect=AssertionError('no executor in reconciliation')):
            result=env['reconcile_saved']({'id':'J'},product,root,None)
        self.assertTrue(result['reconciliationRequired'])
        self.assertEqual(result['status'],'evidence_validated')

if __name__=='__main__': unittest.main()
