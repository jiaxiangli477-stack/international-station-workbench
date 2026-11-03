"""Local launch and transport tests; no browser, network, account or platform calls."""
import io
import ast
import json
import os
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import listing_browser as browser


class ListingBrowserTests(unittest.TestCase):
    def test_status_command_is_read_only_and_does_not_launch_or_require_product(self):
        source=Path(browser.__file__).with_name('operations_api.py').read_text(encoding='utf-8-sig')
        node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='command')
        status=Mock(return_value={'status':'DISCONNECTED','accountVerified':False})
        namespace={'store':SimpleNamespace(product=Mock(side_effect=AssertionError('must not load or edit product')))}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'operations_api.py','exec'),namespace)
        with patch.dict(sys.modules,{'single_approval_flow':SimpleNamespace(),'listing_browser':SimpleNamespace(status=status)}):
            self.assertEqual(namespace['command']({'action':'listing.browser.status'})['status'],'DISCONNECTED')
        status.assert_called_once()

    def test_status_separates_connection_login_and_backend_without_claiming_identity(self):
        for url,expected in [('https://login.alibaba.com/newlogin','LOGIN_REQUIRED'),
                             ('about:blank','CONNECTING'),
                             ('https://post.alibaba.com/product/publish.htm','READY')]:
            opener=Mock();opener.open.return_value=io.BytesIO(json.dumps([{'type':'page','url':url}]).encode())
            with patch.object(browser,'ready',return_value=True),patch.object(browser,'build_opener',return_value=opener):
                result=browser.status()
            self.assertEqual(result['status'],expected)
            self.assertFalse(result['accountVerified'])
            self.assertNotIn('pages',result)
        with patch.object(browser,'ready',return_value=False):
            self.assertEqual(browser.status()['status'],'DISCONNECTED')

    def test_explicit_listing_recovers_a_closed_browser_once_and_waits_for_backend(self):
        states=[{'status':'DISCONNECTED'},{'status':'CONNECTING'},{'status':'READY'}]
        product={'id':'fixture'}
        with patch.object(browser,'status',side_effect=states),patch.object(browser,'open_browser') as launch, \
             patch.object(browser.time,'sleep'):
            self.assertEqual(browser.ensure_ready(product)['status'],'READY')
        launch.assert_called_once_with(product)

    def test_recovery_never_reopens_ready_session_or_pretends_login_is_ready(self):
        with patch.object(browser,'status',return_value={'status':'READY'}),patch.object(browser,'open_browser') as launch:
            self.assertEqual(browser.ensure_ready({})['status'],'READY');launch.assert_not_called()
        with patch.object(browser,'status',side_effect=[{'status':'DISCONNECTED'},{'status':'LOGIN_REQUIRED'}]), \
             patch.object(browser,'open_browser') as launch:
            with self.assertRaisesRegex(ValueError,'登录.*未开始上传或保存'):browser.ensure_ready({})
            launch.assert_called_once()
        with patch.object(browser,'status',return_value={'status':'CONNECTING'}),patch.object(browser,'open_browser') as launch:
            with self.assertRaisesRegex(ValueError,'未开始上传或保存'):browser.ensure_ready({},timeout=0)
            launch.assert_not_called()

    def test_workbench_open_command_requires_current_product_revision(self):
        source=Path(browser.__file__).with_name('operations_api.py').read_text(encoding='utf-8-sig')
        node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='command')
        product={'id':'fixture','revision':6};launch=Mock(return_value={'status':'OPENING'})
        namespace={'store':SimpleNamespace(product=Mock(return_value=product))}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'operations_api.py','exec'),namespace)
        with patch.dict(sys.modules,{'single_approval_flow':SimpleNamespace(),'listing_browser':SimpleNamespace(open_browser=launch)}):
            self.assertEqual(namespace['command']({'action':'listing.browser.open','id':'fixture','revision':6})['status'],'OPENING')
            with self.assertRaisesRegex(ValueError,'版本已变化'):
                namespace['command']({'action':'listing.browser.open','id':'fixture','revision':5})
        launch.assert_called_once_with(product)

    def test_ready_accepts_only_expected_loopback_transport(self):
        info={'Browser':'Edg/141.0','webSocketDebuggerUrl':'ws://127.0.0.1:9322/devtools/browser/fixture'}
        for endpoint,expected in [(info['webSocketDebuggerUrl'],True),('ws://example.test:9322/x',False),
                                  ('ws://127.0.0.1:9222/x',False),('ws://user:pass@127.0.0.1:9322/x',False)]:
            opener=Mock();opener.open.return_value=io.BytesIO(json.dumps(dict(info,webSocketDebuggerUrl=endpoint)).encode())
            with patch.object(browser,'build_opener',return_value=opener):self.assertEqual(browser.ready(),expected)
            self.assertEqual(opener.open.call_args.args[0],'http://127.0.0.1:9322/json/version')

    def test_disconnected_browser_blocks_without_launching(self):
        with patch.object(browser,'ready',return_value=False),patch.object(browser.subprocess,'Popen') as launch:
            with self.assertRaisesRegex(ValueError,'未开始上传或保存'):browser.require_ready()
            launch.assert_not_called()

    def test_readiness_requires_backend_tab_but_never_claims_account_verification(self):
        for url,allowed in [('https://login.alibaba.com/newlogin',False),
                            ('about:blank',False),('https://post.alibaba.com/product/publish.htm',True)]:
            opener=Mock();opener.open.return_value=io.BytesIO(json.dumps([{'type':'page','url':url}]).encode())
            with patch.object(browser,'ready',return_value=True),patch.object(browser,'build_opener',return_value=opener):
                if allowed:self.assertIsNone(browser.require_ready())
                else:
                    with self.assertRaisesRegex(ValueError,'未开始上传或保存'):browser.require_ready()

    def test_connected_browser_is_reused_without_profile_or_process_changes(self):
        with patch.object(browser,'ready',return_value=True),patch.object(browser.subprocess,'Popen') as launch:
            self.assertEqual(browser.open_browser({})['status'],'READY');launch.assert_not_called()

    def test_explicit_open_uses_existing_browser_and_project_profile_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);exe=root/'programs/Microsoft/Edge/Application/msedge.exe'
            exe.parent.mkdir(parents=True);exe.write_text('offline fixture')
            with patch.object(browser,'ready',return_value=False),patch.object(browser.store,'STATE',root/'state'),patch.dict(os.environ,{'PROGRAMFILES(X86)':str(root/'programs'),'PROGRAMFILES':''}),patch.object(browser.subprocess,'Popen') as launch:
                result=browser.open_browser({'listingSkill':{'category_id':'202029902'}})
                self.assertEqual(result['status'],'OPENING');args=launch.call_args.args[0]
                self.assertEqual(args[0],str(exe));self.assertIn('--user-data-dir='+str(root/'state/listing-browser-profile'),args)
                self.assertIn('--remote-debugging-port=9322',args);self.assertTrue(args[-1].endswith('?catId=202029902'))
                self.assertNotIn('shell',launch.call_args.kwargs)


if __name__=='__main__':unittest.main()
