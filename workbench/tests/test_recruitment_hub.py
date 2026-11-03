import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import task_store as store
import topic_workflow
import recruitment_board as board
import recruitment_chain as chain
import operations_api as api

TOPIC={'id':'123','businessType':'CUSTOMIZATION_PRODUCT','title':'Fixture powder','categoryIds':['3'],'categories':['Powder'],
 'ruleSummary':{'categoryId':'3','needPicMatch':'Y','attrDTOList':[{'attrId':101,'attrName':'Dosage Form','categoryId':3,'attrValueDTOList':[{'attrValueId':201,'attrValueName':'Powder'}]}], 'capacityDtoList':[{'field':'cert_tag','name':'关联证书'}]}}

class HubTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=(store.STATE,store.DB)
  store.STATE=Path(self.tmp.name);store.DB=store.STATE/'test.sqlite'
 def tearDown(self):
  store.STATE,store.DB=self.old;self.tmp.cleanup()
 def product(self,key='youhealth'):
  facts={'store':key,'mode':'real','form':'Powder','market':'US','spec':'SKU sheet','formula':'Confirmed formula','price':'Confirmed quote','moq':'Confirmed MOQ','design':'Original','own_image':'fixture.png'}
  p=store.create_product('fixture:'+key,'Fixture',facts=facts)
  p=topic_workflow.attach(p,key,copy.deepcopy(TOPIC))
  return topic_workflow.save(p['id'],p['revision'],{'category':{'actual':'3','evidence':'SKU sheet'},'attr:101':{'actual':'Powder','evidence':'SKU sheet'}})
 def test_matching_never_fills_values_from_theme(self):
  item=board.evaluate(TOPIC,'youhealth',[])
  self.assertEqual(item['status'],'NEEDS_DATA');self.assertFalse(item['canPrepare'])
  self.assertEqual(item['matchedCount'],0)
 def test_image_check_is_a_separate_gate_and_certificate_is_manual(self):
  p=self.product();item=board.evaluate(TOPIC,'youhealth',[p])
  self.assertTrue(item['canPrepare']);self.assertEqual(item['status'],'IMAGE_REVIEW')
  self.assertEqual(item['manualCount'],1);self.assertEqual(item['platformStatus'],'NOT_RUN')
 def test_other_store_and_concept_do_not_become_confirmed_matches(self):
  p=self.product('lifeworthcn');item=board.evaluate(TOPIC,'youhealth',[p])
  self.assertIsNone(item['sourceProduct'])
  p['facts']['store']='youhealth';p['facts']['mode']='concept'
  self.assertFalse(board.evaluate(TOPIC,'youhealth',[p])['canPrepare'])
 def test_only_exact_field_and_category_are_reused(self):
  p=self.product();t=copy.deepcopy(TOPIC);t['ruleSummary']['attrDTOList'][0]['categoryId']=4
  item=board.evaluate(t,'youhealth',[p]);self.assertGreater(item['pendingCount'],0)
 def test_queue_preview_uses_real_gates(self):
  p=self.product();plan=chain.preview([{'id':p['id'],'revision':p['revision']}],'youhealth')
  self.assertEqual(plan['items'][0]['next'],'visual');self.assertTrue(plan['items'][0]['eligible'])
  p['facts']['formula']='';store.save_product(p)
  self.assertFalse(chain.preview([{'id':p['id'],'revision':p['revision']}],'youhealth')['items'][0]['eligible'])
 def test_start_is_deduplicated_and_respects_revision(self):
  p=self.product();selection=[{'id':p['id'],'revision':p['revision']}]
  with patch('skill_jobs.capability',return_value={'available':True}):
   chain.start(selection,'youhealth',True);chain.start(selection,'youhealth',True)
  self.assertEqual(len(store.records('jobs')),1)
  changed=topic_workflow.save(p['id'],p['revision'],{'attr:101':{'actual':'Capsule','evidence':'SKU'}})
  chain.advance(p['id'])
  self.assertEqual(store.product(p['id'])['productionFlow']['status'],'STALE')
  with self.assertRaises(ValueError):chain.start(selection,'youhealth',True)
 def test_image_approval_is_required_before_draft(self):
  p=self.product()
  p['productionFlow']={'revision':p['revision'],'status':'ACTIVE','target':'DRAFT'};store.save_product(p)
  store.commit_output(p['id'],p['revision'],'visual',{'revision':p['revision'],'job':'fixture','images':[]})
  chain.advance(p['id']);self.assertEqual(len(store.records('jobs')),0)
  self.assertEqual(store.product(p['id'])['productionFlow']['status'],'WAITING_VISUAL_REVIEW')
 def test_finished_draft_does_not_publish_or_requeue(self):
  p=self.product();p['productionFlow']={'revision':p['revision'],'status':'ACTIVE','target':'DRAFT'}
  p['draft']={'readback_verified':True,'draft_id':'1234','published':False};store.save_product(p)
  chain.advance(p['id']);self.assertEqual(store.records('jobs'),[])
  self.assertEqual(store.product(p['id'])['productionFlow']['status'],'DRAFT_SAVED')
 def test_stop_prevents_later_automatic_continuation(self):
  p=self.product();p['productionFlow']={'revision':p['revision'],'status':'ACTIVE','target':'DRAFT'};store.save_product(p)
  chain.stop(p['id']);chain.advance(p['id']);self.assertEqual(store.records('jobs'),[])
 def test_more_than_ten_or_client_forged_cross_store_is_rejected(self):
  with self.assertRaises(ValueError):chain.preview([{'id':'x','revision':1}]*11,'youhealth')
  p=self.product('lifeworthcn')
  with self.assertRaises(ValueError):chain.preview([{'id':p['id'],'revision':p['revision']}],'youhealth')
 def test_scan_covers_all_unique_pages_and_paginates_results(self):
  def page(key,q):
   t=copy.deepcopy(TOPIC);t['id']=str(q['page']);t['title']='Fixture '+str(q['page'])
   self.assertTrue(q['_unique'])
   return {'status':'SUCCESS','records':[t],'pagination':{'totalPages':2},'collectedAt':'fixture'}
  with patch('recruitment.read_page',side_effect=page):
   run=board.scan('youhealth',{'businessType':'CUSTOMIZATION_PRODUCT'})
  self.assertEqual(run['total'],2);self.assertEqual(len(board.latest(summary=True)),1)
  self.assertNotIn('items',board.latest(summary=True)[0])
  self.assertEqual(board.read('youhealth','CUSTOMIZATION_PRODUCT')['count'],2)
  self.assertEqual(board.read('youhealth','CUSTOMIZATION_PRODUCT',state='preparable')['count'],0)
 def test_approval_continues_to_draft_and_worker_stops_at_saved_draft(self):
  p=self.product();p['productionFlow']={'revision':p['revision'],'status':'ACTIVE','target':'DRAFT'};store.save_product(p)
  store.commit_output(p['id'],p['revision'],'visual',{'revision':p['revision'],'job':'fixture','images':[]})
  with self.assertRaises(ValueError):api.command({'action':'product.approve','id':p['id'],'phase':'visual','revision':p['revision'],'artifactJob':'fixture'})
  api.command({'action':'product.approve','id':p['id'],'phase':'visual','revision':p['revision'],'topicImageReviewed':True,'artifactJob':'fixture'})
  self.assertEqual(store.records('jobs')[0]['kind'],'listing')
  def save_draft(job):
   store.commit_output(p['id'],p['revision'],'listing',{'draft_id':'456','readback_verified':True,'published':False})
   return {'product':p['id']}
  with patch('skill_jobs.run',side_effect=save_draft):api.worker()
  self.assertEqual(store.product(p['id'])['productionFlow']['status'],'DRAFT_SAVED')
  self.assertEqual(len(store.records('jobs')),1)
 def test_new_images_invalidate_previous_draft_even_with_same_fact_version(self):
  p=self.product();p['draft']={'readback_verified':True};store.save_product(p)
  p=store.commit_output(p['id'],p['revision'],'visual',{'revision':p['revision'],'job':'new','images':[]})
  self.assertIsNone(p['draft'])
 def test_worker_failure_does_not_retry_forever(self):
  p=self.product()
  with patch('skill_jobs.capability',return_value={'available':True}):chain.start([{'id':p['id'],'revision':p['revision']}],'youhealth',True)
  with patch('skill_jobs.run',side_effect=ValueError('fixture failure')):api.worker()
  self.assertEqual(store.product(p['id'])['productionFlow']['status'],'NEEDS_ATTENTION')
  self.assertEqual(len(store.records('jobs')),1)
 def test_display_labels_do_not_change_requirement_fingerprint(self):
  changed=copy.deepcopy(TOPIC);changed['tagLabel']='Different presentation label';changed['sourceOrder']=555
  self.assertEqual(topic_workflow.fingerprint(TOPIC),topic_workflow.fingerprint(changed))
  changed['ruleSummary']['categoryId']='4'
  self.assertNotEqual(topic_workflow.fingerprint(TOPIC),topic_workflow.fingerprint(changed))
 def test_adopting_a_match_copies_only_seller_evidence_and_rejects_stale_source(self):
  p=self.product();item=board.evaluate(TOPIC,'youhealth',[p]);run={'id':'fixture-run','store':'youhealth','businessType':'CUSTOMIZATION_PRODUCT','items':[item]}
  board.latest()
  with store.db() as c:c.execute('INSERT INTO recruitment_runs VALUES(?,?)',('fixture',json.dumps(run)))
  with patch.object(topic_workflow,'cached_topic',return_value=(TOPIC,None)):
   adopted=board.adopt('fixture-run','123')
  self.assertEqual(adopted['facts']['formula'],'Confirmed formula')
  self.assertEqual(adopted['recruitment']['entries']['attr:101']['evidence'],'SKU sheet')
  topic_workflow.save(p['id'],p['revision'],{'attr:101':{'actual':'Capsule','evidence':'New SKU'}})
  with self.assertRaises(ValueError):board.adopt('fixture-run','123')

if __name__=='__main__':unittest.main()
