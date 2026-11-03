import copy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import task_store as store
import selection_jobs as selection

ITEM={'id':'candidate1','title':'Fixture powder','form':'Powder','markets':[{'country':'US'}],
 'differentiation':'Original private label packaging','gate':'HOLD','screening':{'status':'HOLD'},
 'product_references':[{'name':'Public reference','url':'https://example.com/product','image_url':'https://example.com/image.png'}]}

class SelectionJobsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=(store.STATE,store.DB)
  store.STATE=Path(self.tmp.name);store.DB=store.STATE/'test.sqlite'
 def tearDown(self):
  store.STATE,store.DB=self.old;self.tmp.cleanup()
 def test_concept_preview_does_not_require_price_formula_or_create_product(self):
  with patch.object(selection,'source',return_value=[copy.deepcopy(ITEM)]):plan=selection.preview(['candidate1'])
  self.assertTrue(plan['items'][0]['eligible']);self.assertEqual(store.records('products'),[])
  self.assertEqual(plan['items'][0]['kind'],'packaging')
 def test_confirmed_submission_enqueues_packaging_without_listing(self):
  with patch.object(selection,'source',return_value=[copy.deepcopy(ITEM)]),patch('skill_jobs.capability',return_value={'available':True}):
   plan=selection.preview(['candidate1'])
   with self.assertRaises(ValueError):selection.start(plan['items'],False)
   result=selection.start(plan['items'],True)
  self.assertEqual(len(result['started']),1);self.assertEqual(store.records('jobs')[0]['kind'],'packaging')
  self.assertEqual(store.records('products')[0]['facts']['mode'],'concept')
  self.assertEqual(store.records('products')[0]['facts']['formula'],'')
 def test_excluded_or_changed_candidates_cannot_be_queued(self):
  item=copy.deepcopy(ITEM);item['screening']['status']='EXCLUDED'
  with patch.object(selection,'source',return_value=[item]):
   self.assertFalse(selection.preview(['candidate1'])['items'][0]['eligible'])
  with patch.object(selection,'source',return_value=[copy.deepcopy(ITEM)]):plan=selection.preview(['candidate1'])
  item=copy.deepcopy(ITEM);item['title']='Changed'
  with patch.object(selection,'source',return_value=[item]),patch('skill_jobs.capability',return_value={'available':True}):
   with self.assertRaises(ValueError):selection.start(plan['items'],True)
 def test_repeated_submission_does_not_duplicate_active_jobs(self):
  with patch.object(selection,'source',return_value=[copy.deepcopy(ITEM)]),patch('skill_jobs.capability',return_value={'available':True}):
   plan=selection.preview(['candidate1']);selection.start(plan['items'],True);selection.start(plan['items'],True)
  self.assertEqual(len(store.records('jobs')),1)
 def test_packaging_review_continues_visuals_and_never_listing(self):
  import operations_api as api
  with patch.object(selection,'source',return_value=[copy.deepcopy(ITEM)]),patch('skill_jobs.capability',return_value={'available':True}):
   plan=selection.preview(['candidate1']);result=selection.start(plan['items'],True)
  product=store.product(result['started'][0]['product']);job=store.records('jobs')[0]
  store.job_update(job['id'],status='SUCCESS')
  store.commit_output(product['id'],product['revision'],'packaging',{'job':job['id'],'revision':product['revision'],'images':[]})
  selection.advance(product['id'])
  self.assertEqual(store.product(product['id'])['selectionFlow']['status'],'PACKAGING_REVIEW')
  api.command({'action':'product.approve','id':product['id'],'phase':'packaging','revision':product['revision'],'artifactJob':job['id']})
  self.assertEqual(store.records('jobs')[0]['kind'],'visual')
  self.assertFalse(any(j['kind']=='listing' for j in store.records('jobs')))

if __name__=='__main__':unittest.main()
