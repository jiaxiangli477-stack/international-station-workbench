"""Existing draft refresh is read-only and cannot create another listing."""
import copy
from contextlib import contextmanager
import json
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
import test_listing_no_save_reconcile as fixtures


class SavedDraftRefreshTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.NoSaveReconcileTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.ns=self.f.ns;self.calls=[];self.ready=[]
        self.report={'product_id':'P','status':'completed',
                     'save':{'status':'draft_saved','button':'Save','published':False},
                     'category_routing':{'selected_cat_id':'123'},
                     'post_save_verification':{'status':'verified','resolved_draft_url':
                         'https://post.alibaba.com/product/publish.htm?itemId=456&pubAction=draft'},
                     'images':{'main_count':6,'detail_count':12}}
        self.delivery=[{'slot':slot,'section':'main' if slot.startswith('m') else 'detail','exportHash':'hash-'+slot}
                       for slot in self.ns['SLOTS']]
        self.receipt={'draft_id':'456','draft_url':'https://post.alibaba.com/product/publish.htm?itemId=456&pubAction=draft',
                      'store':'fixture','published':False,'actualAccountVerified':True,'category_id':'123',
                      'fields':{'product_name':{'expected':'Title','actual':'Title','matched':True}},
                      'acceptancePolicy':'original-skill-draft-review','image_review_required':True,
                      'image_readback_verified':False,
                      'image_checks':[dict(row,uploadInvoked=True,reviewRequired=True) for row in self.delivery]}
        original=copy.deepcopy(self.receipt);original['fields']['product_name']['actual']='';original['category_id']=''
        self.f.product['draft'].update(draft_id='456',draft_url=self.receipt['draft_url'])
        self.f.product['draft']['evidence']={'reports/run-all-report.json':copy.deepcopy(self.report),
                                           'readback.json':copy.deepcopy(original)}
        for name,value in [('reports/run-all-report.json',self.report),('readback.json',original),
                           ('listing-preflight.json',{'category':'123'}),('upload-map.json',self.delivery)]:
            self.f.write(name,value)
        self.f.save(self.f.product)
        self.ns['command']=lambda root,skills,mode:[mode]
        self.ns['environment']=lambda:{}
        @contextmanager
        def lock(job):
            self.calls.append(('lock',job));yield
        self.ns['session_lock']=lock
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules,{'listing_browser':SimpleNamespace(ensure_ready=lambda product:self.ready.append(True))}).start()
        patch.object(self.ns['subprocess'],'run',side_effect=self.execute).start()

    def execute(self,args,**kwargs):
        self.calls.append(tuple(args))
        self.f.write('readback-refresh.json',self.receipt)
        self.f.write('readback-refresh-report.json',self.report)
        return SimpleNamespace(returncode=0)

    def refresh(self):
        self.assertTrue(callable(self.ns.get('refresh_saved')),'missing read-only saved-draft refresh')
        return self.ns['refresh_saved'](self.f.job,self.f.product,self.f.root,None)

    def test_refresh_only_calls_readback_and_returns_verified_existing_draft(self):
        before=self.f.current();original=(self.f.root/'readback.json').read_bytes()
        result=self.refresh()
        self.assertEqual(result['status'],'completed');self.assertEqual(result['draft_id'],'456')
        self.assertEqual(result['evidence_file'],'readback-refresh.json')
        self.assertEqual(self.calls,[('lock','J'),('readback',)])
        self.assertEqual(self.ready,[True]);self.assertEqual(self.f.current(),before)
        self.assertEqual((self.f.root/'readback.json').read_bytes(),original)
        target=json.loads((self.f.root/'readback-target.json').read_text(encoding='utf-8'))
        self.assertEqual(target['draft_id'],'456');self.assertEqual(target['product'],'P')

    def test_missing_id_wrong_id_or_other_attempt_never_calls_runner(self):
        for key,value in [('draft_id',''),('draft_id','999'),('attempt_id','other'),('revision',7),
                          ('store','other'),('draft_url','https://example.com/?itemId=456')]:
            with self.subTest(key=key):
                original=copy.deepcopy(self.f.product)
                self.f.product['draft'][key]=value;self.f.save(self.f.product)
                with self.assertRaises(ValueError):self.refresh()
                self.assertFalse(self.calls);self.assertEqual(self.f.current(),self.f.product)
                self.f.product=original

    def test_vendor_change_rejects_but_controller_only_change_can_read(self):
        self.ns['skill_contract']=lambda _:dict(self.f.contract,**{'scripts/run_all.cjs':'e'*64})
        with self.assertRaises(ValueError):self.refresh()
        self.assertFalse(self.calls)
        self.ns['skill_contract']=lambda _:dict(self.f.contract,**{'__workbench__/listing_runner.cjs':'e'*64})
        self.assertEqual(self.refresh()['draft_id'],'456')

    def test_failed_or_wrong_refresh_keeps_draft_and_original_evidence(self):
        for kind in ('failure','wrong_id','wrong_category','missing_title'):
            with self.subTest(kind=kind):
                before=self.f.current()
                def execute(args,**kwargs):
                    receipt=copy.deepcopy(self.receipt)
                    if kind=='wrong_id':receipt['draft_id']='999'
                    elif kind=='wrong_category':receipt['category_id']='999'
                    elif kind=='missing_title':receipt['fields']['product_name']['actual']=''
                    self.f.write('readback-refresh.json',receipt)
                    self.f.write('readback-refresh-report.json',self.report)
                    return SimpleNamespace(returncode=1 if kind=='failure' else 0)
                with patch.object(self.ns['subprocess'],'run',side_effect=execute):
                    with self.assertRaises(ValueError):self.refresh()
                self.assertEqual(self.f.current(),before)

    def test_concurrent_scope_change_prevents_returning_completed(self):
        def execute(args,**kwargs):
            current=self.f.current();current['visual']['job']='different';self.f.save(current)
            return self.execute(args,**kwargs)
        with patch.object(self.ns['subprocess'],'run',side_effect=execute):
            with self.assertRaises(ValueError):self.refresh()
        self.assertTrue(self.f.current()['draft']['reconciliationRequired'])

    def test_stale_refresh_files_cannot_be_reused_as_new_readback(self):
        self.f.write('readback-refresh.json',self.receipt)
        self.f.write('readback-refresh-report.json',self.report)
        before=self.f.current()
        with patch.object(self.ns['subprocess'],'run',return_value=SimpleNamespace(returncode=0)):
            with self.assertRaisesRegex(ValueError,'新证据'):self.refresh()
        self.assertEqual(self.f.current(),before)


if __name__=='__main__':unittest.main()
