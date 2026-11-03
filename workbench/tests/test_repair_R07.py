"""Offline origin and pinned transport regressions; never imports serve."""
import ast
import io
from pathlib import Path
from types import SimpleNamespace
import socket
import ssl
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit, unquote, parse_qs, quote
import public_checks as pc

ROOT = Path(__file__).resolve().parents[1]

def handler_methods():
    tree = ast.parse((ROOT/'serve.py').read_text(encoding='utf-8-sig'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Handler')
    names = {'send_head', 'end_headers', 'do_POST'}
    nodes = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    ns = dict(urlsplit=urlsplit, unquote=unquote, parse_qs=parse_qs, quote=quote,
              TEAM=SimpleNamespace(enabled=True, ip='192.168.1.2'),
              resolve_public_path=lambda _: SimpleNamespace(is_file=lambda: True, suffix='.js',
                  open=lambda _: io.BytesIO(b'alert(1)'), stat=lambda: SimpleNamespace(st_size=8)))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'serve.py', 'exec'), ns)
    return ns

def request(path, host='127.0.0.1', role='owner'):
    result = SimpleNamespace(path=path, headers={'Host':host+':18796'},
        server=SimpleNamespace(server_port=18796), command='GET', wfile=io.BytesIO(),
        status=None, response_headers={})
    result.allowed_host=lambda: True
    result.access_role=lambda: role
    result.send_response=lambda value: setattr(result, 'status', value)
    result.send_error=lambda value, *args: setattr(result, 'status', value)
    result.send_header=lambda key, value: result.response_headers.__setitem__(key, value)
    result.end_headers=lambda: None
    result.guess_type=lambda _: 'application/javascript'
    return result

class OriginTests(unittest.TestCase):
    def test_owner_never_serves_report_html_or_js(self):
        for path in ('/shared/abc/index.html','/shared/abc/app.js','/linked/yh/index.html','/linked/yh/app.js'):
            with self.subTest(path=path):
                obj=request(path)
                self.assertIsNone(handler_methods()['send_head'](obj))
                self.assertEqual(obj.status,302)
                self.assertEqual(obj.response_headers['Location'],'http://localhost:18796'+path)

    def test_localhost_reports_allowed_but_admin_api_and_popup_denied(self):
        for path in ('/shared/abc/app.js','/linked/yh/app.js'):
            obj=request(path,'localhost','report')
            self.assertEqual(handler_methods()['send_head'](obj).read(), b'alert(1)')
        for path in ('/api/operations','/api/dashboard/manual','/dashboard-manual.html'):
            obj=request(path,'localhost','report')
            self.assertIsNone(handler_methods()['send_head'](obj))
            self.assertEqual(obj.status,403)

    def test_encoded_report_path_also_redirects(self):
        obj=request('/%73hared/abc/app.js')
        self.assertIsNone(handler_methods()['send_head'](obj))
        self.assertEqual(obj.status,302)

    def test_viewer_response_sandbox_and_report_framing(self):
        tree=ast.parse((ROOT/'serve.py').read_text(encoding='utf-8-sig'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Handler')
        cls.body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='end_headers']
        base=type('Base',(),{'end_headers':lambda self: None})
        ns=dict(SimpleHTTPRequestHandler=base,urlsplit=urlsplit,unquote=unquote,
                TEAM=SimpleNamespace(enabled=True,ip='192.168.1.2'))
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'serve.py','exec'),ns)
        for role in ('viewer','report'):
            obj=ns['Handler']()
            fake=request('/linked/yh/index.html','localhost',role)
            del fake.end_headers
            obj.__dict__.update(fake.__dict__)
            obj.end_headers()
            policy=obj.response_headers['Content-Security-Policy']
            self.assertIn('frame-ancestors http://127.0.0.1:18796 http://localhost:18796',policy)
            self.assertNotIn('X-Frame-Options',obj.response_headers)
            if role=='viewer':
                self.assertIn('; sandbox allow-scripts',policy)
                self.assertNotIn('allow-same-origin',policy)
            else:self.assertNotIn('; sandbox',policy)

