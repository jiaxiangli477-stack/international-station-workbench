"""Offline receipt/lock regressions. All state stays in docs/repair10/R04-sandbox."""
import ast
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import types
import unittest
from unittest.mock import patch
from PIL import Image

BASE = Path(__file__).resolve().parents[2]
SANDBOX = BASE / 'docs/repair10/R04-sandbox'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, BASE/'workbench'/filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.root = SANDBOX/self._testMethodName
        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True)
        self.product = {'id':'p','revision':1}
        self.store = types.SimpleNamespace(ROOT=BASE/'workbench', product=lambda _:self.product)
        self.skills = self.root/'skills'
        templates = self.skills/'b2b-image-skill/assets/templates'
        templates.mkdir(parents=True)
        (templates/'m1.html').write_text('<p>{{NAME}}</p>', encoding='utf-8')
        (templates/'_brand.css').write_text('body{}', encoding='utf-8')
        self.policy = {'templates':{'m1':{'file':'m1.html','sha256':self.hash(templates/'m1.html')}},
                       'brandCssHash':self.hash(templates/'_brand.css')}
        self.binding = {'job':'j','product':'p','revision':1,'attributePlanFingerprint':''}
        self.input = {'id':'p','revision':1,'executionBinding':self.binding}
        (self.root/'input.json').write_text(json.dumps(self.input), encoding='utf-8')
        (self.root/'product.json').write_text('{"spec":"300g"}', encoding='utf-8')
        (self.root/'build').mkdir()
        (self.root/'build/m1.html').write_text('<p>test</p>', encoding='utf-8')
        shutil.copy2(templates/'_brand.css', self.root/'build/_brand.css')
        Image.new('RGB',(1000,1000),'white').save(self.root/'m1.png')
        self.patches = patch.dict(sys.modules, {'task_store':self.store,
            'skill_jobs':types.SimpleNamespace(SKILLS=self.skills, artifact=self.artifact),
            'attribute_plan':types.SimpleNamespace(artifact_matches=lambda p,a: not p.get('attributePlan') or
                a.get('attributePlanFingerprint')==p['attributePlan'].get('fingerprint'))})
        self.patches.start()
        self.runner = load('runner_R04','native_template_runner.py')
        self.native_patch = patch.dict(sys.modules, {'native_template_runner':self.runner})
        self.native_patch.start()
        self.jobs = load('jobs_R04','native_skill_jobs.py')
        (self.root/'template-receipts').mkdir()
        self.receipt = {'slot':'m1','file':'m1.png','html':'build/m1.html','spec':'product.json',
            'imagePixelHash':self.runner.image_hash(self.root/'m1.png'),
            'htmlHash':self.hash(self.root/'build/m1.html'),'specHash':self.hash(self.root/'product.json'),
            'binding':dict(self.binding),'renderer':'installed_render_v2','exitCode':0,'specCheck':'ok'}
        self.write_receipt()

    def tearDown(self):
        self.native_patch.stop()
        self.patches.stop()

    def hash(self,path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def artifact(self,root,path):
        target=(root/path).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file():
            raise ValueError('invalid artifact')
        return target

    def write_receipt(self):
        (self.root/'template-receipts/m1.json').write_text(json.dumps(self.receipt), encoding='utf-8')

    def verify(self):
        return self.jobs.verify(self.root,[{'slot':'m1','file':'m1.png'}],self.policy)

    def test_ok_returns_asset_list(self):
        self.assertEqual(self.verify()[0]['specCheck'],'ok')

    def test_unchecked_retains_explicit_review(self):
        self.receipt['specCheck']='unchecked';self.write_receipt()
        row=self.verify()[0]
        self.assertEqual(row['specCheck'],'unchecked')
        self.assertTrue(row['quality']['reviewRequired'])
        self.assertIn('specification',row['reviewRequirements'])

    def test_bad_rejected(self):
        self.receipt['specCheck']='bad';self.write_receipt()
        with self.assertRaises(ValueError):self.verify()

    def test_not_applicable_preserved(self):
        self.receipt['specCheck']='';self.write_receipt()
        self.assertEqual(self.verify()[0]['specCheck'],'not_applicable')

    def test_spec_change_invalidates_old_receipt(self):
        (self.root/'product.json').write_text('{"spec":"900g"}', encoding='utf-8')
        with self.assertRaises(ValueError):self.verify()

    def test_each_identity_field_invalidates_old_receipt(self):
        for field in self.binding:
            with self.subTest(field=field):
                old=self.receipt['binding'][field]
                self.receipt['binding'][field]='stale';self.write_receipt()
                with self.assertRaises(ValueError):self.verify()
                self.receipt['binding'][field]=old

    def test_legacy_receipt_requires_reverification(self):
        self.receipt.pop('specHash');self.receipt.pop('binding');self.write_receipt()
        with self.assertRaises(ValueError):self.verify()

    def test_policy_identity_blocks_whole_input_receipt_copy(self):
        self.policy['executionBinding']=dict(self.binding,job='actual-other-job')
        with self.assertRaises(ValueError):self.verify()

    def test_current_plan_changed_without_revision_invalidates(self):
        self.product['attributePlan']={'fingerprint':'new'}
        with self.assertRaises(ValueError):self.verify()

    def test_unknown_legacy_lock_gets_recovery_response_without_render(self):
        requests=self.root/'render-requests';requests.mkdir()
        responses=self.root/'render-responses';responses.mkdir()
        (requests/'one.json').write_text('{}')
        (responses/'one.lock').touch()
        with patch.object(self.jobs.subprocess,'run',side_effect=AssertionError('must not render')):
            self.jobs.process_render_requests(self.product,{'id':'j','revision':1},self.root,self.policy)
        reply=json.loads((responses/'one.json').read_text(encoding='utf-8'))
        self.assertTrue(reply['recoveryRequired'])

    def test_normal_completion_releases_owned_lock(self):
        requests=self.root/'render-requests';requests.mkdir()
        (requests/'one.json').write_text('{}')
        self.jobs.process_render_requests(self.product,{'id':'j','revision':1},self.root,self.policy)
        self.assertFalse((self.root/'render-responses/one.lock').exists())

    def test_other_module_completion_keeps_current_receipt(self):
        self.receipt['specDependencyHash']=self.runner.spec_dependency_hash(self.root/'product.json','m1')
        self.write_receipt()
        (self.root/'product.json').write_text('{"spec":"300g","m2":{"text":"later"}}',encoding='utf-8')
        self.assertEqual(self.verify()[0]['specCheck'],'ok')

    def test_own_module_or_source_asset_change_invalidates(self):
        (self.root/'product.json').write_text('{"product":{"image":"source.png"},"m1":{"text":"old"}}',encoding='utf-8')
        (self.root/'source.png').write_bytes(b'original')
        self.receipt['specDependencyHash']=self.runner.spec_dependency_hash(self.root/'product.json','m1')
        self.write_receipt()
        (self.root/'source.png').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.verify()

    def lock_fixture(self,phase):
        requests=self.root/'render-requests';requests.mkdir()
        responses=self.root/'render-responses';responses.mkdir()
        request=requests/'one.json'
        request.write_text('{"modules":["m1"]}',encoding='utf-8')
        lock=responses/'one.lock'
        lock.write_text(json.dumps({'pid':123,'token':'old','job':'j','phase':phase,
                                   'requestHash':self.hash(request)}),encoding='utf-8')
        return request,responses/'one.json',lock

    def acquire(self,parts):
        request,response,lock=parts
        return self.jobs.acquire_render_lock(lock,response,request,self.product,{'id':'j','revision':1},self.root,self.policy)

    def test_confirmed_dead_before_launch_can_be_safely_claimed(self):
        parts=self.lock_fixture('claimed')
        with patch.object(self.jobs,'render_owner_alive',return_value=False),patch.object(self.jobs,'publish_receipts',return_value=[]):
            owner=self.acquire(parts)
        self.assertEqual(owner['pid'],os.getpid())
        self.assertNotEqual(owner['token'],'old')
        self.jobs.release_render_lock(parts[2],owner)
        self.assertFalse(parts[2].exists())

    def test_confirmed_dead_after_completion_reuses_receipts(self):
        parts=self.lock_fixture('rendering')
        with patch.object(self.jobs,'render_owner_alive',return_value=False),patch.object(self.jobs,'publish_receipts',return_value=[{'slot':'m1'}]):
            self.assertIsNone(self.acquire(parts))
        self.assertEqual(json.loads(parts[1].read_text())['status'],'COMPLETED')

    def test_dead_render_unknown_result_does_not_rerender(self):
        parts=self.lock_fixture('rendering')
        with patch.object(self.jobs,'render_owner_alive',return_value=False),patch.object(self.jobs,'publish_receipts',return_value=[]):
            self.assertIsNone(self.acquire(parts))
        self.assertTrue(json.loads(parts[1].read_text(encoding='utf-8'))['recoveryRequired'])

    def test_live_owner_is_untouched(self):
        parts=self.lock_fixture('rendering')
        with patch.object(self.jobs,'render_owner_alive',return_value=True):
            self.assertIsNone(self.acquire(parts))
        self.assertFalse(parts[1].exists())
        self.assertEqual(json.loads(parts[2].read_text())['token'],'old')

    def test_write_failure_still_releases_owned_lock(self):
        requests=self.root/'render-requests';requests.mkdir()
        (requests/'one.json').write_text('{}')
        original=Path.write_text
        def write(path,*args,**kwargs):
            if path.parent.name=='render-responses' and path.name=='one.json':raise OSError('mock disk')
            return original(path,*args,**kwargs)
        with patch.object(Path,'write_text',write),self.assertRaises(OSError):
            self.jobs.process_render_requests(self.product,{'id':'j','revision':1},self.root,self.policy)
        self.assertFalse((self.root/'render-responses/one.lock').exists())

    def process_module(self,process):
        tree=ast.parse((BASE/'workbench/native_template_runner.py').read_text(encoding='utf-8'))
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        function=next(n for n in main.body if isinstance(n,ast.FunctionDef) and n.name=='process_module')
        env=dict(self.runner.__dict__,root=self.root,binding=self.binding,spec_file=self.root/'product.json',
                 spec_hash=self.hash(self.root/'product.json'),process=process)
        exec(compile(ast.Module(body=[function],type_ignores=[]),'R04-process-module','exec'),env)
        return env['process_module']('m1',0,{},self.root,self.root/'build',self.root)

    def test_renderer_cannot_stamp_later_input_over_actual_input(self):
        def process(*args,**kwargs):
            changed=dict(self.input,executionBinding=dict(self.binding,job='later'))
            (self.root/'input.json').write_text(json.dumps(changed),encoding='utf-8')
            return 'm1','',True,False,False,'',[],'ok',''
        with self.assertRaises(ValueError):self.process_module(process)
        self.assertFalse((self.root/'template-receipts/m1.json').exists())

    def test_correct_module_reused_without_render(self):
        self.receipt['specDependencyHash']=self.runner.spec_dependency_hash(self.root/'product.json','m1')
        self.write_receipt()
        process=lambda *a,**k: self.fail('correct module must not be re-rendered')
        self.assertTrue(self.process_module(process)[2])

    def test_renderer_writes_actual_input_hash_and_unchecked_state(self):
        self.process_module(lambda *a,**k:('m1','',True,False,False,'',[],'unchecked',''))
        receipt=json.loads((self.root/'template-receipts/m1.json').read_text(encoding='utf-8'))
        self.assertEqual(receipt['specHash'],self.hash(self.root/'product.json'))
        self.assertEqual(receipt['binding'],self.binding)
        self.assertEqual(receipt['specCheck'],'unchecked')
        self.assertTrue(self.verify()[0]['quality']['reviewRequired'])

    def test_renderer_bad_never_writes_success_receipt(self):
        self.process_module(lambda *a,**k:('m1','',True,False,False,'',[],'bad',''))
        self.assertFalse((self.root/'template-receipts/m1.json').exists())

    def test_spec_changed_during_render_cannot_get_new_receipt(self):
        def process(*a,**k):
            (self.root/'product.json').write_text('{"spec":"900g"}',encoding='utf-8')
            return 'm1','',True,False,False,'',[],'ok',''
        with self.assertRaises(ValueError):self.process_module(process)
        self.assertFalse((self.root/'template-receipts/m1.json').exists())

    def test_timeout_and_lost_response_cannot_repeat_render(self):
        requests=self.root/'render-requests';requests.mkdir()
        request={'modules':['m1'],'spec':'product.json','build':'build'}
        (requests/'one.json').write_text(json.dumps(request),encoding='utf-8')
        with patch.object(self.jobs.subprocess,'run',side_effect=self.jobs.subprocess.TimeoutExpired('mock',1)) as run:
            self.jobs.process_render_requests(self.product,{'id':'j','revision':1},self.root,self.policy)
            self.assertEqual(run.call_count,1)
        responses=self.root/'render-responses'
        self.assertFalse((responses/'one.lock').exists())
        self.assertTrue((responses/'one.uncertain').exists())
        (responses/'one.json').unlink()
        (requests/'two.json').write_text(json.dumps(request),encoding='utf-8')
        with patch.object(self.jobs.subprocess,'run',side_effect=AssertionError('do not repeat')),patch.object(self.jobs,'publish_receipts',return_value=[]):
            self.jobs.process_render_requests(self.product,{'id':'j','revision':1},self.root,self.policy)
        self.assertTrue(json.loads((responses/'one.json').read_text(encoding='utf-8'))['recoveryRequired'])

    def test_partial_saves_qc_and_attribute_fingerprint(self):
        self.product['events']=[]
        self.receipt['specCheck']='unchecked';self.write_receipt()
        class Connection:
            saved=None
            def execute(connection,sql,parameters=()):
                if sql.startswith('UPDATE'):connection.saved=json.loads(parameters[0])
                return connection
            def fetchone(connection):return {'data':json.dumps(self.product)}
        connection=Connection()
        self.store.db=lambda:contextlib.nullcontext(connection)
        self.store.now=lambda:'now'
        self.store.job_update=lambda *a,**k:None
        self.jobs.save_partial(self.product,{'id':'j','revision':1},self.root,
                               {'images':[{'slot':'m1','file':'m1.png'}]},self.policy)
        asset=connection.saved['visualPartial']
        self.assertIn('attributePlanFingerprint',asset)
        self.assertTrue(asset['images'][0]['quality']['reviewRequired'])

    def test_pending_cache_from_old_attribute_input_is_not_promoted(self):
        (self.root/'template-receipts/m1.json').unlink()
        for folder in ('native-cache','native-requests','build/v2'):
            (self.root/folder).mkdir(parents=True,exist_ok=True)
        row={'slot':'m1','scenePixelHash':'s','productPixelHash':'p','subject':'x','image':'m1.png',
             'imagePixelHash':self.runner.image_hash(self.root/'m1.png')}
        for folder in ('native-cache','native-requests'):
            (self.root/folder/'m1.json').write_text(json.dumps(row),encoding='utf-8')
        shutil.copy2(self.root/'m1.png',self.root/'build/v2/m1_fit.png')
        os.utime(self.root/'build/v2/m1_fit.png',None)
        self.assertEqual(self.jobs.save_pending_images(self.product,{'id':'j','revision':1},self.root),[])

    def test_pending_saves_bound_attribute_fingerprint_and_review(self):
        (self.root/'template-receipts/m1.json').unlink()
        self.product['attributePlan']={'fingerprint':'current'}
        self.binding['attributePlanFingerprint']='current'
        self.input['attributePlan']=self.product['attributePlan']
        (self.root/'input.json').write_text(json.dumps(self.input),encoding='utf-8')
        for folder in ('native-cache','native-requests','build/v2'):
            (self.root/folder).mkdir(parents=True,exist_ok=True)
        row={'slot':'m1','scenePixelHash':'s','productPixelHash':'p','subject':'x','image':'m1.png',
             'binding':self.binding,'imagePixelHash':self.runner.image_hash(self.root/'m1.png')}
        for folder in ('native-cache','native-requests'):
            (self.root/folder/'m1.json').write_text(json.dumps(row),encoding='utf-8')
        shutil.copy2(self.root/'m1.png',self.root/'build/v2/m1_fit.png')
        os.utime(self.root/'build/v2/m1_fit.png',None)
        class Connection:
            saved=None
            def execute(connection,sql,parameters=()):
                if sql.startswith('UPDATE'):connection.saved=json.loads(parameters[0])
                return connection
            def fetchone(connection):return {'data':json.dumps(self.product)}
        connection=Connection()
        self.store.db=lambda:contextlib.nullcontext(connection)
        images=self.jobs.save_pending_images(self.product,{'id':'j','revision':1},self.root)
        self.assertEqual(images[0]['attributePlanFingerprint'],'current')
        self.assertEqual(connection.saved['visualPending']['attributePlanFingerprint'],'current')
        self.assertTrue(images[0]['quality']['reviewRequired'])


if __name__=='__main__':
    unittest.main(verbosity=2)
