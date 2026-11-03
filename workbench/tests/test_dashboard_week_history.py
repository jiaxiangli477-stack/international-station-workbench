from datetime import date,timedelta
from pathlib import Path
import json
import tempfile
import unittest
import sqlite3
from calendar_periods import dashboard_windows
import dashboard_week_history as history
from dashboard_integrity import validate_product_pages

def response(payload,rows,count):
    day=payload['shopProductQueryParam']['statDate']
    return {'success':True,'data':{'recordCount':count,'data':rows,'downloadUrl':'https://example.invalid/report?statisticsType=day&statDate='+day}}

class WeekHistoryTests(unittest.TestCase):
    def test_enrich_builds_all_weekly_rankings_without_latest_week_database_reuse(self):
        from dashboard_integrity import enrich
        with tempfile.TemporaryDirectory(dir='D:/Codex') as t:
            ws=Path(t);(ws/'database').mkdir();sqlite3.connect(ws/'database/alibaba_growth.db').close()
            windows=dashboard_windows(date(2026,10,20));history.write(ws/'raw/_window.json',windows)
            def call(tool,payload):
                q=payload['shopProductQueryParam'];day=date.fromisoformat(q['statDate']);day=(day-timedelta(days=day.weekday())).day
                return response(payload,[{'id':str(10000+day),'totalClkCnt':day,'totalImpsCnt':100,'sumProdFbNum':1,'atmFbUv':0,'crtOrd':0,'rtsOnlineAmt':0,'adClkCnt':0,'adImpsCnt':0}],1)
            history.collect_all(ws,'S',call)
            weeks=[{'week_start':w['week_start'],'week_end':w['week_end'],'fb_cnt':1,'fb_tm_uv':0} for w in reversed(windows['weeks'])]
            result=enrich({'meta':{'store_id':'S','week_start':weeks[-1]['week_start']},'weeks':weeks,'months':[],'boss':{}},ws)
            self.assertEqual(len(result['audit_periods']),4)
            self.assertEqual(len({a['products'][0]['product_id'] for a in result['audit_periods'].values()}),4)
            self.assertTrue(all(len(a['lists']['inquiry'])==1 for a in result['audit_periods'].values()))
            self.assertTrue(all(a['products'][0]['tm'] is None and not a['lists']['opp'] for a in result['audit_periods'].values()))
    def test_all_four_weeks_have_distinct_complete_snapshots_with_short_pages(self):
        with tempfile.TemporaryDirectory(dir='D:/Codex') as t:
            ws=Path(t);history.write(ws/'raw/_window.json',dashboard_windows(date(2026,10,20)))
            calls=[]
            def call(tool,payload):
                q=payload['shopProductQueryParam'];calls.append((q['statDate'],q['pageNo']))
                # Requested 20, platform returns only 10: must continue by recordCount.
                page=q['pageNo'];rows=[{'id':str(1000+i),'subject':q['statDate'],'totalClkCnt':i,'totalImpsCnt':100,'sumProdFbNum':1,'atmFbUv':1} for i in range((page-1)*10,min(page*10,23))]
                return response(payload,rows,23)
            manifests=history.collect_all(ws,'STORE',call)
            self.assertEqual(len(calls),84)
            for m in manifests:
                rows=history.product_rows(ws,m['start'],m['end'],'STORE')
                self.assertEqual(len(rows),23);self.assertEqual(rows[0]['title'],m['end'])
                self.assertIsNone(rows[0]['tm'])
                self.assertEqual(rows[0]['tm_daily_sum'],7)
                self.assertEqual(validate_product_pages(ws,'week',m['start'],m['end'],rows)['records'],23)
            self.assertEqual(len(list((ws/'raw').glob('shop_product_w1_p*.json'))),2)
    def test_duplicate_or_partial_pages_do_not_publish_success(self):
        for payload in ({'success':True,'data':{'recordCount':2,'data':[{'id':'1'},{'id':'1'}]}},
                        {'success':False,'data':{}},
                        {'success':True,'data':{'recordCount':2,'data':[]}}):
            with self.subTest(payload=payload),tempfile.TemporaryDirectory(dir='D:/Codex') as t:
                with self.assertRaises(ValueError):history.collect_week(Path(t),'S','2026-10-05','2026-10-11',lambda *a:payload)
                self.assertFalse((Path(t)/'raw/weekly_products/2026-10-05/manifest.json').exists())
    def test_empty_is_verified_and_different_store_is_rejected(self):
        with tempfile.TemporaryDirectory(dir='D:/Codex') as t:
            ws=Path(t);history.collect_week(ws,'S','2026-10-05','2026-10-11',lambda tool,payload:response(payload,[],0))
            self.assertEqual(history.product_rows(ws,'2026-10-05','2026-10-11','S'),[])
            self.assertEqual(history.verify_rows(ws,'2026-10-05','2026-10-11',[])['records'],0)
            with self.assertRaises(ValueError):history.product_rows(ws,'2026-10-05','2026-10-11','OTHER')
    def test_returned_latest_week_cannot_be_relabelled_as_history(self):
        with tempfile.TemporaryDirectory(dir='D:/Codex') as t:
            with self.assertRaisesRegex(ValueError,'日期'):
                history.collect_week(Path(t),'S','2026-10-05','2026-10-11',lambda *a:{'success':True,'data':{'recordCount':0,'data':[],'downloadUrl':'https://example.invalid/?statisticsType=week&statDate=2026-10-17'}})
            self.assertFalse((Path(t)/'raw/weekly_products/2026-10-05/manifest.json').exists())
    def test_missing_day_is_not_zero_but_confirmed_precreation_is_zero(self):
        def day(d,items):return {'day':d,'items':items}
        r={'id':'1','crtTime':'2026-10-07','totalClkCnt':2,'sumProdFbNum':1,'atmFbUv':1}
        days=[day('2026-10-%02d'%n,{'1':r} if n>=7 else {}) for n in range(5,12)]
        self.assertEqual(history.aggregate_days(days)['1']['totalClkCnt'],10)
        days[3]['items']={}
        self.assertIsNone(history.aggregate_days(days)['1']['totalClkCnt'])
    def test_source_count_disagreement_requires_two_enumerations_and_empty_tails(self):
        with tempfile.TemporaryDirectory(dir='D:/Codex') as t:
            def call(tool,payload):
                q=payload['shopProductQueryParam'];rows=[{'id':'1','totalClkCnt':1},{'id':'2','totalClkCnt':2}] if q['pageNo']==1 else []
                return response(payload,rows,1)  # Source declares 1, but enumerates 2.
            ws=Path(t);m=history.collect_week(ws,'S','2026-10-05','2026-10-11',call)
            self.assertEqual(len(m['countWarnings']),7)
            self.assertEqual(history.snapshot(ws,'2026-10-05','2026-10-11','S')[0]['records'],2)
            m['countWarnings'][0]['alternatePages']=[];history.write(ws/'raw/weekly_products/2026-10-05/manifest.json',m)
            with self.assertRaisesRegex(ValueError,'双枚举'):history.snapshot(ws,'2026-10-05','2026-10-11','S')
    def test_historical_ads_are_requested_independently_and_failures_not_zero(self):
        with tempfile.TemporaryDirectory(dir='D:/Codex') as t:
            ws=Path(t);history.write(ws/'raw/_window.json',dashboard_windows(date(2026,10,20)))
            calls=[]
            def call(payload):calls.append(payload);return {'success':False,'data':[]}
            out=history.collect_ad_weeks(ws,call)
            self.assertEqual(len(out),4);self.assertEqual(len(calls),8)
            self.assertEqual(len({x['filters']['beginDateTime'] for x in calls}),4)
            self.assertTrue(all(v=='UNAVAILABLE' for a in out for v in a['coverage'].values()))
    def test_guard_failure_never_marks_snapshot_complete(self):
        with tempfile.TemporaryDirectory(dir='D:/Codex') as t:
            def fail():raise ValueError('store changed')
            with self.assertRaises(ValueError):history.collect_week(Path(t),'S','2026-10-05','2026-10-11',lambda *a:{},fail)
            self.assertFalse((Path(t)/'raw/weekly_products/2026-10-05/manifest.json').exists())
