import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import date
import weekly_update as weekly


class WeeklyAdapterTests(unittest.TestCase):
    def test_bridge_stage_reuses_shims_without_copying_credential_files(self):
        with tempfile.TemporaryDirectory(dir='D:/Codex') as tmp:
            root=Path(tmp);source=root/'.state'/'yh-check'/'bridge';binary=source/'bin';binary.mkdir(parents=True)
            (source/'setup_env.py').write_text('# fixture',encoding='utf-8')
            for name in ('workctl','workctl.cmd','accio-mcp-cli','accio-mcp-cli.cmd','_token.cmd','_token.sh'):
                (binary/name).write_text('fixture',encoding='utf-8')
            with patch.object(weekly,'ROOT',root):
                target=weekly.prepare_bridge(root/'runs'/'bridge')
            self.assertTrue((target/'workctl.cmd').is_file())
            self.assertTrue((target/'accio-mcp-cli.cmd').is_file())
            self.assertFalse(any(p.name.lower().startswith('_token') for p in target.iterdir()))

    def test_store_passes_current_bridge_credentials_to_nested_cli_children(self):
        seen=[]
        def stop_after_window(engine,bridge,expected,period,env=None,**kwargs):
            seen.append(env)
            raise weekly.SyncError('fixture stops before network')
        with tempfile.TemporaryDirectory(dir='D:/Codex') as tmp,patch.object(weekly,'require_identity'),patch.object(weekly,'prepare_inquiry'),patch.object(weekly,'prepare_dashboard',side_effect=weekly.SyncError('fixture')),patch.object(weekly.catalog,'atomic_json'),patch('bridge_runtime.child_environment',side_effect=lambda executable,env:dict(env,ACCIO_GATEWAY_TOKEN='fixture-token')),patch('inquiry_calendar.collect',side_effect=stop_after_window):
            weekly.do_store('youhealth',{'expected_id':'123','folder':'Youhealth','label':'fixture'},Path(tmp),Path(tmp)/'bridge',date(2026,10,20))
        self.assertEqual(seen[0]['ACCIO_GATEWAY_TOKEN'],'fixture-token')

    def test_tuesday_scheduler_passes_complete_natural_week_to_collector(self):
        seen=[]
        def stop_after_window(engine,bridge,expected,period,**kwargs):
            seen.append(period);raise weekly.SyncError('fixture stops before network')
        with tempfile.TemporaryDirectory(dir='D:/Codex') as tmp,patch.object(weekly,'require_identity'),patch.object(weekly,'prepare_inquiry'),patch.object(weekly,'prepare_dashboard',side_effect=weekly.SyncError('fixture')),patch.object(weekly.catalog,'atomic_json'),patch('inquiry_calendar.collect',side_effect=stop_after_window):
            result=weekly.do_store('youhealth',{'expected_id':'123','folder':'Youhealth','label':'fixture'},Path(tmp),Path(tmp)/'bridge',date(2026,10,20))
        self.assertEqual(seen,[{'start':'2026-10-12','end':'2026-10-18'}])
        self.assertEqual(result['period'],seen[0])

    def test_dashboard_uses_confirmed_platform_windows_without_relabeling_inquiry_week(self):
        with tempfile.TemporaryDirectory(dir='D:/Codex') as tmp:
            root=Path(tmp);dashboard=root/'board';proof=dashboard/'engine'/'workspace'/'raw'/'platform_native_week_windows.json'
            proof.parent.mkdir(parents=True)
            proof.write_text('{"windows":[{"start":"2026-10-18","end":"2026-10-24","statDate":"2026-10-24","source":"platform-date-picker","confirmed":true,"evidence":"fixture"}]}',encoding='utf-8')
            cfg={'dashboard':dashboard}
            self.assertEqual(weekly.dashboard_requested_windows(cfg,date(2026,10,27)),[
                {'week_start':'2026-10-18','week_end':'2026-10-24'}])
    def test_prior_customer_judgments_are_not_carried_to_new_runs(self):
        source = "ANALYSIS={'old':{'grade':'A'}}\nSTRENGTH={'old':{}}\nCOMPANIES={'old':{}}\nASK={'_default':{'need':[]},'old':{'need':['private']}}"
        tree = ast.fix_missing_locations(weekly.RemovePriorCustomers().visit(ast.parse(source)))
        values = {}; exec(compile(tree, '<fixture>', 'exec'), values)
        self.assertEqual(values['ANALYSIS'], {})
        self.assertEqual(values['STRENGTH'], {})
        self.assertEqual(values['COMPANIES'], {})
        self.assertEqual(list(values['ASK']), ['_default'])

    def test_seven_day_window_and_partial_failure_guards_are_patched(self):
        source = "import time\ndef run(args, timeout=1800):\n    r = subprocess.run(args, capture_output=True, text=True, encoding='utf-8',\n                       errors='replace', shell=True, timeout=timeout, env=env(), cwd=HERE)\n    return r.returncode, r.stdout\nstart = time.strftime('%Y-%m-%d', time.localtime(time.time() - args.days * 86400))\ndef main():\n    convs = []\n    msg_file = ''\n    msgs = {c.get('conversationId'): (c.get('messages') or [])\n            for c in ((jload(msg_file) or {}).get('conversations') or [])}\n    for c in convs:\n        ms = msgs.get(c.get('conversationId')) or []\n        norm.append({'messages': [{'sendTime': m.get('time')} for m in ms]})\n    d = jparse(out)\n    d2 = jparse(out)\n"
        result = weekly.patch_inquiry_source(source)
        self.assertIn('args.days - 1', result)
        self.assertIn("d.get('status') != 'success'", result)
        self.assertIn("d2.get('status') != 'success'", result)
        self.assertIn('list-conversation-msg-time-range', result)
        self.assertIn('account_scoped_messages', result)
        self.assertIn("sellerAliId", result)
        self.assertIn("cwd=os.path.splitdrive(HERE)[0] + os.sep", result)
        self.assertIn('stamp = stamp / 1000 if stamp > 1e11 else stamp', result)
        self.assertIn("'sendTime': normalize_timestamp(m.get('time'))", result)

    def test_unknown_skill_version_fails_before_execution(self):
        with self.assertRaises(weekly.SyncError):
            weekly.patch_inquiry_source('print("changed source")')

    def test_publishing_never_overwrites_existing_period_or_escapes_share(self):
        old = weekly.catalog.SHARE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); share = root / 'share'; share.mkdir()
                weekly.catalog.SHARE = share
                source = root / 'report.html'; source.write_text('fixture')
                first = weekly.publish_files([(source, 'report.html')], share / 'store', 'period-1')
                self.assertEqual((first / 'report.html').read_text(), 'fixture')
                with self.assertRaises(weekly.SyncError):
                    weekly.publish_files([(source, 'report.html')], share / 'store', 'period-1')
                with self.assertRaises(weekly.SyncError):
                    weekly.publish_files([(source, 'report.html')], root / 'outside', 'period-2')
        finally:
            weekly.catalog.SHARE = old


if __name__ == '__main__':
    unittest.main()
