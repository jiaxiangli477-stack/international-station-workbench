from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge_reads


class TopicRefreshStatusTests(unittest.TestCase):
    def test_job_status_persists_and_rejects_unknown_store(self):
        with tempfile.TemporaryDirectory(dir=r"D:\Codex") as temp, patch.object(bridge_reads, 'STATE', Path(temp)):
            running=bridge_reads.write_topic_refresh_status('youhealth','a'*32,'RUNNING','正在只读查询')
            self.assertEqual(running, bridge_reads.read_topic_refresh_status('youhealth'))
            done=bridge_reads.write_topic_refresh_status('youhealth','a'*32,'FAILED','查询失败，保留旧缓存')
            self.assertEqual(done['status'],'FAILED')
            with self.assertRaisesRegex(ValueError,'店铺尚未绑定'):
                bridge_reads.write_topic_refresh_status('unknown','b'*32,'RUNNING','working')

    def test_running_job_from_previous_server_is_stale(self):
        with tempfile.TemporaryDirectory(dir=r"D:\Codex") as temp, patch.object(bridge_reads, 'STATE', Path(temp)):
            bridge_reads.write_topic_refresh_status('youhealth','a'*32,'RUNNING','正在查询',server_id='server-old')
            self.assertEqual(bridge_reads.read_topic_refresh_status('youhealth',server_id='server-new')['status'],'STALE')


if __name__ == '__main__':
    unittest.main()