class TransportTests(unittest.TestCase):
    def test_dns_rebinding_cannot_change_connection_target(self):
        good=(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',80))
        bad=(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',80))
        sock=Mock()
        with patch.object(pc.socket,'getaddrinfo',side_effect=[[good],[bad]]) as dns, patch.object(pc.socket,'socket',return_value=sock):
            conn=pc.PublicHTTPConnection('example.com',timeout=3)
            conn.connect()
        self.assertEqual(dns.call_count,1)
        sock.connect.assert_called_once_with(('93.184.216.34',80))
        self.assertEqual(conn.host,'example.com')

    def test_private_results_fail_before_socket_creation(self):
        for ip in ('127.0.0.1','10.0.0.1','169.254.169.254'):
            with self.subTest(ip=ip), patch.object(pc.socket,'getaddrinfo',return_value=[(2,1,6,'',(ip,80))]), patch.object(pc.socket,'socket') as create:
                with self.assertRaises(ValueError):pc.PublicHTTPConnection('example.com').connect()
                create.assert_not_called()

    def test_https_preserves_sni_and_requires_valid_certificates(self):
        ctx=ssl.create_default_context()
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode,ssl.CERT_REQUIRED)
        sock=Mock()
        with patch.object(pc,'_public_socket',return_value=sock), patch.object(ctx,'wrap_socket',return_value=Mock()) as wrap:
            pc.PublicHTTPSConnection('example.com',context=ctx).connect()
        wrap.assert_called_once_with(sock,server_hostname='example.com')

    def test_redirect_revalidates_private_destination(self):
        from urllib.request import Request
        with self.assertRaises(ValueError):
            pc.PublicRedirect().redirect_request(Request('https://example.com'),None,302,'',{},'http://127.0.0.1/')

    def test_https_rejects_disabled_certificate_validation_before_connect(self):
        ctx=ssl._create_unverified_context()
        with patch.object(pc,'_public_socket') as connect:
            with self.assertRaises(ValueError):pc.PublicHTTPSConnection('example.com',context=ctx).connect()
        connect.assert_not_called()

    def test_opener_disables_environment_proxies(self):
        from urllib.request import ProxyHandler
        with patch.dict('os.environ',{'HTTP_PROXY':'http://127.0.0.1:8888','HTTPS_PROXY':'http://127.0.0.1:8888'}):
            opener=pc.build_public_opener()
        self.assertFalse(any(isinstance(h,ProxyHandler) and h.proxies for h in opener.handlers))

    def test_both_handlers_use_pinned_transport_after_redirect(self):
        from urllib.request import Request
        for handler,url,connection in ((pc.PublicHTTPHandler(),'http://example.com',pc.PublicHTTPConnection),
                (pc.PublicHTTPSHandler(context=ssl.create_default_context()),'https://example.com',pc.PublicHTTPSConnection)):
            handler.do_open=Mock(return_value='mock response')
            req=Request(url)
            with patch.object(pc,'require_public_url') as validate:
                result=handler.http_open(req) if url.startswith('http:') else handler.https_open(req)
            validate.assert_called_once_with(url)
            self.assertIs(handler.do_open.call_args.args[0],connection)
            self.assertEqual(result,'mock response')

    def test_adapter_replaces_proxy_opener_not_only_dns_precheck(self):
        import inquiry_release
        source='import urllib.request\nfrom public_checks import build_public_opener\ndef _opener():\n return urllib.request.build_opener(urllib.request.ProxyHandler({"http":"private-proxy"}))\n'
        adapted=inquiry_release.secure_public_verifier(source)
        self.assertIn('return build_public_opener()',adapted)
        self.assertNotIn('private-proxy',adapted)
        with self.assertRaises(Exception):inquiry_release.secure_public_verifier('pass')

if __name__=='__main__':unittest.main()
