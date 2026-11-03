"""The UI detection action consumes only verified server evidence, never client claims."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import operations_api as api
import recruitment_detect as detect
import task_store as store

class DetectionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.paths=patch.multiple(store,STATE=Path(self.temp.name),DB=Path(self.temp.name)/'db.sqlite');self.paths.start();self.addCleanup(self.paths.stop)
        self.p=store.create_product('topic:fixture','Fixture',facts={'store':'youhealth','mode':'concept'})
        self.p.update(recruitment={'store':'youhealth','topicId':'133','fingerprint':'a'*64},
                      draft={'status':'completed','store':'youhealth','revision':1,'draft_id':'123','readback_verified':True},
                      heroApproval={'signature':'keep'},visual={'job':'keep'})
        store.save_product(self.p)
        scope=detect.target(self.p);scope.pop('expected_account')
        self.result=dict(scope,status='FAILED',meet=False,items=[{'itemCode':'need_pic_match','meet':False}],checkedAt='fixture')

    def test_false_eligibility_is_saved_as_failed_without_changing_product_facts_or_approval(self):
        before=copy.deepcopy(self.p)
        with patch.object(detect,'collect',return_value=self.result) as collect,patch.object(detect,'current',return_value=self.result):
            out=api.command({'action':'recruitment.detect','id':self.p['id'],'revision':1,'meet':True,'status':'PASSED'})
        collect.assert_called_once();self.assertEqual(out['platformDetection']['status'],'FAILED')
        self.assertFalse(out['platformDetection']['meet'])
        for key in ['facts','heroApproval','visual','draft']:self.assertEqual(out[key],before[key])
        self.assertEqual(store.records('jobs'),[])

    def test_changed_revision_and_unverified_evidence_cannot_start_or_overwrite(self):
        with patch.object(detect,'collect') as collect:
            with self.assertRaisesRegex(ValueError,'版本'):
                api.command({'action':'recruitment.detect','id':self.p['id'],'revision':0})
            collect.assert_not_called()
        with patch.object(detect,'collect',return_value=self.result),patch.object(detect,'current',return_value={'status':'STALE'}):
            with self.assertRaisesRegex(ValueError,'证据'):
                api.command({'action':'recruitment.detect','id':self.p['id'],'revision':1})
        self.assertNotIn('platformDetection',store.product(self.p['id']))

    def test_concurrent_topic_change_keeps_new_scope_and_rejects_old_result(self):
        def collect(*args):
            p=store.product(self.p['id']);p['recruitment']['fingerprint']='b'*64;store.save_product(p)
            return self.result
        with patch.object(detect,'collect',side_effect=collect),patch.object(detect,'current',return_value=self.result):
            with self.assertRaisesRegex(ValueError,'变化'):
                api.command({'action':'recruitment.detect','id':self.p['id'],'revision':1})
        self.assertNotIn('platformDetection',store.product(self.p['id']))

if __name__=='__main__':unittest.main()
