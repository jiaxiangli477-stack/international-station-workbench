from pathlib import Path
import tempfile,unittest
import dashboard_native_week as native

class NativeWeekTests(unittest.TestCase):
    def binding(self,ws):
        native.write(ws/'raw/_window.json',{'as_of':'2026-10-21','weeks':[{'week_start':'2026-10-12','week_end':'2026-10-18'}]})
        native.write(ws/'raw/platform_native_week_windows.json',{'windows':[{'start':'2026-10-12','end':'2026-10-18','statDate':'2026-10-17','source':'platform-date-picker','confirmed':True,'evidence':'TEST FIXTURE, not live platform verification'}]})
    def call(self,requests,token='2026-10-17'):
        def invoke(tool,payload):
            q=payload['shopProductQueryParam'];requests.append(q)
            i=q['pageNo'];row={'id':str(100+i),'sumProdFbNum':i,'atmFbUv':4,'totalClkCnt':8,'totalImpsCnt':100,'crtOrd':0,'rtsOnlineAmt':0,'prodName':'Native '+str(i),'prodImage':'https://example.invalid/a.jpg','prodLevel3':'优品'}
            return {'success':True,'data':{'recordCount':3,'data':[row],'downloadUrl':'https://example.invalid/?statisticsType=week&statDate='+token}}
        return invoke
    def test_native_pagination_preserves_weekly_values_without_daily_calls(self):
        with tempfile.TemporaryDirectory(dir='D:/Codex') as t:
            ws=Path(t);self.binding(ws);calls=[]
            native.collect_all(ws,'STORE',self.call(calls))
            self.assertEqual(len(calls),3)
            self.assertTrue(all(q['statisticsType']=='week' and 'statDate' not in q for q in calls))
            rows=native.product_rows(ws,'2026-10-12','2026-10-18','STORE')
            self.assertEqual(len(rows),3);self.assertEqual(rows[0]['tm'],4);self.assertIsNone(rows[0]['tm_daily_sum'])
            self.assertEqual(rows[0]['title'],'Native 1');self.assertEqual(rows[0]['prod_level'],'优品')
            self.assertEqual(native.verify_rows(ws,'2026-10-12','2026-10-18',rows)['mode'],'platform_native_week')
    def test_no_date_picker_proof_does_not_guess_dates_or_fall_back_to_daily(self):
        with tempfile.TemporaryDirectory(dir='D:/Codex') as t:
            ws=Path(t);self.binding(ws);(ws/'raw/platform_native_week_windows.json').unlink();calls=[]
            with self.assertRaisesRegex(ValueError,'页面选择器'):native.collect_all(ws,'STORE',self.call(calls))
            self.assertEqual(calls,[])
    def test_native_current_week_cannot_be_relabelled_as_historical(self):
        with tempfile.TemporaryDirectory(dir='D:/Codex') as t:
            ws=Path(t);self.binding(ws)
            with self.assertRaisesRegex(ValueError,'另一个自然周'):native.collect_week(ws,'STORE','2026-10-12','2026-10-18',self.call([],'2026-10-10'))
            self.assertFalse((native.directory(ws,'2026-10-12')/'manifest.json').exists())
    def test_t_plus_two_blocks_not_yet_available_full_week(self):
        with tempfile.TemporaryDirectory(dir='D:/Codex') as t:
            ws=Path(t);self.binding(ws);w=native.read(ws/'raw/_window.json');w['as_of']='2026-10-19';native.write(ws/'raw/_window.json',w)
            with self.assertRaisesRegex(ValueError,'T\+2'):native.collect_all(ws,'STORE',self.call([]))
    def test_tampered_page_and_cross_store_snapshot_are_rejected(self):
        with tempfile.TemporaryDirectory(dir='D:/Codex') as t:
            ws=Path(t);self.binding(ws);m=native.collect_week(ws,'STORE','2026-10-12','2026-10-18',self.call([]))
            with self.assertRaises(ValueError):native.snapshot(ws,'2026-10-12','2026-10-18','OTHER')
            page=native.directory(ws,'2026-10-12')/m['pages'][0]['file'];page.write_text('{}')
            with self.assertRaisesRegex(ValueError,'哈希'):native.snapshot(ws,'2026-10-12','2026-10-18','STORE')
    def test_legacy_daily_snapshots_are_not_loaded_as_native_week(self):
        with tempfile.TemporaryDirectory(dir='D:/Codex') as t:
            ws=Path(t);native.write(ws/'raw/weekly_products/2026-10-12/manifest.json',{'format':'dashboard-week-daily-rollup/v2','completed':True})
            self.assertEqual(native.product_rows(ws,'2026-10-12','2026-10-18','STORE'),[])
    def test_dashboard_enrich_consumes_native_week_without_losing_weekly_tm(self):
        from dashboard_integrity import enrich
        import sqlite3
        with tempfile.TemporaryDirectory(dir='D:/Codex') as t:
            ws=Path(t);self.binding(ws);native.collect_all(ws,'STORE',self.call([]))
            (ws/'database').mkdir();sqlite3.connect(ws/'database/alibaba_growth.db').close()
            data={'meta':{'store_id':'STORE','week_start':'2026-10-12'},'weeks':[{'week_start':'2026-10-12','week_end':'2026-10-18','fb_cnt':6,'fb_tm_uv':4}],'months':[],'boss':{}}
            bundle=enrich(data,ws)['audit_periods']['week:2026-10-12']
            self.assertEqual(bundle['provenance']['mode'],'platform_native_week')
            self.assertEqual(bundle['products'][0]['tm'],4)
            self.assertEqual(bundle['products'][0]['inquiries'],1)
            self.assertEqual(len(bundle['lists']['opp']),3)

if __name__=='__main__':unittest.main()
