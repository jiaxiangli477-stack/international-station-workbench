import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import recruitment as native
import weekly_update


class NativePagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=native.STATE;native.STATE=Path(self.tmp.name)
    def tearDown(self):
        native.STATE=self.old;self.tmp.cleanup()

    def fixture_snapshot(self):
        base=native.STATE/'youhealth';base.mkdir();db=base/'fixture.sqlite'
        conn=sqlite3.connect(db)
        conn.execute('CREATE TABLE topics(business TEXT,id TEXT,title TEXT,tag TEXT,leaf TEXT,category_ids TEXT,countries TEXT,created REAL,source_order INTEGER,payload TEXT,PRIMARY KEY(business,id))')
        for business,count in [('HOT_PRODUCT',61),('CUSTOMIZATION_PRODUCT',7)]:
            for i in range(count):
                row={'id':business+str(i),'title':'fixture '+str(i),'tag':'GLOBAL_HOT,ICBU_HOT' if i%2==0 else 'ICBU_SHORT'}
                conn.execute('INSERT INTO topics VALUES(?,?,?,?,?,?,?,?,?,?)',(business,row['id'],row['title'],row['tag'],'Nutrition',',1,2,','|US|' if i%2==0 else '|GB|',1,i,json.dumps(row)))
        conn.commit();conn.close()
        for page in (1,2):
            raw=[{'id':'HOT_PRODUCT'+str(i),'title':'fixture '+str(i),'businessType':'HOT_PRODUCT','categoryIds':'1','ruleDTO':{}} for i in range((page-1)*48,min(page*48,61))]
            (base/('hot_product-'+str(page)+'.json')).write_text(json.dumps({'success':True,'value':{'pageNo':page,'pageSize':48,'pageCount':2,'recordCount':61,'datas':raw}}))
        (base/'categories.json').write_text(json.dumps({'value':{'1':{'name':'Nutrition'}}}))
        (base/'snapshot.json').write_text(json.dumps({'database':'fixture.sqlite','business':{'HOT_PRODUCT':{'totalPages':2,'declaredTotal':61}},'collectedAt':'2026-10-16'}))
        (base/'status.json').write_text(json.dumps({'status':'SUCCESS'}))

    def test_page_two_does_not_repeat_page_one(self):
        self.fixture_snapshot()
        first=native.read_page('youhealth',{'page':'1'});second=native.read_page('youhealth',{'page':'2'})
        self.assertEqual(len(first['records']),48);self.assertEqual(len(second['records']),13)
        self.assertEqual(second['pagination']['totalPages'],2)
        self.assertEqual(second['pagination']['view'],'native')
        self.assertTrue({r['id'] for r in first['records']}.isdisjoint({r['id'] for r in second['records']}))

    def test_types_are_separate_and_filters_search_all_pages(self):
        self.fixture_snapshot()
        custom=native.read_page('youhealth',{'businessType':'CUSTOMIZATION_PRODUCT'})
        self.assertEqual(custom['pagination']['totalRecords'],7)
        result=native.read_page('youhealth',{'title':'fixture 60','tag':'ICBU_HOT','country':'US'})
        self.assertEqual(result['pagination']['totalRecords'],1)
        self.assertEqual(result['records'][0]['id'],'HOT_PRODUCT60')
        self.assertEqual(result['pagination']['view'],'filtered')

    def test_native_echo_must_match_requested_page(self):
        value={'pageNo':1,'pageSize':48,'pageCount':2,'datas':[]}
        with self.assertRaises(weekly_update.SyncError):native.verify_page(value,2,'HOT_PRODUCT')

    def test_short_page_does_not_terminate_platform_page_traversal(self):
        def make_row(key):return {'id':key,'businessType':'HOT_PRODUCT','title':key,'categoryIds':'1','ruleDTO':{}}
        calls=[]
        def fake_call(bridge,folder,business,page):
            calls.append((business,page))
            if business=='CUSTOMIZATION_PRODUCT':return {'pageNo':page,'pageSize':48,'pageCount':0,'recordCount':0,'datas':[]}
            return {'pageNo':page,'pageSize':48,'pageCount':2,'recordCount':3,'datas':[make_row('a'),make_row('b')] if page==1 else [make_row('c')]}
        def fake_run(command,cwd,**kwargs):
            output=Path(command[command.index('--output')+1]);output.write_text(json.dumps({'value':{}}));return ''
        with patch.object(native,'call_page',side_effect=fake_call),patch.object(weekly_update,'require_identity'),patch.object(weekly_update,'run',side_effect=fake_run):
            result=native.collect('youhealth')
        self.assertEqual(result['status'],'SUCCESS')
        self.assertIn(('HOT_PRODUCT',2),calls)
        self.assertEqual(result['business']['HOT_PRODUCT']['uniqueRecords'],3)


if __name__=='__main__':unittest.main()
