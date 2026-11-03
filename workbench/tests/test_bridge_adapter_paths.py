import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import bridge_catalog
import bridge_reads
import recruitment
import weekly_update


class BridgeAdapterPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parents[1] / '.state/runtime/tmp')
        self.root = Path(self.temp.name)
        self.bridge = self.root / 'bridge' / 'bin'
        self.bridge.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_schema_discovery_uses_current_accio_runtime_runner(self):
        with patch.object(bridge_catalog, 'current_bridge', return_value=self.bridge), \
                patch.object(weekly_update, 'run', return_value='{"success":true,"children":[]}') as run:
            result = bridge_catalog.cli_schema('icbu')
        self.assertTrue(result['success'])
        args, kwargs = run.call_args
        self.assertEqual([str(value) for value in args[0]], [str(self.bridge / 'workctl.cmd'), 'schema', 'icbu', '--format', 'json'])
        self.assertEqual(kwargs['timeout'], 30)

    def test_recruitment_pages_use_current_accio_runtime_runner(self):
        output = self.root / 'hot_product-1.json'
        value = {'pageNo': 1, 'pageSize': 48, 'datas': [], 'pageCount': 1, 'recordCount': 0}

        def run(command, cwd, timeout=60, env=None):
            output_path = Path(command[command.index('--output') + 1])
            output_path.write_text(json.dumps({'success': True, 'data': {'success': True, 'value': value}}), encoding='utf-8')
            return ''

        with patch.object(recruitment.weekly_update, 'run', side_effect=run) as bridge_run:
            result = recruitment.call_page(self.bridge, self.root, 'HOT_PRODUCT', 1)
        self.assertEqual(result['pageNo'], 1)
        self.assertEqual(bridge_run.call_count, 1)

    def test_narrow_bridge_reads_use_current_accio_runtime_runner(self):
        output = self.root / 'result.json'

        def run(command, cwd, timeout=60, env=None):
            output_path = Path(command[command.index('--output') + 1])
            output_path.write_text(json.dumps({'success': True, 'data': {'success': True, 'value': []}}), encoding='utf-8')
            return ''

        with patch.object(bridge_reads.weekly_update, 'run', side_effect=run) as bridge_run:
            result = bridge_reads._call(self.bridge / 'workctl.cmd', ['icbu', 'advisor', 'summary'], output)
        self.assertEqual(result, {'success': True, 'value': []})
        self.assertEqual(bridge_run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
