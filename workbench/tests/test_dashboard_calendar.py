import ast
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import dashboard_calendar

class DashboardCalendarTests(unittest.TestCase):
    def test_platform_date_picker_window_controls_dashboard_week(self):
        with tempfile.TemporaryDirectory(dir='D:/Codex') as tmp:
            package=Path(tmp);pipeline=package/'engine/pipeline';pipeline.mkdir(parents=True)
            workspace=package/'engine/workspace/raw';workspace.mkdir(parents=True)
            for name in ('gos_window.py','v6_fetch_monthly.py','v6_fetch_products_monthly.py','v4_judge.py'):
                shutil.copy2(Path('D:/work/boards/lifeworthcn/engine/pipeline')/name,pipeline/name)
            (workspace/'platform_native_week_windows.json').write_text(json.dumps({'windows':[{
                'start':'2026-10-18','end':'2026-10-24','statDate':'2026-10-24',
                'source':'platform-date-picker','confirmed':True,'evidence':'synthetic fixture'}]}),encoding='utf-8')
            dashboard_calendar.install(package,Path.cwd(),'2026-10-27')
            path=pipeline/'gos_window.py';spec=importlib.util.spec_from_file_location('fixture_gos_window',path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            result=module.compute(__import__('datetime').date(2026,10,27),4)
            self.assertEqual([(x['week_start'],x['week_end']) for x in result['weeks']],[('2026-10-18','2026-10-24')])
            self.assertEqual(result['weeks'][0]['tag'],'w1_20261018-1024')
            judge=(pipeline/'v4_judge.py').read_text(encoding='utf-8')
            self.assertIn("prev = wk[-2] if len(wk) > 1 else {key: None for key in latest.keys()}",judge)
            self.assertIn("PREV_END = prev.get('stat_week_end')",judge)
            self.assertIn("prev.get('stat_week_start') or '无可比周'",judge)

    def test_copied_engines_use_only_closed_calendar_months(self):
        for label in ('lifeworthcn','YH'):
            with self.subTest(label=label),tempfile.TemporaryDirectory(dir='D:/Codex') as tmp:
                package=Path(tmp);dest=package/'engine/pipeline';dest.mkdir(parents=True)
                for name in ('gos_window.py','v6_fetch_monthly.py','v6_fetch_products_monthly.py'):shutil.copy2(Path('D:/work/boards')/label/'engine/pipeline'/name,dest/name)
                dashboard_calendar.install(package,Path.cwd(),'2026-10-01')
                monthly=(dest/'v6_fetch_monthly.py').read_text('utf-8')
                self.assertIn('MONTHS = []',monthly);self.assertIn("date.fromisoformat('2026-10-01')",monthly)
                self.assertIn('dashboard_windows',(dest/'gos_window.py').read_text('utf-8'))
                self.assertNotIn("< (W.get('weeks')",(dest/'v6_fetch_products_monthly.py').read_text('utf-8'))
                dashboard_calendar.install(package,Path.cwd(),'2026-11-03')
                self.assertIn("date.fromisoformat('2026-11-03')",(dest/'v6_fetch_monthly.py').read_text('utf-8'))
    def test_original_template_package_is_never_modified(self):
        with self.assertRaises(ValueError):dashboard_calendar.install(Path('D:/work/boards/YH'),Path.cwd(),'2026-10-20')

if __name__=='__main__':unittest.main()
