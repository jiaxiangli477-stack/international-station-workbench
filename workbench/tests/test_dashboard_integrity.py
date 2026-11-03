import copy
import json
from pathlib import Path
import tempfile
import unittest

from dashboard_integrity import product_lists, validate_product_pages, patch_app

class IntegrityTests(unittest.TestCase):
    def test_full_rankings_are_not_truncated(self):
        rows=[dict(product_id=str(i),inquiries=1,tm=0,opp=1,total_clk=5,total_ctr=1,ad_clk=0) for i in range(151)]
        ranked=product_lists(rows)
        self.assertEqual(len(ranked['opp']),151)
        self.assertEqual(len(ranked['inquiry']),151)
        self.assertEqual(len(ranked['ctr']),151)

    def test_missing_ad_clicks_do_not_prove_zero_advertising(self):
        row=dict(product_id='1',inquiries=1,tm=0,opp=1,total_clk=5,total_ctr=1,ad_clk=None)
        self.assertEqual(product_lists([row])['zero_cost'],[])
        self.assertEqual(product_lists([row])['high_eff_low_cost'],[])

    def fixture(self,root):
        raw=root/'raw';raw.mkdir()
        (raw/'_window.json').write_text(json.dumps({'weeks':[{'week_start':'2026-10-12','week_end':'2026-10-18'}]}))
        p=dict(id='001234567890123456789',totalImpsCnt=100,totalClkCnt=5,sumProdFbNum=1,atmFbUv=0,crtOrd=0,rtsOnlineAmt=0,adImpsCnt=0,adClkCnt=0)
        response={'success':True,'data':{'recordCount':1,'data':[p]}}
        (raw/'shop_product_w1_p01.json').write_text(json.dumps(response))
        row=dict(product_id=p['id'],total_imps=100,total_clk=5,inquiries=1,tm=0,orders=0,gmv=0,ad_imps=0,ad_clk=0)
        return raw,response,row

    def test_complete_pagination_and_exact_raw_metrics(self):
        with tempfile.TemporaryDirectory(dir='D:/Codex') as tmp:
            root=Path(tmp);raw,response,row=self.fixture(root)
            self.assertEqual(validate_product_pages(root,'week','2026-10-12','2026-10-18',[row])['records'],1)
            changed=copy.deepcopy(row);changed['total_clk']=6
            with self.assertRaisesRegex(ValueError,'指标'):validate_product_pages(root,'week','2026-10-12','2026-10-18',[changed])
            response['data']['recordCount']=2
            (raw/'shop_product_w1_p01.json').write_text(json.dumps(response))
            with self.assertRaisesRegex(ValueError,'不完整'):validate_product_pages(root,'week','2026-10-12','2026-10-18',[row])

    def test_duplicate_ids_fail_instead_of_hiding_incomplete_source(self):
        with tempfile.TemporaryDirectory(dir='D:/Codex') as tmp:
            root=Path(tmp);raw,response,row=self.fixture(root)
            response['data']['data']*=2
            (raw/'shop_product_w1_p01.json').write_text(json.dumps(response))
            with self.assertRaisesRegex(ValueError,'重复'):validate_product_pages(root,'week','2026-10-12','2026-10-18',[row])

    def test_patch_is_idempotent(self):
        source="document.addEventListener('DOMContentLoaded', boot);"
        one=patch_app(source)
        self.assertEqual(patch_app(one),one)

    def test_health_and_staff_template_patches_are_idempotent(self):
        source='''function renderHealth(){
  var tr0 = (sr.tracks||[])[0] || {};
  var tr1 = (sr.tracks||[])[1] || {};
  return (alert.down? '<span class="tag danger">⚠ 预测降星</span>' : '<span class="tag good">✓ 预测保星（'+esc(alert.title||'')+'）</span>');
}
function renderStaff(){
  var s=D.staff_cs||[];
  return s;
}'''
        one=patch_app(source)
        self.assertIn('var tr0 = auditStarTrack(sr);',one)
        self.assertIn('return t!==tr0;',one)
        self.assertIn('auditStarPredictionHTML(sr)',one)
        self.assertNotIn('✓ 预测保星',one)
        self.assertIn('空表不表示0人接待',one)
        self.assertEqual(patch_app(one),one)

if __name__=='__main__':unittest.main()
