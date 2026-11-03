from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge_catalog


class BridgeCatalogStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=r"D:\Codex")
        self.state_file = Path(self.temp.name) / "discovery.json"
        self.patch = patch.object(bridge_catalog, "DISCOVERY_STATE", self.state_file)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_tracks_a_discovery_job_through_success(self):
        job = "a" * 32
        bridge_catalog.record_discovery_status(job, "RUNNING", "正在查询接口说明")
        self.assertEqual(bridge_catalog.read_discovery_status(job)["status"], "RUNNING")
        bridge_catalog.record_discovery_status(job, "SUCCESS", "接口目录已更新", tools=200, groups=12)
        status = bridge_catalog.read_discovery_status(job)
        self.assertEqual((status["status"], status["tools"], status["groups"]), ("SUCCESS", 200, 12))

    def test_hides_status_from_a_different_job_id(self):
        bridge_catalog.record_discovery_status("a" * 32, "FAILED", "查询失败")
        self.assertEqual(bridge_catalog.read_discovery_status("b" * 32)["status"], "SUPERSEDED")

    def test_running_job_from_previous_server_is_stale(self):
        bridge_catalog.record_discovery_status("a" * 32, "RUNNING", "正在查询", server_id="server-old")
        self.assertEqual(bridge_catalog.read_discovery_status(server_id="server-new")["status"], "STALE")

    def test_rejects_invalid_job_identity_or_state(self):
        with self.assertRaises(ValueError):
            bridge_catalog.record_discovery_status("not-a-job", "RUNNING", "working")
        with self.assertRaises(ValueError):
            bridge_catalog.record_discovery_status("a" * 32, "PROCESSING", "working")


if __name__ == "__main__":
    unittest.main()
