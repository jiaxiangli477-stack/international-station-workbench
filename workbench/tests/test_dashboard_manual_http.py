from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen
import dashboard_manual as manual
import serve
import team_share

class ManualHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir='D:/Codex');self.db=Path(self.temp.name)/'archive.sqlite3'
        self.gate=team_share.TeamGate(enabled=True,auth_required=False,state=Path(self.temp.name)/'team',ip='192.168.2.153')
        self.old=serve.TEAM;serve.TEAM=self.gate
        original=manual.command
        self.command_patch=patch.object(serve.dashboard_manual,'command',side_effect=lambda p:original(p,db=self.db));self.command_patch.start()
        self.stores_patch=patch('weekly_update.STORES',{'store1':{'expected_id':'store1'}});self.stores_patch.start()
        self.index_patch=patch('shared_scan.read_index',return_value={'records':[{'id':'a'*24,'store':'store1','kind':'data','rows':[{'kind':'week','start':'2026-10-12','end':'2026-10-18'}]}]});self.index_patch.start()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),serve.Handler);self.port=self.server.server_port
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.payload={'store':'store1','kind':'week','start':'2026-10-12','end':'2026-10-18','snapshot':'a'*24,'action':'save','changes':{'new_count':65},'revision':0}
    def tearDown(self):
        self.server.shutdown();self.server.server_close();serve.TEAM=self.old
        self.command_patch.stop();self.stores_patch.stop();self.index_patch.stop();self.temp.cleanup()
    def post(self,payload=None,host=None,origin=None):
        headers={'Content-Type':'application/json','X-Workbench':'1'}
        if host:headers['Host']=host
        if origin:headers['Origin']=origin
        return urlopen(Request(f'http://127.0.0.1:{self.port}/api/dashboard/manual',data=json.dumps(payload or self.payload).encode(),headers=headers))
    def test_owner_save_read_and_stale_revision(self):
        with self.post() as response:self.assertEqual(json.load(response)['record']['fields']['new_count'],65)
        with self.assertRaises(HTTPError) as error:self.post()
        self.assertEqual(error.exception.code,409)
        self.assertEqual(manual.load('store1','week','2026-10-12','2026-10-18',db=self.db)['fields']['new_count'],65)
    def test_report_origin_and_lan_viewers_cannot_write(self):
        for host in (f'localhost:{self.port}',f'192.168.2.153:{self.port}'):
            with self.assertRaises(HTTPError) as error:self.post(host=host)
            self.assertEqual(error.exception.code,403)
        with self.assertRaises(HTTPError) as error:self.post(origin='http://untrusted.example')
        self.assertEqual(error.exception.code,403)
        self.assertFalse(self.db.exists())
    def test_snapshot_cannot_be_used_for_another_store_or_period(self):
        for changed in ({'store':'other'},{'start':'2026-10-19','end':'2026-10-25'}):
            with self.assertRaises(HTTPError) as error:self.post(self.payload|changed)
            self.assertEqual(error.exception.code,400)
    def test_report_origin_cannot_read_archive_directly(self):
        url=f'http://127.0.0.1:{self.port}/api/dashboard/manual?store=store1&kind=week&start=2026-10-12&end=2026-10-18'
        with self.assertRaises(HTTPError) as error:urlopen(Request(url,headers={'Host':f'localhost:{self.port}'}))
        self.assertEqual(error.exception.code,403)

if __name__=='__main__':unittest.main()
