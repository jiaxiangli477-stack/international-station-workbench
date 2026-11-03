import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import task_store as store
import packaging_design as design
import skill_jobs

BRIEF = 'Amber glass dropper bottle and carton. Deep grape purple and ivory. Exact text LIFEWORTH / GRAPE SEED / ORAL LIQUID. No other copy.'


class PackagingDesignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = store.STATE, store.DB
        store.STATE = Path(self.tmp.name); store.DB = store.STATE / 'test.sqlite'
        self.p = store.create_product('test:design', 'Test', facts={'mode': 'concept', 'market': 'INTERNAL_B2B', 'form': 'Oral Liquid', 'design': BRIEF})
        self.payload = dict(id=self.p['id'], revision=1, text=BRIEF, acknowledgeExecution=True,imageProvider='configured')

    def tearDown(self):
        store.STATE, store.DB = self.old; self.tmp.cleanup()

    def test_approval_is_explicit_versioned_and_duplicate_click_is_one_job(self):
        with self.assertRaises(ValueError): design.approve(dict(self.payload, acknowledgeExecution=False))
        with self.assertRaises(ValueError): design.approve(dict(self.payload, revision=2))
        first = design.approve(self.payload)
        self.assertEqual(first['id'], design.approve(self.payload)['id'])
        self.assertEqual(len(store.records('jobs')), 1)
        self.assertIsNone(store.product(self.p['id']).get('approvedPackaging'))
        with self.assertRaises(ValueError): design.approve(dict(self.payload, text=BRIEF + 'changed'))

    def test_real_packaging_and_changed_revision_cannot_use_adapter(self):
        p = store.product(self.p['id']); p['facts']['mode'] = 'real'; store.save_product(p)
        with self.assertRaises(ValueError): design.approve(self.payload)
        p['facts']['mode'] = 'concept'; store.save_product(p)
        job = design.approve(self.payload)
        p = store.product(p['id']); p['designReview']['revision'] = 2
        with self.assertRaises(ValueError): design.generate(job, p, store.STATE, skill_jobs.SKILLS)

    def test_blocked_brief_is_visible_only_for_current_revision(self):
        design.propose(self.p['id'], 1, BRIEF, 'old-job')
        self.assertEqual(store.product(self.p['id'])['designReview']['status'], 'PENDING')
        design.propose(self.p['id'], 2, 'stale', 'stale-job')
        self.assertEqual(store.product(self.p['id'])['designReview']['text'], BRIEF)

    def test_fixed_skill_adapter_registers_real_output_without_approving_image(self):
        from PIL import Image
        job = design.approve(self.payload)
        root = store.STATE / 'runs' / job['id']
        class Process:
            def __init__(self, args, **kwargs):
                self.args = args
                assert args[1].endswith('packaging_image_runner.py')
                assert args[2] == 'configured'
                assert '--raw' in args
            def wait(self, timeout):
                Image.new('RGB', (1024, 1024), 'white').save(self.args[-1]); return 0
        with patch.object(design.subprocess, 'Popen', Process), patch.object(skill_jobs.shutil, 'which', return_value=None):
            self.assertEqual(skill_jobs.run(job)['stage'], 'PACKAGING_REVIEW')
        p = store.product(self.p['id'])
        self.assertIsNone(p['approvedPackaging'])
        self.assertIsNone(p['draft'])
        self.assertEqual(len(p['packaging']['images']), 1)
        self.assertTrue((root / 'images/packaging.png').is_file())

    def test_fallback_is_explicit_and_rejection_never_registers_fake_output(self):
        job = design.approve(dict(self.payload, imageProvider='tokenstation'))
        root = store.STATE / 'runs' / job['id']
        class Rejected:
            def __init__(self, args, **kwargs):
                assert args[2] == 'tokenstation'
                assert kwargs['env']['PYTHONIOENCODING'] == 'utf-8'
            def wait(self, timeout):
                (root / 'image-error.json').write_text(json.dumps({'httpStatus':403,'reason':'GROUP_DISABLED'}))
                return 1
        with patch.object(design.subprocess, 'Popen', Rejected):
            with self.assertRaisesRegex(ValueError, '禁用'):
                skill_jobs.run(job)
        self.assertIsNone(store.product(self.p['id']).get('packaging'))
        self.assertEqual(len(store.records('jobs')), 1)


if __name__ == '__main__': unittest.main()
