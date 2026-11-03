import copy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import task_store as store
import recruitment_images as images
import skill_jobs

TOPIC={'id':'123','businessType':'HOT_PRODUCT','title':'Energy powder','categoryIds':['3'],'categories':['Sports Nutrition'],
 'requirements':[{'name':'Dosage Form','values':['Powder']}], 'countries':[], 'image':'https://example.com/ref.png',
 'ruleSummary':{'categoryId':'3','needPicMatch':'Y','attrDTOList':[{'attrId':101,'attrName':'Dosage Form','categoryId':3,'attrValueDTOList':[{'attrValueId':201,'attrValueName':'Powder'}]}]}}

class TopicImageTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=(store.STATE,store.DB)
  store.STATE=Path(self.tmp.name);store.DB=store.STATE/'test.sqlite'
 def tearDown(self):
  store.STATE,store.DB=self.old;self.tmp.cleanup()
 def preview(self):
  with patch('topic_workflow.cached_topic',return_value=(copy.deepcopy(TOPIC),None)):
   return images.preview('youhealth','HOT_PRODUCT',['123'])
 def test_theme_can_prepare_internal_concept_without_seller_facts(self):
  plan=self.preview();self.assertEqual(plan['eligible'],1)
  self.assertEqual(plan['items'][0]['kind'],'packaging');self.assertEqual(store.records('products'),[])
 def test_confirm_creates_traceable_theme_job_not_listing(self):
  plan=self.preview()
  with patch('topic_workflow.cached_topic',return_value=(copy.deepcopy(TOPIC),None)),patch('skill_jobs.capability',return_value={'available':True}):
   with self.assertRaises(ValueError):images.start('youhealth','HOT_PRODUCT',plan['items'],False)
   result=images.start('youhealth','HOT_PRODUCT',plan['items'],True)
  p=store.product(result['started'][0]['product'])
  self.assertEqual(p['facts']['mode'],'concept');self.assertEqual(p['facts']['formula'],'')
  self.assertEqual(p['recruitment']['entries'],{});self.assertEqual(p['recruitment']['topicId'],'123')
  self.assertEqual(p['recruitment']['conceptDesign']['form'],'Powder')
  self.assertEqual(store.records('jobs')[0]['kind'],'packaging')
  self.assertTrue(skill_jobs.missing(p,'listing'))
 def test_duplicate_click_does_not_enqueue_second_job(self):
  plan=self.preview()
  with patch('topic_workflow.cached_topic',return_value=(copy.deepcopy(TOPIC),None)),patch('skill_jobs.capability',return_value={'available':True}):
   images.start('youhealth','HOT_PRODUCT',plan['items'],True)
   images.start('youhealth','HOT_PRODUCT',plan['items'],True)
  self.assertEqual(len(store.records('products')),1);self.assertEqual(len(store.records('jobs')),1)
 def test_changed_theme_or_wrong_business_is_rejected(self):
  plan=self.preview();changed=copy.deepcopy(TOPIC);changed['ruleSummary']['categoryId']='4'
  with patch('topic_workflow.cached_topic',return_value=(changed,None)),patch('skill_jobs.capability',return_value={'available':True}):
   with self.assertRaises(ValueError):images.start('youhealth','HOT_PRODUCT',plan['items'],True)
  with self.assertRaises(ValueError):images.preview('youhealth','bad',['123'])
 def test_reference_can_guide_internal_concept_without_claiming_a_real_form(self):
  changed=copy.deepcopy(TOPIC);changed['requirements']=[];changed['ruleSummary']['attrDTOList']=[]
  with patch('topic_workflow.cached_topic',return_value=(changed,None)):
   plan=images.preview('youhealth','HOT_PRODUCT',['123'])
  self.assertEqual(plan['eligible'],1)
  self.assertEqual(images.prepare(changed,'youhealth')['facts']['form'],'')
 def test_no_form_and_no_reference_still_need_clarification(self):
  changed=copy.deepcopy(TOPIC);changed['requirements']=[];changed['ruleSummary']['attrDTOList']=[];changed['image']=''
  with patch('topic_workflow.cached_topic',return_value=(changed,None)):
   plan=images.preview('youhealth','HOT_PRODUCT',['123'])
  self.assertEqual(plan['eligible'],0);self.assertIn('form',plan['items'][0]['gaps'])
 def test_stop_blocks_automatic_following_visual_stage(self):
  import selection_jobs
  plan=self.preview()
  with patch('topic_workflow.cached_topic',return_value=(copy.deepcopy(TOPIC),None)),patch('skill_jobs.capability',return_value={'available':True}):
   result=images.start('youhealth','HOT_PRODUCT',plan['items'],True)
  p=store.product(result['started'][0]['product']);images.stop(p['id'])
  selection_jobs.advance(p['id']);self.assertEqual(store.product(p['id'])['selectionFlow']['status'],'STOPPED')
 def test_existing_entries_are_preserved_and_old_draft_chain_is_paused(self):
  import topic_workflow
  p=store.create_product('topic:youhealth:HOT_PRODUCT:123','Existing',facts={'mode':'concept','store':'youhealth','design':'Existing direction'})
  p=topic_workflow.attach(p,'youhealth',copy.deepcopy(TOPIC))
  p['recruitment']['entries']['category']={'actual':'3','evidence':'SKU evidence'}
  p['productionFlow']={'revision':p['revision'],'status':'ACTIVE'};store.save_product(p)
  plan=self.preview()
  with patch('topic_workflow.cached_topic',return_value=(copy.deepcopy(TOPIC),None)),patch('skill_jobs.capability',return_value={'available':True}):
   result=images.start('youhealth','HOT_PRODUCT',plan['items'],True)
  changed=store.product(result['started'][0]['product'])
  self.assertEqual(changed['recruitment']['entries']['category']['evidence'],'SKU evidence')
  self.assertEqual(changed['productionFlow']['status'],'STOPPED')
  self.assertGreater(changed['revision'],p['revision'])
 def test_other_active_jobs_cannot_be_relabelled_as_image_jobs(self):
  import topic_workflow
  p=store.create_product('topic:youhealth:HOT_PRODUCT:123','Existing',facts={'mode':'concept','store':'youhealth','design':'Existing direction'})
  p=topic_workflow.attach(p,'youhealth',copy.deepcopy(TOPIC))
  store.enqueue('listing','product:'+p['id'],{'product':p['id'],'revision':p['revision']})
  self.assertEqual(self.preview()['eligible'],0)

if __name__=='__main__':unittest.main()
