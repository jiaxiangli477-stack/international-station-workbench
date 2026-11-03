"""Cross-agent contracts; no live services or external executors."""
import copy
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import attribute_plan
import production_flow
import task_store
import skill_jobs


class VisualOnlyContractTests(unittest.TestCase):
    def fixture(self):
        proposal = {'revision': 1, 'manifest': {'fields': {'product_name': 'Synthetic'}}}
        proposal['fingerprint'] = attribute_plan.fingerprint(proposal)
        return {'id': 'synthetic', 'title': 'Synthetic', 'revision': 1, 'source': 'manual:synthetic', 'facts': {'mode': 'concept', 'store': 'youhealth'},
                'attributePlan': proposal, 'approvedAttributes': None,
                'packaging': {'job': 'pack', 'revision': 1, 'attributePlanFingerprint': proposal['fingerprint']},
                'approvedPackaging': 'pack',
                'visual': {'job': 'visual', 'revision': 1, 'attributePlanFingerprint': proposal['fingerprint']},
                'approvedVisual': 'visual'}

    def test_visual_target_ends_after_image_approval_without_listing(self):
        p = self.fixture()
        p['workflow'] = {'target': 'VISUALS'}
        with patch.object(task_store, 'records', return_value=[]):
            result = production_flow.plan(p)
        self.assertEqual(result['next'], 'done')
        self.assertEqual(result['status'], 'VISUALS_READY')

    def test_draft_target_still_requires_attributes_review(self):
        with patch.object(task_store, 'records', return_value=[]):
            self.assertEqual(production_flow.plan(self.fixture())['next'], 'attributes_review')

    def test_preview_preserves_source_product_target_and_rejects_invalid_target(self):
        original = self.fixture()
        with patch.object(task_store, 'records', return_value=[]), patch.object(task_store, 'product', side_effect=lambda _: copy.deepcopy(original)):
            preview = production_flow.preview([{'id': original['id'], 'revision': 1}], 'youhealth', 'VISUALS')
            self.assertEqual(preview['target'], 'VISUALS')
            self.assertEqual(preview['items'][0]['status'], 'VISUALS_READY')
            self.assertNotIn('workflow', original)
            with self.assertRaises(ValueError):
                production_flow.preview([{'id': original['id'], 'revision': 1}], 'youhealth', 'PUBLISH')

    def test_missing_skill_fails_before_executors_or_job_directory(self):
        p = self.fixture()
        with patch.object(skill_jobs, 'executor_blocked', return_value=False), patch.object(task_store, 'product', return_value=p), \
                patch.object(skill_jobs, 'missing', return_value=[]), patch.object(skill_jobs, 'skill_preflight', return_value={'available': False, 'missing': ['SKILL.md']}), \
                patch.object(skill_jobs.shutil, 'which', return_value=None), patch.object(skill_jobs.subprocess, 'Popen') as child:
            with self.assertRaisesRegex(ValueError, '缺少原Skill依赖'):
                skill_jobs.run({'id': 'synthetic', 'product': p['id'], 'revision': 1, 'kind': 'attributes'})
            child.assert_not_called()


if __name__ == '__main__':
    unittest.main()
