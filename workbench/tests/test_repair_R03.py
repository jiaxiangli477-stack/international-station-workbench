"""Offline executor/workflow regressions; all files remain in the D-drive sandbox."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import task_store as store
import operations_api as api
import skill_jobs
import packaging_image_runner as runner
import packaging_design

SANDBOX = Path(__file__).resolve().parents[2] / 'docs/repair10/R03-sandbox'
SANDBOX.mkdir(parents=True, exist_ok=True)


class ExecutorRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=SANDBOX)
        self.root = Path(self.temp.name)
        self.paths = patch.multiple(store, STATE=self.root, DB=self.root/'db.sqlite')
        self.paths.start()
        self.executors=patch.object(skill_jobs,'_unconfirmed_executors',set(),create=True)
        self.executors.start()

    def tearDown(self):
        self.paths.stop()
        self.executors.stop()
        self.temp.cleanup()

    def product(self, status='NEEDS_ATTENTION'):
        p = store.create_product('fixture', 'Fixture', facts={'mode':'concept','market':'INTERNAL_B2B','form':'Powder','design':'Fixture'})
        p['workflow'] = {'revision':1,'status':status,'imageProvider':'codex-native'}
        store.save_product(p)
        return p

    def job(self, p):
        return store.enqueue('visual', 'product:'+p['id'], {'product':p['id'],'revision':1,'imageProvider':'codex-native','workflowContinuation':True})

    def test_resume_updates_new_workflow_in_same_transaction(self):
        p=self.product(); j=self.job(p); store.job_update(j['id'], status='NEEDS_ATTENTION')
        with patch.object(api.production_flow,'process_alive',return_value=False), patch.object(skill_jobs,'missing',return_value=[]), patch('native_skill_jobs.session',return_value='fixture-session'):
            api.command({'action':'job.resume-native','id':j['id'],'revision':1,'acknowledgeExecution':True})
        current=store.product(p['id'])
        self.assertEqual(current['workflow']['status'],'ACTIVE')
        self.assertEqual(current['workflow']['job'],j['id'])
        self.assertNotIn('selectionFlow',current)

    def test_resume_rollback_leaves_job_unqueued_if_product_update_fails(self):
        p=self.product(); j=self.job(p); store.job_update(j['id'], status='NEEDS_ATTENTION')
        with store.db() as c:
            c.execute("CREATE TRIGGER reject_update BEFORE UPDATE ON products BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with patch.object(api.production_flow,'process_alive',return_value=False), patch.object(skill_jobs,'missing',return_value=[]), patch('native_skill_jobs.session',return_value='fixture-session'):
            with self.assertRaises(Exception):api.command({'action':'job.resume-native','id':j['id'],'revision':1,'acknowledgeExecution':True})
        self.assertEqual(store.records('jobs')[0]['status'],'NEEDS_ATTENTION')

    def test_resume_does_not_restart_stopped_workflow(self):
        p=self.product('STOPPED'); j=self.job(p); store.job_update(j['id'], status='NEEDS_ATTENTION')
        with patch.object(api.production_flow,'process_alive',return_value=False), patch.object(skill_jobs,'missing',return_value=[]), patch('native_skill_jobs.session',return_value='fixture-session'):
            api.command({'action':'job.resume-native','id':j['id'],'revision':1,'acknowledgeExecution':True})
        self.assertEqual(store.product(p['id'])['workflow']['status'],'STOPPED')

    def test_advance_failure_preserves_success_and_result(self):
        p=self.product('ACTIVE');j=self.job(p)
        with patch.object(skill_jobs,'run',return_value={'verified':True}), patch.object(api.production_flow,'advance',side_effect=ValueError('fixture downstream')), patch.object(api,'kick'):
            api.worker()
        current=store.records('jobs')[0]
        self.assertEqual(current['status'],'SUCCESS')
        self.assertEqual(current['result'],{'verified':True})
        self.assertTrue(current['orchestrationError'])

    def test_unconfirmed_executor_blocks_queue(self):
        p=self.product();j=self.job(p)
        store.job_update(j['id'],status='NEEDS_ATTENTION',executorStillRunning=True,recoveryRequired=True)
        other=store.enqueue('visual','other',{'revision':1})
        with patch.object(skill_jobs,'run') as run,patch.object(api,'kick'):
            api.worker()
        run.assert_not_called()
        self.assertEqual(next(x for x in store.records('jobs') if x['id']==other['id'])['status'],'QUEUED')

    def test_bridge_exception_reaps_child(self):
        p=self.product('ACTIVE');j=self.job(p)
        child=MagicMock();child.pid=987654;child.poll.return_value=None
        child.communicate.side_effect=subprocess.TimeoutExpired('fixture',5)
        with patch.object(skill_jobs,'missing',return_value=[]),patch.object(skill_jobs.shutil,'which',return_value='fixture-codex'),patch.object(skill_jobs.subprocess,'Popen',return_value=child),patch.object(skill_jobs.subprocess,'run',return_value=types.SimpleNamespace(returncode=0)),patch('native_skill_jobs.contract',return_value={}),patch('native_skill_jobs.process_render_requests',side_effect=ValueError('fixture bridge')),patch('topic_workflow.handoff',return_value=None):
            with self.assertRaises(ValueError):skill_jobs.run(j)
        child.wait.assert_called()

    def test_cleanup_failure_sets_recovery_flags(self):
        p=self.product();j=self.job(p);child=MagicMock();child.pid=987654;child.poll.return_value=None
        child.communicate.side_effect=subprocess.TimeoutExpired('fixture',5)
        child.wait.side_effect=subprocess.TimeoutExpired('fixture',5)
        with patch.object(skill_jobs,'missing',return_value=[]),patch.object(skill_jobs.shutil,'which',return_value='fixture-codex'),patch.object(skill_jobs.subprocess,'Popen',return_value=child),patch.object(skill_jobs.subprocess,'run',side_effect=OSError('fixture taskkill')),patch('native_skill_jobs.contract',return_value={}),patch('native_skill_jobs.process_render_requests',side_effect=ValueError('fixture bridge')),patch('topic_workflow.handoff',return_value=None):
            with self.assertRaises(ValueError):skill_jobs.run(j)
        current=store.records('jobs')[0]
        self.assertTrue(current.get('executorStillRunning'))
        self.assertTrue(current.get('recoveryRequired'))

    def test_approve_rejects_old_attribute_fingerprint(self):
        p=self.product();p['attributePlan']={'fingerprint':'new','revision':1}
        p['packaging']={'job':'old','revision':1,'attributePlanFingerprint':'old'};store.save_product(p)
        with self.assertRaises(ValueError):api.command({'action':'product.approve','id':p['id'],'phase':'packaging','revision':1,'artifactJob':'old'})

    def test_specification_unchecked_requires_explicit_review(self):
        p=self.product();p['visual']={'job':'visual','revision':1,'images':[{'specCheck':'unchecked','slot':'m1'}]};store.save_product(p)
        with self.assertRaises(ValueError):api.command({'action':'product.approve','id':p['id'],'phase':'visual','revision':1,'artifactJob':'visual'})
        with patch.object(api.production_flow,'advance'):
            out=api.command({'action':'product.approve','id':p['id'],'phase':'visual','revision':1,'artifactJob':'visual','specificationReviewed':True})
        self.assertEqual(out['approvedVisual'],'visual')

    def test_non_native_reconcile_requires_template_receipts(self):
        p=self.product();j=self.job(p);store.job_update(j['id'],status='NEEDS_ATTENTION',imageProvider='configured')
        root=self.root/'runs'/j['id'];root.mkdir(parents=True);(root/'result.json').write_text('{"status":"completed"}')
        with patch.object(api.production_flow,'process_alive',return_value=False),patch.object(skill_jobs,'validate_result',return_value=[]),patch('native_skill_jobs.contract',return_value={}),patch('native_skill_jobs.verify',side_effect=ValueError('missing receipts')) as verify:
            with self.assertRaises(ValueError):api.command({'action':'job.reconcile-output','id':j['id']})
        verify.assert_called_once()

    def test_system_exit_errors_get_safe_structured_receipt(self):
        cases=[('HTTP 429 token=secret','RATE_LIMITED'),('HTTP 503 token=secret','UPSTREAM_TEMPORARY'),('图已生成但下载失败 https://host/?token=secret','GENERATED_DOWNLOAD_FAILED'),('unknown secret','UNKNOWN')]
        for message,reason in cases:
            fake=types.SimpleNamespace(main=MagicMock(side_effect=SystemExit(message)))
            out=self.root/'images/packaging.png';out.parent.mkdir(exist_ok=True)
            with patch.dict(sys.modules,{'gen_image':fake}),patch.object(sys,'argv',['runner','configured','--raw','fixture','-o',str(out)]):
                with self.assertRaises(SystemExit):runner.main()
            receipt=json.loads((self.root/'image-error.json').read_text())
            self.assertEqual(receipt['reason'],reason)
            self.assertNotIn('secret',json.dumps(receipt))
            self.assertFalse(receipt['retryAllowed'])
            fake.main.assert_called_once()

    def test_generated_download_uncertainty_blocks_new_packaging_job(self):
        p=self.product();j=self.job(p)
        store.job_update(j['id'],kind='packaging',status='NEEDS_ATTENTION',recoveryRequired=True,imageError={'reason':'GENERATED_DOWNLOAD_FAILED'})
        with patch.object(skill_jobs,'capability',return_value={'available':True}),patch.object(skill_jobs,'missing',return_value=[]):
            with self.assertRaises(ValueError):api.command({'action':'product.run','id':p['id'],'revision':1,'kind':'packaging','acknowledgeExecution':True})
        with self.assertRaises(ValueError):packaging_design.approve({'id':p['id'],'revision':1,'text':'approved input text '*5,'acknowledgeExecution':True,'imageProvider':'configured'})
        self.assertEqual(len(store.records('jobs')),1)

    def test_system_exit_forbidden_and_quota_categories(self):
        cases=[('HTTP 403 secret','HTTP_403'),('insufficient_quota secret','INSUFFICIENT_QUOTA'),('group disabled secret','GROUP_DISABLED')]
        for message,reason in cases:
            fake=types.SimpleNamespace(main=MagicMock(side_effect=SystemExit(message)))
            out=self.root/'images/packaging.png';out.parent.mkdir(exist_ok=True)
            with patch.dict(sys.modules,{'gen_image':fake}),patch.object(sys,'argv',['runner','configured','-o',str(out)]):
                with self.assertRaises(SystemExit):runner.main()
            self.assertEqual(json.loads((self.root/'image-error.json').read_text())['reason'],reason)

    def test_timeout_uses_tree_stop_and_wait(self):
        p=self.product();j=self.job(p)
        child=MagicMock();child.pid=987654;child.communicate.side_effect=subprocess.TimeoutExpired('fixture',10800)
        with patch.object(skill_jobs,'missing',return_value=[]),patch.object(skill_jobs.shutil,'which',return_value='fixture-codex'),patch.object(skill_jobs.subprocess,'Popen',return_value=child),patch.object(skill_jobs.subprocess,'run',return_value=types.SimpleNamespace(returncode=0)) as stop,patch('topic_workflow.handoff',return_value=None):
            with self.assertRaises(ValueError):skill_jobs.run(dict(j,imageProvider='configured',kind='packaging'))
        self.assertEqual(stop.call_args.args[0],['taskkill','/PID',str(child.pid),'/T','/F'])
        child.wait.assert_called_once()

    def test_non_native_full_run_uses_template_verifier(self):
        p=self.product();j=self.job(p);child=MagicMock();child.pid=987654;child.returncode=0
        root=self.root/'runs'/j['id'];root.mkdir(parents=True);(root/'result.json').write_text('{"status":"completed"}')
        with patch.object(skill_jobs,'missing',return_value=[]),patch.object(skill_jobs.shutil,'which',return_value='fixture-codex'),patch.object(skill_jobs.subprocess,'Popen',return_value=child),patch('native_skill_jobs.contract',return_value={}),patch('native_skill_jobs.verify',side_effect=ValueError('fixture no receipts')) as verify,patch.object(skill_jobs,'validate_result',return_value=[]),patch('topic_workflow.handoff',return_value=None):
            with self.assertRaises(ValueError):skill_jobs.run(dict(j,imageProvider='configured'))
        verify.assert_called_once()
        self.assertIsNone(store.product(p['id'])['visual'])

    def test_images_only_target_cannot_use_legacy_listing_entry(self):
        p=self.product('VISUALS_READY')
        p['facts']['store']='youhealth';p['workflow']['target']='VISUALS';store.save_product(p)
        with patch.object(skill_jobs,'missing',return_value=[]),patch.object(skill_jobs,'capability',return_value={'available':True}):
            with self.assertRaisesRegex(ValueError,'仅图片'):
                api.command({'action':'product.run','id':p['id'],'revision':1,'kind':'listing','acknowledgeExecution':True})
            with self.assertRaisesRegex(ValueError,'仅图片'):
                skill_jobs.run({'id':'fake','product':p['id'],'revision':1,'kind':'listing'})
        self.assertEqual(store.records('jobs'),[])

    def test_listing_reconcile_keeps_unknown_result_and_calls_safe_contract(self):
        import listing_adapter
        p=self.product('NEEDS_ATTENTION')
        p['facts']['store']='youhealth';store.save_product(p)
        j=store.enqueue('listing','product:'+p['id'],{'product':p['id'],'revision':1})
        store.job_update(j['id'],status='NEEDS_ATTENTION',recoveryRequired=True)
        root=self.root/'runs'/j['id'];root.mkdir(parents=True)
        (root/'reports').mkdir()
        for name,data in [('reports/run-all-report.json',{}),('readback.json',{}),('listing-preflight.json',{'category':'mock'})]:
            (root/name).write_text(json.dumps(data))
        result={'status':'evidence_validated','reconciliationRequired':True}
        with patch.object(api.production_flow,'process_alive',return_value=False),patch.object(listing_adapter,'reconcile_saved',return_value=result) as safe,patch.object(listing_adapter,'validate_receipt'),patch.object(store,'commit_output') as commit:
            api.command({'action':'job.reconcile-output','id':j['id']})
        safe.assert_called_once();commit.assert_not_called()
        current=store.records('jobs')[0]
        self.assertEqual(current['status'],'NEEDS_ATTENTION');self.assertTrue(current['recoveryRequired'])

    def test_cleanup_uncertainty_blocks_even_when_database_write_fails(self):
        p=self.product();j=self.job(p);child=MagicMock();child.pid=987654
        child.wait.side_effect=subprocess.TimeoutExpired('fixture',5)
        with patch.object(skill_jobs.subprocess,'run',side_effect=OSError('fixture kill failure')),patch.object(store,'job_update',side_effect=OSError('fixture database')):
            with self.assertRaises(OSError):skill_jobs.stop_executor(child,j)
        try:self.assertTrue(skill_jobs.executor_blocked())
        finally:
            if hasattr(skill_jobs,'_unconfirmed_executors'):skill_jobs._unconfirmed_executors.clear()

    def test_listing_reconcile_only_releases_the_explicit_verified_no_save_outcome(self):
        import listing_adapter
        for result,recovery in [({'status':'no_save_verified','reconciliationRequired':False},False),
                                ({'status':'evidence_validated','reconciliationRequired':False},True)]:
            with self.subTest(outcome=result['status']):
                p=self.product();j=store.enqueue('listing','product:'+p['id'],{'product':p['id'],'revision':1})
                store.job_update(j['id'],status='NEEDS_ATTENTION',recoveryRequired=True)
                with patch.object(api.production_flow,'process_alive',return_value=False), \
                     patch.object(listing_adapter,'reconcile_saved',return_value=result), \
                     patch.object(api.production_flow,'advance') as advance:
                    api.command({'action':'job.reconcile-output','id':j['id']})
                current=next(row for row in store.records('jobs') if row['id']==j['id'])
                self.assertEqual(current['status'],'NEEDS_ATTENTION')
                self.assertEqual(current['recoveryRequired'],recovery)
                self.assertEqual(current.get('reconciliation'),result)
                advance.assert_not_called()

    def test_explicit_saved_draft_readback_commits_the_existing_draft_without_rerunning_listing(self):
        import listing_adapter
        p=self.product();j=store.enqueue('listing','product:'+p['id'],{'product':p['id'],'revision':1})
        p['draft']={'draft_id':'123','attempt_id':j['id']};store.save_product(p)
        store.job_update(j['id'],status='NEEDS_ATTENTION',recoveryRequired=True)
        result={'status':'completed','draft_id':'123','draft_url':'https://post.alibaba.com/product/publish.htm?itemId=123',
                'readback_verified':True,'published':False,'image_review_required':True}
        with patch.object(api.production_flow,'process_alive',return_value=False), \
             patch.object(listing_adapter,'refresh_saved',return_value=result,create=True) as refresh, \
             patch.object(listing_adapter,'reconcile_saved') as local, \
             patch.object(api.production_flow,'advance') as advance:
            api.command({'action':'job.reconcile-output','id':j['id'],'refreshSavedDraft':True})
        refresh.assert_called_once();local.assert_not_called();advance.assert_not_called()
        current=store.product(p['id']);job=next(row for row in store.records('jobs') if row['id']==j['id'])
        self.assertEqual(current['draft']['draft_id'],'123');self.assertTrue(current['draft']['readback_verified'])
        self.assertEqual(current['stage'],'DRAFT_REVIEW');self.assertEqual(current['workflow']['status'],'DRAFT_SAVED')
        self.assertEqual(job['status'],'SUCCESS');self.assertFalse(job['recoveryRequired'])


if __name__=='__main__':unittest.main()
