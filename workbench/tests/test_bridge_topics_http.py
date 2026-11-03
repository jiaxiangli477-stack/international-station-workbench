from http.client import HTTPConnection
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge_reads
import recruitment
import serve


class BridgeTopicsHttpTests(unittest.TestCase):
    def test_refresh_returns_job_and_exposes_terminal_state(self):
        with tempfile.TemporaryDirectory(dir=r"D:\Codex") as temp:
            server=serve.WorkspaceServer(('127.0.0.1',0),serve.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with patch.object(serve,'TOPIC_JOBS',{}), \
                        patch.object(bridge_reads,'STATE',Path(temp)), \
                        patch.object(recruitment,'status',return_value={'status':'NOT_COLLECTED'}), \
                        patch.object(bridge_reads,'refresh_topics',return_value={'status':'SUCCESS','message':'测试采集完成'}), \
                        patch.object(bridge_reads,'read_topics',return_value={'status':'SUCCESS','records':[]}):
                    conn=HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                    conn.request('POST','/api/bridge/topics/refresh',body=json.dumps({'store':'youhealth'}),
                                 headers={'Content-Type':'application/json'})
                    response=conn.getresponse();started=json.loads(response.read())
                    self.assertEqual(response.status,202)
                    self.assertEqual(started['status'],'RUNNING')
                    self.assertRegex(started['jobId'],r'^[a-f0-9]{32}$')
                    terminal=None
                    for _ in range(50):
                        terminal=bridge_reads.read_topic_refresh_status('youhealth')
                        if terminal.get('status')!='RUNNING':break
                        time.sleep(.02)
                    self.assertEqual(terminal['status'],'SUCCESS')
                    conn.request('GET','/api/bridge/topics?store=youhealth')
                    data=json.loads(conn.getresponse().read())
                    self.assertEqual(data['refreshJob']['status'],'SUCCESS')
                    conn.close()
            finally:
                server.shutdown();server.server_close();thread.join(timeout=2)

    def test_existing_collection_is_reported_as_not_started(self):
        with tempfile.TemporaryDirectory(dir=r"D:\Codex") as temp:
            server=serve.WorkspaceServer(('127.0.0.1',0),serve.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with patch.object(serve,'TOPIC_JOBS',{}), \
                        patch.object(recruitment,'status',return_value={'status':'RUNNING','started':'fixture'}), \
                        patch.object(bridge_reads,'refresh_topics') as refresh:
                    conn=HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                    conn.request('POST','/api/bridge/topics/refresh',body=json.dumps({'store':'youhealth'}),
                                 headers={'Content-Type':'application/json'})
                    response=conn.getresponse();body=json.loads(response.read())
                    self.assertEqual(response.status,409)
                    self.assertEqual(body['status'],'ALREADY_RUNNING')
                    refresh.assert_not_called()
                    conn.close()
            finally:
                server.shutdown();server.server_close();thread.join(timeout=2)


if __name__=='__main__':
    unittest.main()
