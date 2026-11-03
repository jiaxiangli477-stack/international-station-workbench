"""Content-only attempts must never reuse an older normalization report."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import listing_adapter as adapter


class ContentAttemptTests(unittest.TestCase):
    def test_failed_retry_keeps_current_input_instead_of_stale_reports(self):
        sandbox = Path(__file__).resolve().parents[2] / 'docs/audit-20261028-sandbox'
        sandbox.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=sandbox) as temporary:
            root = Path(temporary)
            reports = root / 'reports'
            reports.mkdir()
            manifest = {'product_id': 'fixture', 'fields': {'product_name': 'Current input'}}
            (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            (reports / 'fixture-fill-manifest.json').write_text(json.dumps(
                dict(manifest, fields={'product_name': 'Stale input'})), encoding='utf-8')
            (reports / 'fixture-fill-content-audit.json').write_text(
                '{"status":"passed","blockers":[]}', encoding='utf-8')
            unrelated = reports / 'other-fixture-fill-manifest.json'
            unrelated.write_text('{}', encoding='utf-8')
            with patch.object(adapter, 'command', return_value=['offline-fixture']), \
                    patch.object(adapter.subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
                normalized, gaps = adapter.prepare_content(root, root / 'skills')
            self.assertEqual(normalized, manifest)
            self.assertTrue(any('未交回可用报告' in gap for gap in gaps))
            self.assertTrue(unrelated.is_file())


if __name__ == '__main__':
    unittest.main()
