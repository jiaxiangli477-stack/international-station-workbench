import copy
import tempfile
from pathlib import Path
import unittest
import task_store as store
import concept_direction as direction
import recruitment_images
from unittest.mock import patch


class ConceptDirectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=store.DB,store.STATE
        store.STATE=Path(self.tmp.name);store.DB=store.STATE/'test.sqlite'
        self.topic={'id':'123','businessType':'HOT_PRODUCT','title':'条装蛋白粉','requirements':[{'name':'Dosage Form','values':['Gummy']}],
                    'categories':['Sport'],'categoryIds':['3'],'image':'https://example.com/reference.jpg'}
        p=recruitment_images.prepare(self.topic,'youhealth');p['id']='P-test';store.save_product(p);self.p=p
    def tearDown(self):
        store.DB,store.STATE=self.old;self.tmp.cleanup()
    def test_conflict_is_detected_before_paid_execution(self):
        self.assertIn('Gummy',direction.conflict(self.p))
        with patch('topic_workflow.cached_topic',return_value=(copy.deepcopy(self.topic),None)):
            plan=recruitment_images.preview('youhealth','HOT_PRODUCT',['123'])
        self.assertFalse(plan['items'][0]['eligible'])
    def test_title_selection_changes_only_concept_direction_and_survives_prepare(self):
        p=direction.resolve(self.p['id'],1,'title')
        self.assertEqual(p['revision'],2);self.assertEqual(p['recruitment']['conceptDesign']['form'],'Powder')
        self.assertEqual(p['facts']['form'],'');self.assertEqual(p['recruitment']['snapshot'],self.topic)
        self.assertEqual(p['designReview']['status'],'PENDING');self.assertFalse(direction.conflict(p))
        again=recruitment_images.prepare(self.topic,'youhealth',p)
        self.assertEqual(again['revision'],2);self.assertEqual(again['recruitment']['conceptDesign']['form'],'Powder')


if __name__=='__main__':unittest.main()
