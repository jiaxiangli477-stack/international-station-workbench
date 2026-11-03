import copy
import tempfile
from pathlib import Path
import unittest
import task_store as store
import topic_workflow as topic
import operations_api as api
import skill_jobs
from unittest.mock import patch


FIXTURE = {'id':'123','businessType':'CUSTOMIZATION_PRODUCT','title':'Fixture powder',
 'categoryIds':['1','2','3'],'categories':['Health','Food','Powder'],'categoryLeaf':'Powder',
 'image':'https://example.com/ref.png','pictureMatch':'Y',
 'capabilities':['关联证书产品'], 'requirements':[],
 'ruleSummary':{'categoryId':'3','needPicMatch':'Y','capacityDtoList':[{'field':'cert_tag','name':'关联证书产品'}],
 'attrDTOList':[{'attrId':101,'attrName':'Dosage Form','productPropertyId':101,'categoryId':3,
 'attrValueDTOList':[{'attrValueId':201,'attrValueName':'Powder','productValueId':201}]}]}}


class RectificationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=(store.STATE,store.DB)
  store.STATE=Path(self.tmp.name);store.DB=store.STATE/'test.sqlite'
  self.p=store.create_product('fixture','Fixture',facts={'store':'youhealth','mode':'concept'})
  self.p=topic.attach(self.p,'youhealth',FIXTURE)
 def tearDown(self):
  store.STATE,store.DB=self.old;self.tmp.cleanup()
 def test_requirement_is_not_a_product_fact(self):
  r=topic.report(self.p)
  row=next(x for x in r['rows'] if x['key']=='attr:101')
  self.assertEqual(row['status'],'TO_CONFIRM')
  self.assertEqual(row['actual'],'')
  self.assertEqual(row['fieldId'],'101')
  self.assertFalse(r['readyForDraft'])
 def test_matching_requires_real_evidence_and_preserves_native_ids(self):
  p=topic.save(self.p['id'],1,{'attr:101':{'actual':'Powder'}})
  self.assertEqual(next(x for x in topic.report(p)['rows'] if x['key']=='attr:101')['status'],'TO_CONFIRM')
  p=topic.save(p['id'],p['revision'],{'attr:101':{'actual':'Powder','evidence':'SKU sheet'}})
  row=next(x for x in topic.report(p)['rows'] if x['key']=='attr:101')
  self.assertEqual(row['status'],'MATCHED')
  self.assertEqual(row['assignment']['valueIds'],['201'])
 def test_mismatch_is_not_replaced_with_required_value(self):
  p=topic.save(self.p['id'],1,{'attr:101':{'actual':'Capsule','evidence':'SKU sheet'}})
  row=next(x for x in topic.report(p)['rows'] if x['key']=='attr:101')
  self.assertEqual(row['status'],'MISMATCH');self.assertEqual(row['actual'],'Capsule')
  self.assertNotIn('assignment',row)
 def test_category_leaf_not_parent_and_certificate_is_manual(self):
  p=topic.save(self.p['id'],1,{'category':{'actual':'1','evidence':'Current SKU'}})
  r=topic.report(p)
  self.assertEqual(next(x for x in r['rows'] if x['key']=='category')['status'],'MISMATCH')
  self.assertEqual(next(x for x in r['rows'] if x['key']=='certificate')['status'],'MANUAL')
  self.assertEqual(r['platform']['status'],'NOT_RUN')
 def test_changes_invalidate_downstream_and_old_revision_is_rejected(self):
  self.p.update(draft={'draft_id':'1'},approvedVisual='old');store.save_product(self.p)
  p=topic.save(self.p['id'],1,{'attr:101':{'actual':'Powder','evidence':'sheet'}})
  self.assertIsNone(p['draft']);self.assertIsNone(p['approvedVisual'])
  with self.assertRaises(ValueError):topic.save(p['id'],1,{})
 def test_unchanged_save_does_not_increment_or_clear_outputs(self):
  p=topic.save(self.p['id'],1,{})
  self.assertEqual(p['revision'],1)
 def test_unknown_fields_and_cross_store_are_rejected(self):
  with self.assertRaises(ValueError):topic.save(self.p['id'],1,{'attr:unknown':{'actual':'x'}})
  self.p['facts']['store']='lifeworthcn'
  self.assertFalse(topic.report(self.p)['readyForDraft'])
 def test_certificates_do_not_block_internal_preparation(self):
  p=topic.save(self.p['id'],1,{'category':{'actual':'3','evidence':'SKU sheet'},'attr:101':{'actual':'Powder','evidence':'SKU sheet'},'image':{'actual':'主体相似','evidence':'Reference checked'}})
  r=topic.report(p)
  self.assertTrue(r['readyForDraft']);self.assertEqual(r['manualCount'],1)
  self.assertFalse(r['readyToPublish'])
 def test_listing_gate_checks_rectification_and_no_api_can_mark_topic_passed(self):
  self.assertTrue(any('征品整改' in x for x in skill_jobs.missing(self.p,'listing')))
  self.p['draft']={'readback_verified':True};store.save_product(self.p)
  with self.assertRaisesRegex(ValueError,'平台匹配检测'):
   api.command({'action':'product.approve','id':self.p['id'],'phase':'draft','revision':1})
  with self.assertRaises(ValueError):topic.save(self.p['id'],1,{'certificate':{'actual':'bound'}})
 def test_same_topic_id_in_other_business_gets_separate_task(self):
  def fixture(key,topic_id,business):
   t=copy.deepcopy(FIXTURE);t['businessType']=business;return t,None
  with patch.object(topic,'cached_topic',side_effect=fixture):
   a=api.command({'action':'topic.adopt','store':'youhealth','topic':'123','businessType':'HOT_PRODUCT'})
   b=api.command({'action':'topic.adopt','store':'youhealth','topic':'123','businessType':'CUSTOMIZATION_PRODUCT'})
   again=api.command({'action':'topic.adopt','store':'youhealth','topic':'123','businessType':'HOT_PRODUCT'})
  self.assertNotEqual(a['id'],b['id']);self.assertEqual(a['id'],again['id'])
 def test_handoff_has_constraints_but_no_fabricated_assignment(self):
  bundle=topic.handoff(self.p)
  self.assertEqual(bundle['topicId'],'123');self.assertEqual(bundle['store'],'youhealth')
  self.assertEqual(bundle['attributeAssignments'],[])
  self.assertEqual(bundle['platformCheck'],'NOT_RUN')
  self.assertEqual(bundle['sourceFingerprint'],self.p['recruitment']['fingerprint'])
 def test_ambiguous_native_option_is_not_automatically_chosen(self):
  self.p['recruitment']['snapshot']['ruleSummary']['attrDTOList'][0]['attrValueDTOList'].append({'attrValueId':202,'attrValueName':'Powder'})
  store.save_product(self.p)
  p=topic.save(self.p['id'],1,{'attr:101':{'actual':'Powder','evidence':'SKU sheet'}})
  row=next(x for x in topic.report(p)['rows'] if x['key']=='attr:101')
  self.assertEqual(row['status'],'TO_CONFIRM');self.assertNotIn('assignment',row)

if __name__=='__main__':unittest.main()
