"""Single-product Skill manifests normalize before content preflight; no model calls."""
from contextlib import contextmanager
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import attribute_plan
import listing_adapter


class ManifestShapeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='D:/Codex', prefix='attribute-shape-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.product = dict(id='fixture', revision=1, events=[])
        self.job = dict(id='attrs-fixture', revision=1, workflowContinuation=True)
        self.manifest = {'fields': {'product_name': 'Fixture product'}}
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('CREATE TABLE products(id TEXT PRIMARY KEY,data TEXT)')
        self.conn.execute('INSERT INTO products VALUES(?,?)', ('fixture', json.dumps(self.product)))
        self.conn.commit()
        self.addCleanup(self.conn.close)

        @contextmanager
        def db():
            with self.conn:
                yield self.conn

        def preflight(root, skills):
            content = json.loads((root / 'manifest.json').read_text(encoding='utf-8-sig'))
            self.assertIsInstance(content, dict)
            self.assertEqual(content['product_id'], 'fixture')
            return content, ['fixture content review']

        self.preflight = self.enterContext(patch.object(listing_adapter, 'prepare_content', side_effect=preflight))
        self.enterContext(patch.object(listing_adapter, 'skill_contract', return_value={'fixture': 'contract'}))
        self.enterContext(patch.object(attribute_plan, 'skill_root', return_value=Path('D:/Codex/fixture-skill')))
        self.enterContext(patch.object(attribute_plan.store, 'db', db))
        self.enterContext(patch.dict(sys.modules, {'skill_jobs': SimpleNamespace(artifact=lambda root, file: root / file)}))

    def install(self, value):
        (self.root / 'manifest.json').write_text(json.dumps(value), encoding='utf-8')
        result = dict(status='completed', manifest_file='manifest.json', field_sources={}, unresolved=[])
        return attribute_plan.install(self.product, self.job, self.root, result)

    def assert_installed(self, value):
        product = self.install(value)
        plan = product['attributePlan']
        self.assertIsInstance(plan['manifest'], dict)
        self.assertEqual(plan['manifest']['product_id'], 'fixture')
        self.assertIn('fixture content review', plan['unresolved'])
        self.assertEqual(plan['fingerprint'], attribute_plan.fingerprint(plan))
        self.preflight.assert_called_once()

    def test_single_item_array_runs_original_content_preflight_and_normalize(self):
        self.assert_installed([self.manifest])

    def test_object_remains_compatible(self):
        self.assert_installed(self.manifest)

    def test_actual_manifest_shape_from_completed_run_remains_supported(self):
        source = Path(__file__).resolve().parents[1] / '.state/operations/runs/d8b1814d90b74ccdb2b95dc7a643876e/manifest.json'
        if not source.is_file():
            self.skipTest('private acceptance artifact is not present')
        value = json.loads(source.read_text(encoding='utf-8-sig'))
        if isinstance(value, list):
            self.assertEqual(len(value), 1)
            self.assertIsInstance(value[0], dict)
        else:
            self.assertIsInstance(value, dict)
        self.assert_installed(copy.deepcopy(value))

    def test_multiple_empty_and_invalid_manifests_rejected_before_preflight(self):
        for value in ([self.manifest, self.manifest], [], [None], [[]], ['text'], None, 'text', 7, True):
            with self.subTest(shape=type(value).__name__):
                with self.assertRaisesRegex(ValueError, 'manifest'):
                    self.install(value)
        self.preflight.assert_not_called()
        product = json.loads(self.conn.execute('SELECT data FROM products').fetchone()['data'])
        self.assertNotIn('attributePlan', product)


if __name__ == '__main__':
    unittest.main()
