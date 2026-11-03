"""Original source proved pre-save stop; SQLite fixtures, no platform calls."""
import ast
from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NoSaveReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.root = self.state/'runs'/'J'
        (self.root/'reports').mkdir(parents=True)
        self.contract = {'scripts/run_all.cjs':'a'*64, 'SKILL.md':'b'*64,
                         '__workbench_contract_version__':'listing-source-v2',
                         '__workbench__/listing_runner.cjs':'c'*64}
        errors = [{'field':'benefits', 'error':'actual identity not verified'}]
        self.report = {'product_id':'P', 'status':'blocked_critical_transaction_fields',
                       'critical_fill_errors':errors,
                       'save':{'status':'not_saved','button':None,'published':False,
                               'reason':'critical_transaction_fill_failed','errors':errors},
                       'post_save_verification':{'status':'not_run','reason':'critical_transaction_fill_failed'}}
        self.product = {'id':'P','revision':6,'facts':{'store':'fixture'},
                        'attributePlan':{'fingerprint':'fp','skillContract':{}},
                        'visual':{'job':'visual'},'approval':{'hero':'unchanged'},
                        'workflow':{'listingMechanism':'original-skill-v1'}}
        self.product['draft'] = {'job':'J','attempt_id':'J','revision':6,'store':'fixture',
                                'run_directory':str(self.root),'published':None,
                                'reconciliationRequired':True,
                                'evidence':{'reports/run-all-report.json':copy.deepcopy(self.report)},
                                'evidenceErrors':[]}
        self.job = {'id':'J','product':'P','revision':6}
        self.write('reports/run-all-report.json',self.report)
        self.write('listing-context.json',{'product':'P','revision':6,'store':'fixture',
                                          'listingMechanism':'original-skill-v1'})
        self.write('skill-preparation.json',{'revision':6,'status':'READY',
                                           'attributePlanFingerprint':'fp','visualJob':'visual'})
        self.write('skill-contract.json',self.contract)
        self.conn=sqlite3.connect(':memory:');self.conn.row_factory=sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.execute('CREATE TABLE products(id TEXT PRIMARY KEY,data TEXT)')
        @contextmanager
        def db():
            try:yield self.conn;self.conn.commit()
            except BaseException:self.conn.rollback();raise
        self.ns={'__name__':'offline','store':SimpleNamespace(STATE=self.state,db=db,now=lambda:'fixture')}
        tree=ast.parse((ROOT/'listing_adapter.py').read_text(encoding='utf-8-sig'))
        tree.body=[n for n in tree.body if not (isinstance(n,ast.Import) and any(a.name=='task_store' for a in n.names))]
        exec(compile(tree,'listing_adapter.py','exec'),self.ns)
        self.ns['skill_contract']=lambda _:copy.deepcopy(self.contract)
        self.save(self.product)

    def write(self,name,value):
        (self.root/name).write_text(json.dumps(value),encoding='utf-8')

    def save(self,value):
        self.conn.execute('INSERT OR REPLACE INTO products VALUES(?,?)',('P',json.dumps(value)))
        self.conn.commit()

    def current(self):
        return json.loads(self.conn.execute('SELECT data FROM products WHERE id="P"').fetchone()['data'])

    def reconcile(self):
        return self.ns['reconcile_saved'](self.job,self.product,self.root,None)

    def test_exact_pre_save_stop_removes_only_matching_clue_and_preserves_diagnostics(self):
        current=copy.deepcopy(self.product);current['unrelated']='concurrent';self.save(current)
        result=self.reconcile()
        self.assertEqual(result['status'],'no_save_verified')
        self.assertIs(result['reconciliationRequired'],False)
        updated=self.current();history=updated.pop('listingReconciliations')
        self.assertEqual(history[0]['attempt'],self.product['draft'])
        current.pop('draft');self.assertEqual(updated,current)
        self.assertEqual(result['evidence']['reportSha256'],hashlib.sha256((self.root/'reports/run-all-report.json').read_bytes()).hexdigest())

    def test_controller_change_is_allowed_but_vendor_change_is_not(self):
        self.ns['skill_contract']=lambda _:dict(self.contract,**{'__workbench__/listing_runner.cjs':'d'*64})
        self.assertEqual(self.reconcile()['status'],'no_save_verified')
        self.save(self.product)
        self.ns['skill_contract']=lambda _:dict(self.contract,**{'scripts/run_all.cjs':'d'*64})
        with self.assertRaises(ValueError):self.reconcile()
        self.assertEqual(self.current(),self.product)

    def test_ambiguous_or_partial_receipts_never_clear(self):
        variants=[('save',{'status':'saved','button':'Save','published':False}),
                  ('save',{'status':'not_saved','button':None,'published':False}),
                  ('post_save_verification',{'status':'not_run','reason':'timeout'}),
                  ('product_id','other'),('draft_id','123'),('draft_url','https://post.alibaba.com/draft'),
                  ('critical_fill_errors',[])]
        for key,value in variants:
            with self.subTest(key=key,value=value):
                altered=copy.deepcopy(self.report);altered[key]=value
                self.write('reports/run-all-report.json',altered)
                self.product['draft']['evidence']['reports/run-all-report.json']=altered
                self.save(self.product)
                with self.assertRaises((ValueError,FileNotFoundError)):self.reconcile()
                self.assertEqual(self.current(),self.product)

    def test_readback_or_persisted_save_traces_never_clear(self):
        for kind in ('file','persisted','draft_id','history','errors'):
            with self.subTest(kind=kind):
                self.write('reports/run-all-report.json',self.report)
                product=copy.deepcopy(self.product)
                if kind=='file':self.write('readback.json',{})
                elif kind=='persisted':product['draft']['evidence']['readback.json']={}
                elif kind=='draft_id':product['draft']['draft_id']='123'
                elif kind=='history':product['draftHistory']=[{'draft_id':'123'}]
                else:product['draft']['evidenceErrors']=[{'file':'readback.json'}]
                self.save(product)
                with self.assertRaises(ValueError):self.ns['reconcile_saved'](self.job,product,self.root,None)
                self.assertEqual(self.current(),product)
                (self.root/'readback.json').unlink(missing_ok=True)

    def test_changed_scope_or_attempt_cannot_be_cleared(self):
        for kind in ('revision','fingerprint','visual','draft','store','mechanism'):
            with self.subTest(kind=kind):
                current=copy.deepcopy(self.product)
                if kind=='revision':current['revision']=7
                elif kind=='fingerprint':current['attributePlan']['fingerprint']='new'
                elif kind=='visual':current['visual']['job']='new'
                elif kind=='draft':current['draft']['attempt_id']='new'
                elif kind=='store':current['facts']['store']='other'
                else:current['workflow']['listingMechanism']='other'
                self.save(current)
                with self.assertRaises(ValueError):self.reconcile()
                self.assertEqual(self.current(),current)

    def test_changed_context_preparation_or_persisted_report_cannot_clear(self):
        variants=[('listing-context.json',{'product':'other','revision':6,'store':'fixture',
                                          'listingMechanism':'original-skill-v1'}),
                  ('skill-preparation.json',{'revision':6,'status':'READY',
                                            'attributePlanFingerprint':'fp','visualJob':'other'})]
        for name,value in variants:
            with self.subTest(name=name):
                original=(self.root/name).read_text(encoding='utf-8')
                self.write(name,value)
                with self.assertRaises(ValueError):self.reconcile()
                self.assertEqual(self.current(),self.product)
                (self.root/name).write_text(original,encoding='utf-8')
        self.product['draft']['evidence']['reports/run-all-report.json']['product_id']='other'
        self.save(self.product)
        with self.assertRaises(ValueError):self.reconcile()
        self.assertEqual(self.current(),self.product)

    def test_pre_save_error_reports_actual_failure_and_never_claims_post_save(self):
        with self.assertRaisesRegex(ValueError,'保存前阻断.*未保存草稿.*actual identity'):
            self.ns['validate_receipt'](self.report,{},'fixture','123')

    def test_alternative_platform_identity_and_saved_editor_links_remain_uncertain(self):
        traces=[{'itemId':'123'},{'item_id':'123'},{'savedDraftId':'123'},
                {'savedDraftUrl':'https://post.alibaba.com/example'}, {'product_id':'123'},
                {'editor':'https://post.alibaba.com/product/publish.htm?itemId=123'},
                {'editor':'https://i.alibaba.com/product/edit?productId=123'}]
        for trace in traces:
            with self.subTest(trace=trace):
                altered=copy.deepcopy(self.report);altered['additional']=trace
                self.write('reports/run-all-report.json',altered)
                self.product['draft']['evidence']['reports/run-all-report.json']=altered
                self.save(self.product)
                with self.assertRaises(ValueError):self.reconcile()
                self.assertEqual(self.current(),self.product)


if __name__=='__main__':unittest.main()
