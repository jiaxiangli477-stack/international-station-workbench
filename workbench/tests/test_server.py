import importlib.util
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

spec = importlib.util.spec_from_file_location('workspace_server', Path(__file__).parents[1] / 'serve.py')
server_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server_module)


class ServerRestartTests(unittest.TestCase):
    def test_transient_windows_exclusive_port_wait_is_retried_without_reuse(self):
        error=OSError('port waiting');error.winerror=10048
        expected=object()
        with patch.object(server_module,'WorkspaceServer',side_effect=[error,expected]),patch.object(server_module.time,'sleep') as pause:
            self.assertIs(server_module.open_server(('127.0.0.1',8796),object(),attempts=2),expected)
        pause.assert_called_once()

    def test_unrelated_bind_error_is_not_swallowed(self):
        with patch.object(server_module,'WorkspaceServer',side_effect=OSError('other')):
            with self.assertRaises(OSError):server_module.open_server(('127.0.0.1',8796),object(),attempts=2)


class LocalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old = (server_module.ROOT, server_module.DASHBOARD_ROOTS, server_module.REPORT_ROOT)
        shared = server_module.shared_scan
        self.old_shared = (shared.SHARE, shared.STATE, shared.CACHE, shared.INDEX)
        shared.SHARE = self.root / 'share'; shared.SHARE.mkdir()
        shared.STATE = self.root / 'state'; shared.CACHE = shared.STATE / 'cache'; shared.INDEX = shared.STATE / 'index.json'
        ui = self.root / 'ui'; ui.mkdir()
        (ui / 'index.html').write_text('workspace', encoding='utf-8')
        (ui / 'serve.py').write_text('private code', encoding='utf-8')
        dash = self.root / 'dash'; dash.mkdir()
        for name in server_module.DASHBOARD_FILES:
            (dash / name).write_text('sample asset', encoding='utf-8')
        (dash / 'private.json').write_text('not public', encoding='utf-8')
        reports = self.root / 'reports'; reports.mkdir()
        (reports / '询盘客户背调分析_20261014.html').write_text('older report', encoding='utf-8')
        (reports / '询盘客户背调分析_20261015.html').write_text('latest report', encoding='utf-8')
        (reports / 'messages.txt').write_text('private raw messages', encoding='utf-8')
        server_module.ROOT = ui
        server_module.DASHBOARD_ROOTS = {'test': ('Sample', dash)}
        server_module.REPORT_ROOT = reports
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), server_module.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        server_module.ROOT, server_module.DASHBOARD_ROOTS, server_module.REPORT_ROOT = self.old
        shared = server_module.shared_scan
        shared.SHARE, shared.STATE, shared.CACHE, shared.INDEX = self.old_shared
        self.temp.cleanup()

    def test_embedded_owner_post_uses_named_handler_and_preserves_upstream_status(self):
        import json
        import selection_service
        body=json.dumps({'query':'fixture public research'}).encode()
        with patch.object(selection_service,'request',return_value=(b'{"id":"fixture","secret":"not-public"}','application/json',202)) as upstream:
            request=Request(self.base+'/selection-app/api/selection',data=body,
                headers={'Content-Type':'application/json','X-Workbench':'1'},method='POST')
            with urlopen(request) as response:
                self.assertEqual(response.status,202)
                self.assertEqual(json.load(response),{'id':'fixture'})
        upstream.assert_called_once_with('/api/selection',method='POST',body=body)

    def test_allowed_dashboard_and_latest_report_are_readable(self):
        with urlopen(self.base + '/linked/test/index.html') as r:
            body = r.read()
            self.assertIn(b'sample asset', body)
            self.assertIn(b'jiaxiang-linked:test:', body)
            self.assertIsNone(r.headers['X-Frame-Options'])
            self.assertIn('frame-ancestors', r.headers['Content-Security-Policy'])
            self.assertIn(f'http://127.0.0.1:{self.server.server_port}', r.headers['Content-Security-Policy'])
        with urlopen(self.base + '/linked/inquiry/report.html') as r:
            self.assertIn(b'latest report', r.read())
        self.assertEqual((self.root / 'dash' / 'index.html').read_text(), 'sample asset')

    def test_private_files_and_directory_listing_are_not_exposed(self):
        for path in ['/serve.py', '/linked/test/private.json', '/linked/test/',
                     '/linked/inquiry/messages.txt', '/linked/inquiry/']:
            with self.subTest(path=path), self.assertRaises(HTTPError) as result:
                urlopen(self.base + path)
            self.assertEqual(result.exception.code, 404)

    def test_encoded_traversal_is_rejected(self):
        for path in ['/linked/test/%2e%2e/private.json', '/linked/test/%5cprivate.json',
                     '/../serve.py', '/%00index.html']:
            self.assertIsNone(server_module.resolve_public_path(path))

    def test_foreign_host_and_write_requests_are_rejected(self):
        with self.assertRaises(HTTPError) as result:
            urlopen(Request(self.base + '/', headers={'Host': 'external.example'}))
        self.assertEqual(result.exception.code, 403)
        with self.assertRaises(HTTPError) as result:
            urlopen(Request(self.base + '/api/integrations', data=b'{}', method='POST'))
        self.assertEqual(result.exception.code, 501)

    def test_registry_does_not_enable_collection_or_share_raw_paths(self):
        import json
        with urlopen(self.base + '/api/integrations') as r:
            data = json.load(r)
        self.assertFalse(data['collectionEnabled'])
        self.assertFalse(data['sharingEnabled'])
        self.assertTrue(data['dashboards'][0]['available'])
        self.assertNotIn(str(self.root / 'dash'), json.dumps(data))

    def test_shared_report_origin_cannot_read_workspace_api(self):
        with self.assertRaises(HTTPError) as result:
            urlopen(Request(self.base + '/api/integrations', headers={'Host': f'localhost:{self.server.server_port}'}))
        self.assertEqual(result.exception.code, 403)

    def test_shared_cached_html_is_embeddable_only_in_local_workspace(self):
        shared = server_module.shared_scan
        ident = 'a' * 24
        folder = shared.CACHE / ident; folder.mkdir(parents=True)
        (folder / 'index.html').write_text('<html><head></head><body>fixture</body></html>')
        shared.atomic_json(shared.INDEX, {'records': [{'id': ident, 'store': 'fixture', 'files': ['index.html']}]})
        request = Request(self.base + f'/shared/{ident}/index.html', headers={'Host': f'localhost:{self.server.server_port}'})
        with urlopen(request) as r:
            self.assertIn(b'jiaxiang-linked:shared-fixture:', r.read())
            self.assertNotIn('X-Frame-Options', r.headers)
            self.assertIn(f'http://127.0.0.1:{self.server.server_port}', r.headers['Content-Security-Policy'])

    def test_shared_scan_rejects_foreign_origin(self):
        with self.assertRaises(HTTPError) as result:
            urlopen(Request(self.base + '/api/shared/scan', data=b'{}', method='POST', headers={'Origin':'http://external.example'}))
        self.assertEqual(result.exception.code, 403)

    def test_execution_commands_require_explicit_json_and_reject_foreign_origin(self):
        for headers in ({'Content-Type':'application/json'},
                        {'Content-Type':'application/json','X-Workbench':'1','Origin':'http://external.example'}):
            with self.subTest(headers=headers), self.assertRaises(HTTPError) as result:
                urlopen(Request(self.base+'/api/operations',data=b'{"action":"product.create","title":"fixture"}',headers=headers))
            self.assertEqual(result.exception.code,403)

    def test_execution_creates_persistent_record_without_exposing_private_files(self):
        import json
        from unittest.mock import patch
        api=server_module.operations_api
        with patch.object(api.store,'DB',self.root/'operations.sqlite'),patch.object(api.store,'STATE',self.root/'operations'),patch.object(api,'kick'):
            request=Request(self.base+'/api/operations',data=json.dumps({'action':'product.create','title':'Fixture product'}).encode(),headers={'Content-Type':'application/json','X-Workbench':'1'})
            with urlopen(request) as response:
                item=json.load(response)
            with urlopen(self.base+'/api/operations') as response:
                state=json.load(response)
            self.assertEqual(state['products'][0]['id'],item['id'])
            self.assertEqual(state['products'][0]['stage'],'FACTS')
            with self.assertRaises(HTTPError) as result:
                urlopen(self.base+'/task-assets/'+'0'*32+'/executor.log')
            self.assertEqual(result.exception.code,404)

    def test_product_quality_routes_are_local_explicit_and_readonly_on_readback(self):
        import json
        api = server_module.operations_api
        summary = [{"product_id": "P-fixture", "revision": 3, "status": "completed",
                    "release_status": "HOLD", "missing_evidence": ["visual_analysis_missing"]}]
        report = {**summary[0], "run_id": "a" * 32, "confirmed_fields": {"main_ingredient": "Creatine"}}
        with patch.object(api, "quality_reports", return_value=summary, create=True), \
                patch.object(api, "quality_report", return_value=report, create=True), \
                patch.object(api, "quality_diagnose", return_value=report, create=True) as diagnose, \
                patch.object(api, "kick") as kick, \
                patch.object(server_module.Handler, "access_role", return_value="owner"):
            with urlopen(self.base + "/api/product-quality") as response:
                self.assertEqual(json.load(response), summary)
            body = json.dumps({"product_id": "P-fixture", "revision": 3}).encode()
            request = Request(self.base + "/api/product-quality/diagnose", data=body,
                              headers={"Content-Type": "application/json", "X-Workbench": "1"}, method="POST")
            with urlopen(request) as response:
                self.assertEqual(json.load(response), report)
            with urlopen(self.base + f"/api/product-quality/report/P-fixture/{'a' * 32}") as response:
                self.assertEqual(json.load(response), report)
            self.assertEqual(diagnose.call_count, 1)
            kick.assert_not_called()
        with patch.object(server_module.Handler, "access_role", return_value="viewer"):
            request = Request(self.base + "/api/product-quality/diagnose",
                              data=b'{"product_id":"P-fixture","revision":3}',
                              headers={"Content-Type": "application/json", "X-Workbench": "1"}, method="POST")
            with self.assertRaises(HTTPError) as error:
                urlopen(request)
            self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base + f"/api/product-quality/report/../{'a' * 32}")
        self.assertIn(error.exception.code, (400, 404))


if __name__ == '__main__':
    unittest.main()
