import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

import attribute_plan
import product_intelligence_adapter as adapter
import single_approval_flow
import task_store


SKILL_ROOT = Path(__file__).resolve().parents[2] / "vendor/product-intelligence-v2-2.4.0/reviewed/product-intelligence-v2"
SKILL_MANIFEST = SKILL_ROOT.parent / "skill-source.json"


class ProductIntelligenceAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / ".state/runtime/tmp")
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.patcher = patch.object(task_store, "STATE", self.state)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.quality_patcher = patch.object(adapter, "QUALITY_ROOT", self.root / "quality")
        self.quality_patcher.start()
        self.addCleanup(self.quality_patcher.stop)
        self.product = self.product_fixture()
        self.product_patcher = patch.object(adapter.store, "product", return_value=self.product)
        self.product_patcher.start()
        self.addCleanup(self.product_patcher.stop)

    def tearDown(self):
        self.temp.cleanup()

    def product_fixture(self):
        plan = {
            "revision": 3,
            "manifest": {"fields": {
                "product_name": "UNCONFIRMED DESIGN NAME",
                "main_ingredient": "Creatine",
                "dosage_form": "Powder",
                "specification": "300 g",
            }, "custom_attributes": [{"name": "Claim", "value": "Private label available"}]},
            "field_sources": {
                "fields.product_name": {"kind": "DESIGN", "source": "Concept brief"},
                "fields.main_ingredient": {"kind": "CONFIRMED", "source": "Approved supplier specification"},
                "fields.dosage_form": {"kind": "REFERENCE", "source": "Reference listing"},
                "fields.specification": {"kind": "DESIGN", "source": "Unapproved design target"},
                "custom_attributes.0.value": {"kind": "CONFIRMED", "source": "Approved service capability record"},
            },
            "unresolved": [],
            "skillContract": {"test": "contract"},
        }
        plan["fingerprint"] = attribute_plan.fingerprint(plan)
        hero_job = "hero-approved"
        image_dir = self.state / "runs" / hero_job / "images"
        image_dir.mkdir(parents=True)
        hero_image = image_dir / "m1.png"
        Image.new("RGB", (1000, 1000), "blue").save(hero_image)
        hero = {
            "job": hero_job,
            "revision": 3,
            "attributePlanFingerprint": plan["fingerprint"],
            "templateVerified": True,
            "packagingJob": "package-approved",
            "images": [{"slot": "m1", "file": "images/m1.png", "specCheck": "ok"}],
        }
        hero["pixelHash"] = single_approval_flow.pixel_hash(hero, hero["images"][0])
        scope = single_approval_flow.hero_scope({
            "id": "P-fixture", "revision": 3, "facts": {"mode": "real"},
            "workflow": {"approvalPolicy": single_approval_flow.POLICY},
            "packaging": {"job": "package-approved"}, "attributePlan": plan, "hero": hero,
        })
        return {
            "id": "P-fixture", "revision": 3, "title": "UNCONFIRMED PRODUCT TITLE",
            "facts": {"mode": "real", "market": "US", "form": "Powder", "spec": "REFERENCE 300g"},
            "workflow": {"approvalPolicy": single_approval_flow.POLICY},
            "packaging": {"job": "package-approved"},
            "attributePlan": plan,
            "hero": hero,
            "heroApproval": {**scope, "signature": single_approval_flow.signature(scope), "approvedAt": "fixture"},
            "visualPartial": {"job": "partial-job", "revision": 3, "images": [
                {"slot": "m2", "file": "images/unreviewed.png"},
                {"slot": "d1", "file": "images/unreviewed-detail.png"},
            ]},
            "approvedVisual": None,
        }

    def test_skill_preflight_checks_pinned_source_hashes_and_version(self):
        result = adapter.skill_preflight()
        self.assertTrue(result["available"])
        self.assertEqual(result["version"], "2.4.0")
        self.assertGreater(result["verified_files"], 10)
        self.assertTrue(result["source_fingerprint"])

    def test_source_hash_mismatch_blocks_before_running_skill(self):
        manifest = json.loads(SKILL_MANIFEST.read_text(encoding="utf-8"))
        runtime_files = adapter.runtime_source_files(manifest)
        copy_root = self.root / "skill"
        copy_root.mkdir()
        for relative in runtime_files:
            source = SKILL_ROOT / relative
            target = copy_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        manifest_path = self.root / "skill-source.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        (copy_root / runtime_files[0]).write_bytes((copy_root / runtime_files[0]).read_bytes() + b"\nmodified")
        with patch.object(adapter, "APPROVED_MANIFEST_SHA256", manifest_hash):
            with self.assertRaisesRegex(ValueError, "哈希"):
                adapter.skill_preflight(copy_root, manifest_path)

    def test_manifest_only_full_cli_pipeline_uses_only_confirmed_fields_and_approved_current_images(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("remote network forbidden")):
            result = adapter.diagnose("P-fixture", expected_revision=3)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["revision"], 3)
        self.assertEqual(result["pipeline"], [
            "doctor", "import-products", "audit-assets", "analyze-images:manifest_only",
            "import-visual-analysis", "score", "release-dashboard",
        ])
        self.assertEqual([row["slot"] for row in result["images"]], ["m1"])
        self.assertTrue(all(row["copied"] for row in result["images"]))
        self.assertEqual(result["confirmed_fields"], {
            "main_ingredient": "Creatine", "custom_attributes.0.value": "Private label available",
        })
        self.assertNotIn("UNCONFIRMED DESIGN NAME", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("300 g", json.dumps(result, ensure_ascii=False))
        self.assertIn("market_evidence_missing", result["risk_flags"])
        self.assertIn("visual_analysis_missing", result["risk_flags"])
        self.assertIn("product_specification_missing", result["missing_evidence"])
        self.assertEqual(result["release_status"], "HOLD")
        report_path = adapter.QUALITY_ROOT / "P-fixture" / result["run_id"] / "diagnostic.json"
        self.assertTrue(report_path.is_file())
        staged_root = adapter.QUALITY_ROOT / "P-fixture" / result["run_id"] / "inputs/products/P-fixture"
        self.assertTrue((staged_root / "main/m1.png").is_file())
        self.assertFalse((staged_root / "main/m2.png").exists())
        self.assertFalse((staged_root / "detail/d1.png").exists())

    def test_stale_revision_and_unregistered_image_paths_are_blocked(self):
        with self.assertRaisesRegex(ValueError, "版本"):
            adapter.diagnose("P-fixture", expected_revision=2)
        self.product["hero"]["images"][0]["file"] = "../../outside.png"
        with self.assertRaises((ValueError, OSError)):
            adapter.diagnose("P-fixture", expected_revision=3)
        self.assertFalse((self.root / "quality").exists())

    def test_diagnostic_readback_is_revision_bound_and_does_not_reuse_stale_report(self):
        result = adapter.diagnose("P-fixture", expected_revision=3)
        latest = adapter.latest("P-fixture", current_revision=3)
        self.assertEqual(latest["run_id"], result["run_id"])
        self.assertEqual(latest["status"], "completed")
        self.assertIsNone(adapter.latest("P-fixture", current_revision=4))
        readback = adapter.read_report("P-fixture", result["run_id"])
        self.assertEqual(readback["source_skill"]["version"], "2.4.0")
        self.assertEqual(readback["revision"], 3)


if __name__ == "__main__":
    unittest.main()
