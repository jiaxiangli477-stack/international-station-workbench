import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from project_paths import skill_preflight


class LocalSkillExtensionTests(unittest.TestCase):
    def test_reports_local_extension_without_claiming_upstream_hash_match(self):
        with tempfile.TemporaryDirectory(dir=r"D:\Codex") as temp:
            parent = Path(temp)
            root = parent / "b2b-image-skill"
            root.mkdir()
            (root / "scripts").mkdir()
            (root / "scripts" / "reference_sample.py").write_text("validator", encoding="utf-8")
            base_text = b"upstream skill text"
            local_text = b"upstream skill text plus reviewed extension"
            (root / "SKILL.md").write_bytes(local_text)
            source = {
                "skill_root": str(root.resolve()),
                "repository": "Star-Platinum-1/lifeworth-b2b-image",
                "commit": "505dca197860dddaec37458b2f0e70cf15f840d6",
                "commit_date": "2026-10-13",
                "skill_md_sha256": hashlib.sha256(base_text).hexdigest(),
                "local_extension": {
                    "name": "reference-sample-v1",
                    "skill_md_sha256": hashlib.sha256(local_text).hexdigest(),
                },
            }
            (parent / "b2b-image-skill.source.json").write_text(json.dumps(source), encoding="utf-8")
            with patch.dict(os.environ, {"WORKBENCH_B2B_SKILL_ROOT": str(root)}):
                result = skill_preflight("b2b-image-skill")
        self.assertEqual(result["version"], "505dca1+reference-sample-v1@2026-10-13")
        self.assertEqual(result["name"], "b2b-image-skill")
        self.assertIn("local extension", result["note"])

    def test_b2b_skill_preflight_requires_reference_validator(self):
        with tempfile.TemporaryDirectory(dir=r"D:\Codex") as temp:
            parent = Path(temp)
            root = parent / "b2b-image-skill"
            root.mkdir()
            (root / "SKILL.md").write_text("test", encoding="utf-8")
            with patch.dict(os.environ, {"WORKBENCH_B2B_SKILL_ROOT": str(root)}):
                result = skill_preflight("b2b-image-skill")
        self.assertFalse(result["available"])
        self.assertIn("scripts/reference_sample.py", result["missing"])


if __name__ == "__main__":
    unittest.main()
