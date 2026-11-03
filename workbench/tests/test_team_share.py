from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen
import serve
import team_share

class TeamShareTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.gate=team_share.TeamGate(enabled=True,state=Path(self.tmp.name),ip='192.168.2.153')
        self.original=serve.TEAM;serve.TEAM=self.gate
        self.server=ThreadingHTTPServer(('127.0.0.1',0),serve.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.port=self.server.server_port;self.base=f'http://127.0.0.1:{self.port}'
        self.lan_host=f'192.168.2.153:{self.port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();serve.TEAM=self.original;self.tmp.cleanup()
    def post(self,path,data,lan=False,cookie=None):
        headers={'Content-Type':'application/json','X-Workbench':'1'}
        if lan:headers['Host']=self.lan_host
        if cookie:headers['Cookie']=cookie
        return urlopen(Request(self.base+path,data=json.dumps(data).encode(),headers=headers))
    def session(self):
        with self.post('/api/team/invite',{}) as response:invite=json.load(response)
        code=invite['url'].split('#invite=')[1]
        with self.post('/api/team/session',{'code':code},lan=True) as response:
            return response.headers['Set-Cookie'].split(';',1)[0]
    def test_complete_selection_view_does_not_grant_generation_or_proxy_writes(self):
        self.gate.auth_required=False
        with urlopen(Request(self.base+'/api/team/status',headers={'Host':self.lan_host})) as response:
            self.assertEqual(json.load(response)['role'],'viewer')
        with patch('selection_readonly.resource',return_value=(b'full selection readonly','text/html')):
            with urlopen(Request(self.base+'/selection-app/',headers={'Host':self.lan_host})) as response:
                self.assertIn(b'full selection readonly',response.read())
        with patch.object(serve.operations_api,'command') as command:
            for path,action in [('/api/operations','selection.preview'),('/api/operations','selection.start'),('/api/operations','topic.images.start'),('/selection-app/api/start','start')]:
                with self.assertRaises(HTTPError) as error:self.post(path,{'action':action},lan=True)
                self.assertEqual(error.exception.code,403)
            command.assert_not_called()
    def test_anonymous_lan_gets_login_but_cannot_read_operations_or_reports(self):
        with urlopen(Request(self.base+'/',headers={'Host':self.lan_host})) as response:
            self.assertIn('团队查看'.encode(),response.read())
        for path in ('/api/operations','/shared/'+'0'*24+'/index.html','/api/integrations'):
            with self.assertRaises(HTTPError) as error:urlopen(Request(self.base+path,headers={'Host':self.lan_host}))
            self.assertEqual(error.exception.code,401)
    def test_authenticated_viewer_can_read_but_no_command_or_share_admin(self):
        cookie=self.session()
        with urlopen(Request(self.base+'/api/team/status',headers={'Host':self.lan_host,'Cookie':cookie})) as response:
            status=json.load(response)
        self.assertEqual(status['role'],'viewer');self.assertFalse(status['permissions']['execute'])
        with patch.object(serve.operations_api,'overview',return_value={'products':[]}):
            with urlopen(Request(self.base+'/api/operations',headers={'Host':self.lan_host,'Cookie':cookie})) as response:
                self.assertEqual(json.load(response),{'products':[]})
        for path,data in (('/api/operations',{'action':'product.create','title':'forbidden'}),('/api/team/invite',{}),('/api/shared/scan',{}),('/selection-app/api/selection',{})):
            with self.assertRaises(HTTPError) as error:self.post(path,data,lan=True,cookie=cookie)
            self.assertEqual(error.exception.code,403)
    def test_invite_rotation_invalidates_prior_sessions_and_forged_cookies_fail(self):
        cookie=self.session();self.assertEqual(self.gate.role('192.168.2.20','192.168.2.153',cookie),'viewer')
        self.gate.issue(self.port)
        self.assertIsNone(self.gate.role('192.168.2.20','192.168.2.153',cookie))
        self.assertIsNone(self.gate.role('192.168.2.20','127.0.0.1','jiaxiang_view_session=forged'))
        self.assertFalse(self.gate.peer_ok('10.40.1.20'))
    def test_lan_host_from_loopback_is_not_an_owner_shortcut(self):
        self.assertEqual(self.gate.role('127.0.0.1','127.0.0.1',''),'owner')
        self.assertIsNone(self.gate.role('127.0.0.1','192.168.2.153',''))
        self.assertEqual(self.gate.role('127.0.0.1','localhost',''),'report')
    def test_selection_view_is_a_read_projection_not_owner_proxy(self):
        cookie=self.session()
        with patch.object(team_share,'readonly_selection',return_value='<h1>read-only selection</h1>'):
            with urlopen(Request(self.base+'/team/selection',headers={'Host':self.lan_host,'Cookie':cookie})) as response:
                self.assertIn(b'read-only selection',response.read())
    def test_direct_lan_view_needs_no_cookie_but_keeps_write_and_network_limits(self):
        self.gate.auth_required=False
        with urlopen(Request(self.base+'/',headers={'Host':self.lan_host})) as response:
            html=response.read()
        self.assertNotIn('查看口令'.encode(),html)
        self.assertIn('国际站运营工作台'.encode(),html)
        with urlopen(Request(self.base+'/api/team/status',headers={'Host':self.lan_host})) as response:
            status=json.load(response)
        self.assertEqual(status['role'],'viewer');self.assertFalse(status['authRequired'])
        with patch.object(serve.operations_api,'overview',return_value={'products':[]}):
            with urlopen(Request(self.base+'/api/operations',headers={'Host':self.lan_host})) as response:
                self.assertEqual(json.load(response),{'products':[]})
        for path in ('/api/operations','/api/shared/scan'):
            with self.assertRaises(HTTPError) as error:self.post(path,{'action':'product.create'},lan=True)
            self.assertEqual(error.exception.code,403)
        self.assertFalse(self.gate.peer_ok('10.40.1.20'))
        self.assertEqual(self.gate.issue(self.port)['url'],f'http://192.168.2.153:{self.port}/')

    def test_routed_colleague_address_needs_explicit_viewer_allowlist(self):
        self.assertFalse(self.gate.peer_ok('192.168.8.74'))
        gate=team_share.TeamGate(enabled=True,state=Path(self.tmp.name),ip='192.168.2.153',
                                 auth_required=False,viewer_networks=['192.168.8.74/32'])
        self.assertTrue(gate.peer_ok('192.168.8.74'))
        self.assertFalse(gate.peer_ok('192.168.8.75'))
        self.assertEqual(gate.role('192.168.8.74','127.0.0.1',''),'viewer')
        self.assertFalse(gate.local_owner('192.168.8.74','127.0.0.1'))
        for value in ('0.0.0.0/0','8.8.8.8/32','100.64.0.0/10','127.0.0.0/8','::/0'):
            with self.assertRaises(ValueError):
                team_share.TeamGate(enabled=True,state=Path(self.tmp.name),viewer_networks=[value])

    def test_office_lan_mode_covers_wired_and_wifi_without_individual_registration(self):
        gate=team_share.TeamGate(enabled=True,state=Path(self.tmp.name),ip='192.168.2.153',
                                 auth_required=False,viewer_networks=['192.168.0.0/16','10.0.0.0/8','172.16.0.0/12'])
        for peer in ('192.168.2.42','192.168.8.74','192.168.8.75','10.40.1.20','172.20.1.30'):
            self.assertEqual(gate.role(peer,'192.168.2.153',''),'viewer')
            self.assertFalse(gate.local_owner(peer,'127.0.0.1'))
        self.assertFalse(gate.peer_ok('8.8.8.8'))

    def test_http_from_routed_viewer_can_read_but_cannot_execute(self):
        serve.TEAM=team_share.TeamGate(enabled=True,state=Path(self.tmp.name),ip='192.168.2.153',
                                      auth_required=False,viewer_networks=['192.168.8.74/32'])
        class RoutedHandler(serve.Handler):
            def setup(self):
                super().setup()
                self.client_address=('192.168.8.74',12345)
        self.server.RequestHandlerClass=RoutedHandler
        with urlopen(Request(self.base+'/',headers={'Host':self.lan_host})) as response:
            self.assertEqual(response.status,200)
        with urlopen(Request(self.base+'/api/team/status',headers={'Host':self.lan_host})) as response:
            self.assertEqual(json.load(response)['role'],'viewer')
        with patch.object(serve.operations_api,'command') as command:
            with self.assertRaises(HTTPError) as error:self.post('/api/operations',{},lan=True)
            self.assertEqual(error.exception.code,403)
            command.assert_not_called()

if __name__=='__main__':unittest.main()
