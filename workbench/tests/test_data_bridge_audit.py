"""Synthetic regressions for account evidence, stable followups and bridge refresh."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import inquiry_calendar
import inquiry_jobs
import task_store
import weekly_update
from types import SimpleNamespace
from tests import test_inquiry_calendar as calendar_fixtures
from bridge_materialization import save_account_messages


class DataBridgeAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='D:/Codex')
        self.root = Path(self.tmp.name)
        self.patch = patch.object(task_store, 'DB', self.root/'test.sqlite')
        self.patch.start()
        self.state_patch=patch.object(task_store,'STATE',self.root)
        self.state_patch.start()

    def tearDown(self):
        self.patch.stop()
        self.state_patch.stop()
        self.tmp.cleanup()

    def conversation(self, seller, text='question'):
        return {'conversationId': 'same', 'sellerAliId': seller, 'messages': [
            {'sendTime': '2026-10-19T10:00:00', 'senderRole': 'buyer', 'content': text}]}

    def test_followup_identity_is_stable_across_single_and_multiple_seller_runs(self):
        one, two = self.conversation('seller-1'), self.conversation('seller-2', 'other')
        task_store.add_followups('fixture', [one], 'first')
        original = task_store.records('todos')[0]
        task_store.update_todo(original['id'], {'status': 'DONE', 'note': 'retained'})
        task_store.add_followups('fixture', [one, two], 'second')
        task_store.add_followups('fixture', [two], 'third')
        rows = task_store.records('todos')
        self.assertEqual(len(rows), 2)
        same = next(r for r in rows if r['sellerAliId']=='seller-1')
        self.assertEqual((same['id'],same['status'],same['note']),
                         (original['id'],'DONE','retained'))
        self.assertEqual(next(r for r in rows if r['sellerAliId']=='seller-2')['evidence'], 'other')

    def test_known_legacy_followup_keeps_link_and_cannot_be_reassigned_to_another_seller(self):
        legacy_id=hashlib.sha256(b'fixture|same|unanswered').hexdigest()[:24]
        legacy={'id':legacy_id,'store':'fixture','conversation':'same','sellerAliId':'seller-1',
                'status':'DONE','note':'retained','messageTime':'2026-10-19T10:00:00'}
        with task_store.db() as connection:
            connection.execute('INSERT INTO todos VALUES(?,?)',(legacy_id,json.dumps(legacy)))
        task_store.add_followups('fixture',[self.conversation('seller-2','other')],'second')
        self.assertEqual(len(task_store.records('todos')),2)
        self.assertEqual(next(r for r in task_store.records('todos') if r['id']==legacy_id),legacy)

    def test_followup_orders_timezone_aware_messages_by_instant(self):
        conversation=self.conversation('seller-1')
        conversation['messages']=[
            {'sendTime':'2026-10-19T10:00:00+08:00','senderRole':'buyer','content':'question'},
            {'sendTime':'2026-10-19T03:00:00Z','senderRole':'seller','content':'later answer'}]
        self.assertEqual(task_store.add_followups('fixture',[conversation],'job'),0)

    def segment(self):
        period={'start':'2026-10-19','end':'2026-10-25'}
        folder=self.root/'part'
        calendar_fixtures.InquiryCalendarTests.part(self,folder,period)
        def load(name):return json.loads((folder/name).read_text('utf-8'))
        def save(name,value):(folder/name).write_text(json.dumps(value),encoding='utf-8')
        raw=load('.work/conversations_all.json')
        raw['conversations'][0].update(sellerAliId='seller-1',contactAliId='buyer-1')
        raw['conversations'].append(dict(raw['conversations'][0],sellerAliId='seller-2',contactAliId='buyer-2'))
        raw['meta'].update(totalConversations=2,totalAccounts=2)
        save('.work/conversations_all.json',raw)
        normalized=load('conversations.json');normalized['store']['accountCount']=2
        normalized['conversations'][0].update(sellerAliId='seller-1',contactAliId='buyer-1')
        normalized['conversations'].append(deepcopy(normalized['conversations'][0]))
        normalized['conversations'][1].update(sellerAliId='seller-2',contactAliId='buyer-2')
        for index,row in enumerate(normalized['conversations']):
            row['messages']=[dict(row['messages'][0],content='message '+str(index))]
        save('conversations.json',normalized)
        messages=load('.work/messages_all.json')
        messages['conversations']=[{'conversationId':row['conversationId'],'sellerAliId':row['sellerAliId'],
                                   'messages':row['messages']} for row in normalized['conversations']]
        messages['meta'].update(sourceTotalConversations=2,totalInputConversations=2,
                                totalConversationsWithMessages=2,totalMessages=2)
        save('.work/messages_all.json',messages)
        return folder,period,load,save

    def test_cross_seller_message_swap_cannot_pass_complete_period_verification(self):
        folder,period,load,save=self.segment()
        normalized=load('conversations.json')
        rows=normalized['conversations'];rows[0]['messages'],rows[1]['messages']=rows[1]['messages'],rows[0]['messages']
        save('conversations.json',normalized)
        with self.assertRaises(ValueError):inquiry_calendar.verified_part(folder,'123',period)

    def test_ambiguous_bulk_rows_require_account_fetch_evidence(self):
        folder,period,load,save=self.segment()
        messages=load('.work/messages_all.json')
        for row in messages['conversations']:row.pop('sellerAliId')
        save('.work/messages_all.json',messages)
        with self.assertRaises(ValueError):inquiry_calendar.verified_part(folder,'123',period)

    def test_account_recovery_preserves_original_bulk_and_binds_verified_messages(self):
        folder,period,load,save=self.segment()
        messages=load('.work/messages_all.json')
        for row in messages['conversations']:row.pop('sellerAliId')
        save('.work/messages_all.json',messages)
        original=(folder/'.work/messages_all.json').read_bytes()
        rows=load('conversations.json')['conversations']
        save_account_messages(folder/'.work/account_messages.json',folder/'.work/conversations_all.json',
                              folder/'.work/messages_all.json',
                              {(row['sellerAliId'],row['conversationId']):row['messages'] for row in rows})
        inquiry_calendar.verified_part(folder,'123',period)
        self.assertEqual((folder/'.work/messages_all.json').read_bytes(),original)
        normalized=load('conversations.json')
        rows=normalized['conversations'];rows[0]['messages'],rows[1]['messages']=rows[1]['messages'],rows[0]['messages']
        save('conversations.json',normalized)
        with self.assertRaises(ValueError):inquiry_calendar.verified_part(folder,'123',period)

    def prepare_engine(self,engine):
        engine.mkdir(parents=True,exist_ok=True)
        (engine/'inquiry_analysis.py').write_text('# synthetic',encoding='utf-8')
        return {'version':'fixture'}

    def test_cached_reanalysis_keeps_self_contained_raw_evidence(self):
        folder,period,load,save=self.segment()
        job=task_store.enqueue('inquiry','cache-fixture',{'store':'fixture','period':period,'sourceMode':'cached'})
        cfg={'expected_id':'123'}
        class StopAfterValidation(Exception):pass
        with patch.dict(inquiry_jobs.weekly.STORES,{'fixture':cfg}), \
                patch.object(inquiry_jobs.weekly,'prepare_inquiry',side_effect=self.prepare_engine), \
                patch.object(inquiry_jobs,'cached_source',return_value=folder/'conversations.json'), \
                patch('inquiry_release.run_analysis',side_effect=StopAfterValidation):
            with self.assertRaises(StopAfterValidation):inquiry_jobs.run(job)
        target=self.root/'runs'/job['id']/'inquiry-engine/inquiry'
        for path in (folder/'.work').iterdir():path.unlink()
        inquiry_calendar.verified_part(target,'123',period)
        self.assertTrue((target/'cached-collection.json').is_file())

    def test_live_inquiry_reuses_shims_without_running_credential_setup(self):
        period={'start':'2026-10-19','end':'2026-10-25'}
        job=task_store.enqueue('inquiry','live-fixture',{'store':'fixture','period':period,'sourceMode':'live'})
        class StopBeforeCollection(Exception):pass
        with patch.dict(inquiry_jobs.weekly.STORES,{'fixture':{'expected_id':'123'}}), \
                patch.object(inquiry_jobs.weekly,'prepare_inquiry',side_effect=self.prepare_engine), \
                patch.object(inquiry_jobs.shared_scan,'SHARE',self.root), \
                patch.object(inquiry_jobs.weekly,'prepare_bridge',return_value=self.root/'bridge/bin') as prepare, \
                patch.object(inquiry_jobs.weekly,'require_identity'), \
                patch.object(inquiry_jobs.weekly,'run') as run, \
                patch('bridge_runtime.child_environment',side_effect=lambda _,env:dict(env,ACCIO_GATEWAY_TOKEN='fixture-current')), \
                patch('inquiry_calendar.collect',side_effect=StopBeforeCollection) as collect:
            with self.assertRaises(StopBeforeCollection):inquiry_jobs.run(job)
        prepare.assert_called_once()
        run.assert_not_called()
        self.assertEqual(collect.call_args.kwargs['env']['ACCIO_GATEWAY_TOKEN'],'fixture-current')

    def test_each_calendar_segment_refreshes_its_child_gateway_environment(self):
        from datetime import date,timedelta
        engine=self.root/'engine';engine.mkdir()
        for name in ('fetch_inquiries.py','fetch_buyer_contacts.py','bridge_materialization.py'):
            (engine/name).write_text('# fixture',encoding='utf-8')
        tokens=[]
        def fetch(command,cwd,**kwargs):
            end=command[command.index('--end-date')+1]
            days=int(command[command.index('--days')+1])
            start=(date.fromisoformat(end)-timedelta(days=days-1)).isoformat()
            tokens.append(kwargs['env']['ACCIO_GATEWAY_TOKEN'])
            calendar_fixtures.InquiryCalendarTests.part(self,Path(cwd)/'inquiry',{'start':start,'end':end})
        with patch('weekly_update.require_identity'),patch('weekly_update.run',side_effect=fetch), \
                patch('inquiry_release.collect_contacts'), \
                patch('bridge_runtime.child_environment',side_effect=[{'ACCIO_GATEWAY_TOKEN':'first'},
                    {'ACCIO_GATEWAY_TOKEN':'second'},{'ACCIO_GATEWAY_TOKEN':'third'},
                    {'ACCIO_GATEWAY_TOKEN':'fourth'},{'ACCIO_GATEWAY_TOKEN':'fifth'}]) as refresh:
            inquiry_calendar.collect(engine,self.root/'bridge','123',{'start':'2026-08-01','end':'2026-08-31'},env={})
        self.assertEqual(tokens,['first','second','third','fourth','fifth'])
        self.assertEqual(refresh.call_count,5)

    def test_collector_failure_shows_known_blocker_without_private_output(self):
        result=SimpleNamespace(returncode=5,stdout='fixture-private-account\n账号范围消息未完整核验，停止生成新报告',
                               stderr='fixture-secret-token')
        with patch('weekly_update.subprocess.run',return_value=result):
            with self.assertRaises(weekly_update.SyncError) as error:
                weekly_update.run(['fixture-cli'],self.root,env={})
        self.assertIn('跨销售账号',str(error.exception))
        self.assertNotIn('fixture-',str(error.exception))

    def test_failed_retry_preserves_previous_success_timestamp(self):
        weekly_state=self.root/'weekly';weekly_state.mkdir()
        previous='2026-10-01T10:00:00+08:00'
        (weekly_state/'status.json').write_text(json.dumps({'stores':{'fixture':{'lastSuccess':previous}}}),encoding='utf-8')
        with patch.object(weekly_update,'STATE',weekly_state), \
                patch.dict(weekly_update.STORES,{'fixture':{'expected_id':'123'}},clear=True), \
                patch.object(weekly_update.catalog,'SHARE',self.root), \
                patch.object(weekly_update.catalog,'scan',return_value={}), \
                patch.object(weekly_update,'prepare_bridge',return_value=self.root/'bridge'), \
                patch.object(weekly_update,'bridge_identity',return_value='123'), \
                patch.object(weekly_update,'do_store',return_value={'status':'FAILED','lastSuccess':None}):
            result=weekly_update.update('fixture')
        self.assertEqual(result['status'],'FAILED')
        self.assertEqual(result['stores']['fixture']['lastSuccess'],previous)

    def test_published_reports_with_failed_followup_handoff_are_only_partial(self):
        period={'start':'2026-10-19','end':'2026-10-25'}
        def prepare_inquiry(engine):
            folder=engine/'inquiry';folder.mkdir(parents=True)
            (folder/'conversations.json').write_text(json.dumps({'store':{'aliId':'123'},'conversations':[]}),encoding='utf-8')
            (folder/'询盘客户背调分析_fixture.html').write_text('<html>'+('fixture '*200)+'</html>',encoding='utf-8')
        def prepare_dashboard(engine,*args,**kwargs):
            folder=engine/'engine/workspace/dashboard';folder.mkdir(parents=True)
            (folder/'dashboard_data.js').write_text('fixture',encoding='utf-8')
        from datetime import date
        with patch.object(weekly_update,'require_identity'), \
                patch.object(weekly_update,'prepare_inquiry',side_effect=prepare_inquiry), \
                patch.object(weekly_update,'prepare_dashboard',side_effect=prepare_dashboard), \
                patch.object(weekly_update,'dashboard_requested_windows',return_value=[{'week_start':period['start'],'week_end':period['end']}]), \
                patch.object(weekly_update,'run'), \
                patch.object(weekly_update,'publish_files',return_value=self.root/'published'), \
                patch.object(weekly_update.catalog,'atomic_json'), \
                patch('shared_scan.data_object',return_value={'meta':{'store_id':'123'}}), \
                patch('inquiry_calendar.collect'),patch('inquiry_release.run_analysis'), \
                patch('task_store.record_completed',return_value={'id':'fixture'}), \
                patch('task_store.add_followups',side_effect=ValueError('fixture handoff failure')):
            result=weekly_update.do_store('fixture',{'expected_id':'123','folder':'fixture','label':'fixture'},
                                          self.root/'stage',self.root/'bridge',date(2026,10,27))
        self.assertEqual(result['publishedKinds'],['inquiry','dashboard'])
        self.assertEqual(result['status'],'PARTIAL')
        self.assertIsNone(result['lastSuccess'])


if __name__=='__main__':unittest.main()
