from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from calendar_periods import chunks
from inquiry_calendar import merge_parts,collect,message_date

class InquiryCalendarTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory(dir='D:/Codex');self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def part(self,folder,period,expected='123'):
        folder.mkdir(parents=True,exist_ok=True);work=folder/'.work';work.mkdir(exist_ok=True)
        raw=work/'conversations_all.json';meta={'startDate':period['start'],'endDate':period['end'],'failureRatio':0}
        def put(path,value):path.write_text(json.dumps(value),encoding='utf-8')
        put(raw,{'meta':dict(meta,totalAccounts=1,totalFailedAccounts=0,totalConversations=1),'conversations':[{'conversationId':'c1','sellerAliId':'seller1','sellerName':'seller'}]})
        messages=[{'sendTime':period['start']+' 12:00:00','senderRole':'buyer','content':'same message'}]*2+[{'sendTime':'2026-09-30 12:00:00','senderRole':'buyer','content':'outside month'}]
        put(work/'messages_all.json',{'meta':dict(meta,sourceConversationFile=str(raw),sourceTotalConversations=1,totalInputConversations=1,totalMessages=3,totalConversationsWithMessages=1),'conversations':[{'conversationId':'c1','messages':messages}]})
        put(folder/'conversations.json',{'window':{'since':period['start']+'T00:00:00','until':period['end']+'T23:59:59'},'store':{'aliId':expected,'accountCount':1},'conversations':[{'conversationId':'c1','contactAliId':'buyer1','sellerAliId':'seller1','sellerName':'seller','messages':messages}]})
        put(folder/'buyers.json',[{'contactAliId':'buyer1','persona':{}}])
    def test_31_day_month_has_five_bounded_segments(self):
        parts=chunks('2026-10-01','2026-10-31')
        self.assertEqual(len(parts),5);self.assertEqual(parts[-1],{'start':'2026-10-29','end':'2026-10-31'})
        self.assertEqual(sum((date.fromisoformat(p['end'])-date.fromisoformat(p['start'])).days+1 for p in parts),31)
    def test_month_merge_dedupes_conversations_profiles_but_not_real_repeated_messages(self):
        parts=[]
        for p in chunks('2026-10-01','2026-10-31'):
            folder=self.root/p['start'];self.part(folder,p);parts.append((folder,p))
        result=merge_parts(parts,self.root/'merged','123','2026-10-01','2026-10-31')
        self.assertEqual(result['conversations'],1);self.assertEqual(result['messages'],10);self.assertEqual(result['buyers_with_persona'],1)
        data=json.loads((self.root/'merged/conversations.json').read_text('utf-8'))
        self.assertEqual(data['window']['until'],'2026-10-31T23:59:59')
        self.assertFalse(any(m['content']=='outside month' for c in data['conversations'] for m in c['messages']))
    def test_same_conversation_id_in_two_seller_accounts_remains_two_conversations(self):
        period=chunks('2026-10-19','2026-10-25')[0];folder=self.root/'account-scoped-id';self.part(folder,period)
        def load(path):return json.loads(path.read_text(encoding='utf-8'))
        def save(path,value):path.write_text(json.dumps(value),encoding='utf-8')
        raw=load(folder/'.work/conversations_all.json');raw['meta'].update(totalAccounts=2,totalConversations=2)
        raw['conversations'][0].update(sellerAliId='seller-1',sellerName='Seller 1')
        second=dict(raw['conversations'][0],sellerAliId='seller-2',sellerName='Seller 2',contactAliId='buyer-2')
        raw['conversations'].append(second);save(folder/'.work/conversations_all.json',raw)
        msgs=load(folder/'.work/messages_all.json');msgs['meta'].update(sourceTotalConversations=2,totalInputConversations=2,totalConversationsWithMessages=2,totalMessages=6)
        msgs['conversations'].append(dict(msgs['conversations'][0]));save(folder/'.work/messages_all.json',msgs)
        normalized=load(folder/'conversations.json');normalized['store']['accountCount']=2
        normalized['conversations'][0].update(sellerAliId='seller-1',sellerName='Seller 1')
        second=dict(normalized['conversations'][0],sellerAliId='seller-2',sellerName='Seller 2',contactAliId='buyer-2')
        normalized['conversations'].append(second);save(folder/'conversations.json',normalized)
        msgs=load(folder/'.work/messages_all.json')
        for row,seller in zip(msgs['conversations'],('seller-1','seller-2')):row['sellerAliId']=seller
        save(folder/'.work/messages_all.json',msgs)
        save(folder/'buyers.json',[{'contactAliId':'buyer-1'},{'contactAliId':'buyer-2'}])
        result=merge_parts([(folder,period)],self.root/'account-scoped-merge','123',period['start'],period['end'])
        data=load(self.root/'account-scoped-merge/conversations.json')
        self.assertEqual(result['conversations'],2)
        self.assertEqual(result['messages'],4)
        self.assertEqual({(c['sellerAliId'],c['contactAliId']) for c in data['conversations']},{('seller-1','buyer1'),('seller-2','buyer-2')})
    def test_missing_segment_and_wrong_store_fail_before_merged_output(self):
        p=chunks('2026-10-12','2026-10-18')[0];folder=self.root/'part';self.part(folder,p,'other')
        with self.assertRaises(ValueError):merge_parts([],self.root/'missing','123','2026-10-01','2026-10-31')
        with self.assertRaises(ValueError):merge_parts([(folder,p)],self.root/'wrong','123',p['start'],p['end'])
        self.assertFalse((self.root/'wrong/conversations.json').exists())
    def test_failed_segment_is_not_accepted_as_a_complete_month(self):
        parts=[]
        for p in chunks('2026-10-01','2026-10-31'):
            folder=self.root/p['start'];self.part(folder,p);parts.append((folder,p))
        path=parts[1][0]/'.work/messages_all.json';d=json.loads(path.read_text());d['meta']['failureRatio']=0.5;path.write_text(json.dumps(d))
        with self.assertRaises(ValueError):merge_parts(parts,self.root/'incomplete','123','2026-10-01','2026-10-31')
        self.assertFalse((self.root/'incomplete/conversations.json').exists())
    def test_timezone_day_boundary_and_unknown_timestamps(self):
        self.assertEqual(message_date('2026-09-30T16:00:00Z'),'2026-10-01')
        self.assertEqual(message_date('2026-10-01 00:00:00'),'2026-10-01')
        with self.assertRaises(ValueError):message_date(None)
    def test_collector_calls_only_bounded_windows_and_enriches_each_one(self):
        engine=self.root/'engine';engine.mkdir()
        for name in ['fetch_inquiries.py','fetch_buyer_contacts.py','bridge_materialization.py']:(engine/name).write_text('')
        calls=[]
        def fetch(command,cwd,**kw):
            days=int(command[command.index('--days')+1]);end=command[command.index('--end-date')+1]
            from datetime import timedelta
            start=(date.fromisoformat(end)-timedelta(days=days-1)).isoformat();calls.append((start,end));self.part(Path(cwd)/'inquiry',{'start':start,'end':end})
        with patch('weekly_update.require_identity'),patch('weekly_update.run',side_effect=fetch),patch('inquiry_release.collect_contacts') as contacts:
            result=collect(engine,self.root/'bridge','123',{'start':'2026-08-01','end':'2026-08-31'})
        self.assertEqual(len(calls),5);self.assertEqual(contacts.call_count,5);self.assertEqual(result['segments'],5)

if __name__=='__main__':unittest.main()
