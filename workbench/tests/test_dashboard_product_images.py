from contextlib import closing
import ast
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dashboard_product_images import fill_from_snapshot


class SnapshotImagesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'raw').mkdir()
        (self.root / 'database').mkdir()
        self.db = self.root / 'database/alibaba_growth.db'
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('CREATE TABLE products(product_id TEXT,main_image TEXT)')
            c.execute("INSERT INTO products VALUES('fixture-product','old')")
            c.execute('CREATE TABLE store_weekly_stats(stat_week_start TEXT,stat_week_end TEXT)')
            c.execute("INSERT INTO store_weekly_stats VALUES('2026-10-12','2026-10-18')")
        self.write('_window.json', {'weeks':[{'week_start':'2026-10-12','week_end':'2026-10-18'}]})
        self.page = {'success':True,'data':{'recordCount':1,'data':[{'id':'fixture-product','prodImage':'https://example.com/image_100x100.jpg'}]}}
        self.write('shop_product_w1_p01.json', self.page)

    def write(self, name, data):
        (self.root / 'raw' / name).write_text(json.dumps(data), encoding='utf-8')

    def test_complete_snapshot_updates_images_without_external_calls(self):
        result = fill_from_snapshot(self.root)
        self.assertEqual(result['products'], 1)
        with closing(sqlite3.connect(self.db)) as c, c:
            self.assertEqual(c.execute('SELECT main_image FROM products').fetchone()[0], 'https://example.com/image_300x300.jpg')

    def test_missing_declared_rows_rejected_before_database_update(self):
        self.page['data']['recordCount'] = 2
        self.write('shop_product_w1_p01.json', self.page)
        with self.assertRaises(ValueError): fill_from_snapshot(self.root)
        with closing(sqlite3.connect(self.db)) as c, c:
            self.assertEqual(c.execute('SELECT main_image FROM products').fetchone()[0], 'old')

    def test_wrong_period_rejected(self):
        self.write('_window.json', {'weeks':[{'week_start':'2026-10-05','week_end':'2026-10-11'}]})
        with self.assertRaises(ValueError): fill_from_snapshot(self.root)

    def test_failed_response_rejected(self):
        self.page['success'] = False
        self.write('shop_product_w1_p01.json', self.page)
        with self.assertRaises(ValueError): fill_from_snapshot(self.root)

    def test_duplicate_products_or_page_gap_rejected(self):
        self.write('shop_product_w1_p03.json', self.page)
        with self.assertRaises(ValueError): fill_from_snapshot(self.root)
        (self.root/'raw/shop_product_w1_p03.json').unlink()
        self.write('shop_product_w1_p02.json', self.page)
        with self.assertRaises(ValueError): fill_from_snapshot(self.root)

    def test_weekly_adapter_routes_image_step_to_snapshot_with_identity_guards(self):
        source = Path(__file__).resolve().parents[1] / 'weekly_dashboard_adapter.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        function = next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='guarded_run')
        original, identity = Mock(return_value=True), Mock()
        import os,sys
        refresh=Mock(return_value={})
        context = {'require_identity':identity,'bridge':self.root,'identity':self.root/'identity.json',
                   'args':SimpleNamespace(expected='fixture',workspace_code=str(self.root)),
                   'Path':Path,'sys':sys,'os':os,'bridge_runtime':SimpleNamespace(child_environment=refresh),'original':original}
        exec(compile(ast.Module(body=[function],type_ignores=[]),str(source),'exec'),context)
        self.assertTrue(context['guarded_run']([sys.executable,'v6_fetch_imgs.py'],str(self.root),'D1',1800))
        self.assertEqual(identity.call_count,2)
        command = original.call_args.args[0]
        self.assertEqual(Path(command[1]).name,'dashboard_product_images.py')
        self.assertEqual(command[-1],str(self.root))

    def test_weekly_adapter_refreshes_local_gateway_environment_per_step(self):
        source = Path(__file__).resolve().parents[1] / 'weekly_dashboard_adapter.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        function = next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='guarded_run')
        import os,sys
        original = Mock(side_effect=lambda *a,**k: os.environ.get('ACCIO_GATEWAY_TOKEN')=='fixture-current')
        refresh = Mock(return_value={'ACCIO_GATEWAY_TOKEN':'fixture-current','ACCIO_GATEWAY_USERNAME':'fixture-user','ACCIO_LOCAL_GATEWAY_URL':'http://localhost:4097'})
        context={'require_identity':Mock(),'bridge_runtime':SimpleNamespace(child_environment=refresh),
                 'bridge':self.root,'identity':self.root/'identity.json','args':SimpleNamespace(expected='fixture',workspace_code=str(self.root)),
                 'Path':Path,'sys':sys,'os':os,'original':original}
        exec(compile(ast.Module(body=[function],type_ignores=[]),str(source),'exec'),context)
        with patch.dict(os.environ,{'ACCIO_GATEWAY_TOKEN':'fixture-stale','ACCIO_LOCAL_GATEWAY_URL':'http://localhost:4097'},clear=False):
            self.assertTrue(context['guarded_run']([sys.executable,'step.py'],str(self.root),'step',60))
            self.assertEqual(os.environ['ACCIO_GATEWAY_TOKEN'],'fixture-stale')
        refresh.assert_called_once()

    def test_native_week_manifest_is_used_for_image_fill_without_second_api_fetch(self):
        from dashboard_native_week import collect_week
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("INSERT INTO products VALUES('1600000000001','old-native')")
            c.execute('DELETE FROM store_weekly_stats')
            c.execute("INSERT INTO store_weekly_stats VALUES('2026-10-18','2026-10-24')")
        self.write('_window.json',{'weeks':[{'week_start':'2026-10-18','week_end':'2026-10-24'}]})
        (self.root/'stores.json').write_text(json.dumps({'active':'lifeworthcn','stores':{'lifeworthcn':{'store_id':'123'}}}),encoding='utf-8')
        self.write('platform_native_week_windows.json',{'windows':[{'start':'2026-10-18','end':'2026-10-24','statDate':'2026-10-24','source':'platform-date-picker','confirmed':True,'evidence':'synthetic fixture','store_id':'123'}]})
        def call(tool,payload):
            q=payload['shopProductQueryParam'];i=q['pageNo']
            rows=[{'id':'1600000000001','prodImage':'https://example.com/image_100x100.jpg','prodName':'Fixture'}] if i==1 else []
            return {'success':True,'data':{'recordCount':1,'data':rows,'downloadUrl':'https://example.invalid/?statisticsType=week&statDate=2026-10-24'}}
        collect_week(self.root,'123','2026-10-18','2026-10-24',call)
        result=fill_from_snapshot(self.root)
        self.assertEqual(result['source'],'verified-platform-native-week')
        with closing(sqlite3.connect(self.db)) as c, c:
            self.assertEqual(c.execute("SELECT main_image FROM products WHERE product_id='1600000000001'").fetchone()[0],'https://example.com/image_300x300.jpg')
