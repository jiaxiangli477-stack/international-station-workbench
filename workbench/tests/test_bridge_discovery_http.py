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
import bridge_catalog
import serve


class BridgeDiscoveryHttpTests(unittest.TestCase):
    def test_discovery_returns_job_id_and_pollable_terminal_status(self):
        started = threading.Event()
        finish = threading.Event()
        def fake_discover():
            started.set()
            finish.wait(2)
            return {'status': 'SUCCESS', 'tools': [{}, {}], 'groups': [{}], 'failedSchemas': [],
                    'message': '测试目录已更新'}

        with tempfile.TemporaryDirectory(dir=r"D:\Codex") as temp:
            state_path = Path(temp) / 'discovery-status.json'
            catalog_lock=threading.Lock()
            server = serve.WorkspaceServer(('127.0.0.1', 0), serve.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch.object(serve, 'CATALOG_JOB', catalog_lock), \
                        patch.object(bridge_catalog, 'DISCOVERY_STATE', state_path), \
                        patch.object(bridge_catalog, 'discover', side_effect=fake_discover):
                    conn = HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                    conn.request('POST', '/api/bridge/catalog/discover', body='{}',
                                 headers={'Content-Type': 'application/json'})
                    response = conn.getresponse()
                    begin = json.loads(response.read())
                    self.assertEqual(response.status, 202)
                    self.assertRegex(begin['jobId'], r'^[a-f0-9]{32}$')
                    self.assertTrue(started.wait(1))
                    conn.request('GET', '/api/bridge/catalog/discovery-status?jobId='+begin['jobId'])
                    running = json.loads(conn.getresponse().read())
                    self.assertEqual(running['status'], 'RUNNING')
                    finish.set()
                    terminal = None
                    for _ in range(50):
                        conn.request('GET', '/api/bridge/catalog/discovery-status?jobId='+begin['jobId'])
                        terminal = json.loads(conn.getresponse().read())
                        if terminal.get('status') != 'RUNNING':
                            break
                        time.sleep(.02)
                    self.assertEqual((terminal.get('status'), terminal.get('tools'), terminal.get('groups')),
                                     ('SUCCESS', 2, 1), msg=repr(terminal))
                    for _ in range(50):
                        if not catalog_lock.locked(): break
                        time.sleep(.01)
                    self.assertFalse(catalog_lock.locked())
                    conn.close()
            finally:
                finish.set()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
