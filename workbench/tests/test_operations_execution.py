from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import task_store as store
import operations_api as api
import skill_jobs

class OperationsExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.old=(store.DB,store.STATE)
        store.STATE=self.root;store.DB=self.root/'test.sqlite'
    def tearDown(self):
        store.DB,store.STATE=self.old
        self.temp.cleanup()
    def test_date_ranges_exclude_today_and_monday_is_not_invalid_previous_week(self):
        with self.assertRaises(ValueError):store.period('last7',today=date(2026,10,16))
        self.assertEqual(store.period('previous_week',today=date(2026,10,16)),{'start':'2026-10-05','end':'2026-10-11'})
        self.assertEqual(store.period('previous_week',today=date(2026,10,12)),{'start':'2026-10-05','end':'2026-10-11'})
        with self.assertRaises(ValueError):store.period('this_week',today=date(2026,10,12))
        with self.assertRaises(ValueError):store.period('custom','2026-10-01','2026-10-15',today=date(2026,10,16))
    def test_active_request_dedup_survives_database_reopen(self):
        first=store.enqueue('inquiry','inquiry:a',{'store':'a'})
        second=store.enqueue('inquiry','inquiry:a',{'store':'a'})
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(store.claim()['id'],first['id'])
        self.assertIsNone(store.claim())
        store.job_update(first['id'],status='SUCCESS')
        self.assertNotEqual(store.enqueue('inquiry','inquiry:a',{'store':'a'})['id'],first['id'])
    def test_candidate_dedup_and_revision_invalidate_downstream_outputs(self):
        p=store.create_product('source:1','Original')
        self.assertEqual(store.create_product('source:1','Second')['id'],p['id'])
        store.commit_output(p['id'],1,'visual',{'job':'image-job','revision':1,'images':[]})
        api.command({'action':'product.approve','id':p['id'],'phase':'visual','revision':1,'artifactJob':'image-job'})
        changed=store.amend_product(p['id'],{'market':'US'})
        self.assertIsNone(changed['approvedVisual'])
        with self.assertRaises(ValueError):store.commit_output(p['id'],1,'listing',{'draft_id':'old'})
        self.assertIsNone(store.product(p['id'])['draft'])
    def test_listing_cannot_skip_visual_approval_or_confirmed_new_product_plan(self):
        p=store.create_product('source:1','Product',facts={'mode':'concept'})
        with self.assertRaises(ValueError):api.command({'action':'product.run','id':p['id'],'revision':1,'kind':'listing','acknowledgeExecution':True})
        self.assertIn('当前版本的新品属性方案',skill_jobs.missing(p,'listing'))
    def test_stale_form_does_not_overwrite_another_pages_product_facts(self):
        p=store.create_product('fixture:concurrent','Fixture product')
        store.amend_product(p['id'],{'market':'US'},expected_revision=1)
        with self.assertRaises(ValueError):store.amend_product(p['id'],{'market':'UK'},expected_revision=1)
        self.assertEqual(store.product(p['id'])['facts']['market'],'US')
    def test_followup_repeated_periods_preserve_done_but_new_buyer_message_reopens(self):
        conv={'conversationId':'conv-1','contactName':'Fixture Buyer','messages':[{'sendTime':'2026-10-15T10:00:00','senderRole':'buyer','content':'Question'}]}
        self.assertEqual(store.add_followups('a',[conv],'job-1'),1)
        todo=store.records('todos')[0]
        store.update_todo(todo['id'],{'status':'DONE','owner':'Fixture owner','note':'Handled'})
        self.assertEqual(store.add_followups('a',[conv],'job-2'),0)
        self.assertEqual(store.records('todos')[0]['status'],'DONE')
        conv['messages'].append({'sendTime':'2026-10-15T11:00:00','senderRole':'buyer','content':'New question'})
        store.add_followups('a',[conv],'job-3')
        self.assertEqual(store.records('todos')[0]['status'],'OPEN')
        store.add_followups('b',[conv],'job-4')
        self.assertEqual(len(store.records('todos')),2)
    def test_inquiry_followup_can_create_one_linked_product(self):
        store.add_followups('a',[{'conversationId':'c','messages':[{'senderRole':'buyer','sendTime':'2026-10-15','content':'Question'}]}],'job')
        todo=store.records('todos')[0]
        p=api.command({'action':'todo.product','id':todo['id'],'title':'Fixture demand'})
        again=api.command({'action':'todo.product','id':todo['id'],'title':'Fixture demand'})
        self.assertEqual(p['id'],again['id'])
        self.assertEqual(store.records('todos')[0]['product'],p['id'])
    def test_older_period_cannot_reopen_done_and_seller_reply_is_observed_without_claiming_full_answer(self):
        conv={'conversationId':'conversation','messages':[{'senderRole':'buyer','sendTime':'2026-10-15T10:00:00','content':'Latest'}]}
        store.add_followups('a',[conv],'recent')
        todo=store.records('todos')[0];store.update_todo(todo['id'],{'status':'DONE'})
        older={'conversationId':'conversation','messages':[{'senderRole':'buyer','sendTime':'2026-10-10T10:00:00','content':'Older'}]}
        store.add_followups('a',[older],'previous-week')
        self.assertEqual(store.records('todos')[0]['status'],'DONE')
        self.assertEqual(store.records('todos')[0]['evidence'],'Latest')
        conv['messages'].append({'senderRole':'seller','sendTime':'2026-10-15T11:00:00','content':'Reply'})
        store.add_followups('a',[conv],'reply-observed')
        self.assertTrue(store.records('todos')[0]['responseObserved'])
        self.assertEqual(store.records('todos')[0]['status'],'DONE')
    def test_duplicate_conversation_ids_across_sellers_keep_separate_followups(self):
        rows=[
            {'conversationId':'same','sellerAliId':'seller-1','contactName':'Buyer 1','messages':[{'senderRole':'buyer','sendTime':'2026-10-19T10:00:00','content':'Question 1'}]},
            {'conversationId':'same','sellerAliId':'seller-2','contactName':'Buyer 2','messages':[{'senderRole':'buyer','sendTime':'2026-10-19T10:01:00','content':'Question 2'}]},
        ]
        self.assertEqual(store.add_followups('a',rows,'job-1'),2)
        todos=store.records('todos')
        self.assertEqual(len(todos),2)
        self.assertEqual({x['sellerAliId'] for x in todos},{'seller-1','seller-2'})
        self.assertEqual({x['evidence'] for x in todos},{'Question 1','Question 2'})
    def test_empty_outputs_and_fake_draft_receipts_do_not_count_as_success(self):
        with self.assertRaises(ValueError):skill_jobs.validate_result(self.root,'visual',{'status':'completed','images':[]})
        with self.assertRaises(ValueError):skill_jobs.validate_result(self.root,'listing',{'status':'completed','draft_id':'1','draft_url':'https://example.com/1'})
        with self.assertRaises(ValueError):skill_jobs.artifact(self.root,'../secret.txt')
        with self.assertRaises(ValueError):api.artifact_file('0'*32,'executor.log')
    def test_worker_runs_registered_inquiry_adapter_and_persists_result(self):
        job=api.command({'action':'inquiry.create','store':'youhealth','periodMode':'previous_week','sourceMode':'cached'})
        with tempfile.TemporaryDirectory() as tmp,patch.object(api.weekly_update,'STATE',Path(tmp)),patch('inquiry_jobs.run',return_value={'reportSnapshot':'fixture'}):
            api.worker()
        self.assertEqual(store.records('jobs')[0]['status'],'SUCCESS')
        self.assertEqual(store.records('jobs')[0]['result']['reportSnapshot'],'fixture')
    def test_unknown_stores_and_commands_are_rejected(self):
        with self.assertRaises(ValueError):api.command({'action':'inquiry.create','store':'unbound','periodMode':'previous_week'})
        with self.assertRaises(ValueError):api.command({'action':'shell','command':'anything'})
    def test_report_handoff_reads_index_after_scan_summary_and_is_repeatable(self):
        import inquiry_jobs
        import shared_scan
        job=store.enqueue('inquiry','test-handoff',{'store':'youhealth','period':{'start':'2026-10-09','end':'2026-10-15'}})
        folder=store.STATE/'runs'/job['id']/'inquiry-engine/inquiry';folder.mkdir(parents=True)
        (folder/'conversations.json').write_text(json.dumps({'store':{'aliId':api.weekly_update.STORES['youhealth']['expected_id']},'window':{'since':'2026-10-09T00:00:00','until':'2026-10-15T23:59:59'},'conversations':[]}),encoding='utf-8')
        (folder/'buyers.json').write_text('[]',encoding='utf-8')
        (folder/'询盘客户背调分析_fixture.html').write_text('<html>'+('fixture '*150)+'</html>',encoding='utf-8')
        share=self.root/'share';share.mkdir()
        index={'records':[{'store':'youhealth','id':'fixture','complete':True,'sourceRelative':'Youhealth/manual-'+job['id']+'-inquiry/report.html'}]}
        with patch.object(shared_scan,'SHARE',share),patch.object(shared_scan,'scan',return_value={'status':'SUCCESS'}),patch.object(shared_scan,'read_index',return_value=index):
            self.assertEqual(inquiry_jobs.finish(job)['reportSnapshot'],'fixture')
            self.assertEqual(inquiry_jobs.finish(job)['reportSnapshot'],'fixture')
    def test_packaging_runner_collects_real_files_and_requires_review_before_full_visuals(self):
        from PIL import Image
        p=store.create_product('fixture:packaging','Fixture product',facts={'market':'US','form':'powder','design':'Fixture design','mode':'concept'})
        job=store.enqueue('packaging','product:'+p['id'],{'product':p['id'],'revision':1})
        root=store.STATE/'runs'/job['id']
        class FixtureProcess:
            returncode=0
            def __init__(self,*args,**kwargs):pass
            def communicate(self,*args,**kwargs):
                Image.new('RGB',(1000,1000),'white').save(root/'package.png')
                (root/'brief.md').write_text('Fixture design brief',encoding='utf-8')
                (root/'result.json').write_text(json.dumps({'status':'completed','images':[{'slot':'A0','file':'package.png'}],'brief_file':'brief.md'}),encoding='utf-8')
        with patch.object(skill_jobs.shutil,'which',return_value='fixture-executor'),patch.object(skill_jobs.subprocess,'Popen',FixtureProcess):
            result=skill_jobs.run(job)
        self.assertEqual(result['stage'],'PACKAGING_REVIEW')
        self.assertIn('当前版本的包装方向审核',skill_jobs.missing(store.product(p['id']),'visual'))
        api.command({'action':'product.approve','id':p['id'],'phase':'packaging','revision':1,'artifactJob':job['id']})
        self.assertNotIn('当前版本的包装方向审核',skill_jobs.missing(store.product(p['id']),'visual'))
        self.assertEqual(api.artifact_file(job['id'],'package.png'),root/'package.png')

if __name__=='__main__':unittest.main()
