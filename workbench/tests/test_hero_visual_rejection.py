"""Offline server visual-feedback scope and unchanged rejected-pixel guard."""
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import skill_jobs
from native_template_runner import image_hash


class HeroRejectionTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT.parent/'docs/acceptance/OCR-sandbox';folder.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=folder)
        self.root=Path(self.temp.name)
        self.image=self.root/'m1.png'
        Image.new('RGB',(1000,1000),'blue').save(self.image)
        self.rows=[{'slot':'m1','file':'m1.png'}]
        self.job={'kind':'hero','nativeResumeSession':'existing-session','visualReview':{
            'status':'REJECTED','reason':'Title overlaps pouch; use PROTEIN / POWDER / TO GO.',
            'rejectedPixelHash':image_hash(self.image)}}

    def tearDown(self):self.temp.cleanup()

    def test_same_pixels_rejected_even_if_file_reencoded(self):
        with Image.open(self.image) as image:image.save(self.root/'reencoded.png',compress_level=0)
        with self.assertRaisesRegex(ValueError,'像素未变化'):
            skill_jobs.require_changed_hero(self.job,self.root,[{'slot':'m1','file':'reencoded.png'}])

    def test_changed_pixels_can_continue_to_remaining_checks(self):
        Image.new('RGB',(1000,1000),'green').save(self.image)
        skill_jobs.require_changed_hero(self.job,self.root,self.rows)

    def test_resume_feedback_explicitly_overrides_old_cache_advice(self):
        review=skill_jobs.hero_visual_review(self.job)
        self.assertEqual(review['source'],'server-visual-review')
        prompt=skill_jobs.hero_review_instructions(self.job)
        for text in ('不恢复旧spec','只重新生成m1','不要重画A0','PROTEIN / POWDER / TO GO'):
            self.assertIn(text,prompt)

    def test_normal_resume_is_unchanged(self):
        job={'kind':'hero','nativeResumeSession':'existing-session'}
        self.assertIsNone(skill_jobs.hero_visual_review(job))
        self.assertEqual(skill_jobs.hero_review_instructions(job),'')
        skill_jobs.require_changed_hero(job,self.root,self.rows)

    def test_feedback_requires_hero_rejection_and_valid_reason(self):
        for override in ({'kind':'visual'},{'kind':'packaging'},
                         {'visualReview':{'status':'APPROVED','reason':'old feedback'}},
                         {'visualReview':{'status':'REJECTED','reason':'   '}},
                         {'visualReview':{'status':'REJECTED','reason':['untrusted shape']}}):
            job=dict(self.job,**override)
            self.assertIsNone(skill_jobs.hero_visual_review(job))
            self.assertEqual(skill_jobs.hero_review_instructions(job),'')
            skill_jobs.require_changed_hero(job,self.root,self.rows)


if __name__=='__main__':unittest.main()
