import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
import cloud_team as cloud

class CloudInboxTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.original=cloud.STATE;cloud.STATE=Path(self.temp.name)
        self.addCleanup(setattr,cloud,'STATE',self.original)
        (cloud.STATE/'config.json').write_text('{}')
        self.item={'id':'9e752b42-7e63-44da-8c87-55d8c77e177d','store':'youhealth','taskType':'images','selected':['candidate-1'],'note':'参考包装','createdAt':'2026-10-27T00:00:00Z'}

    def test_sync_only_receives_requests_and_never_enqueues_skill(self):
        def remote(path,payload=None):return {'requests':[self.item]} if payload is None else {'ok':True}
        with patch.object(cloud,'request',side_effect=remote),patch.object(cloud.task_store,'enqueue') as enqueue:
            self.assertEqual(cloud.sync_once()['status'],'SUCCESS')
            self.assertEqual(cloud.rows()[0]['status'],'RECEIVED_LOCAL')
            cloud.sync_once();self.assertEqual(len(cloud.rows()),1)
            enqueue.assert_not_called()

    def test_changed_request_same_identity_is_rejected(self):
        cloud.save(dict(self.item,status='RECEIVED_LOCAL'))
        changed=dict(self.item,note='变更')
        with patch.object(cloud,'request',return_value={'requests':[changed]}):
            self.assertEqual(cloud.sync_once()['status'],'FAILED')
        self.assertEqual(cloud.rows()[0]['note'],'参考包装')

    def test_review_creates_only_draft_preflight_and_is_idempotent(self):
        cloud.save(dict(self.item,status='RECEIVED_LOCAL'))
        with patch('operations_api.command',return_value={'items':[{'id':'P-fixture','revision':1}]}) as command,patch.object(cloud,'request',return_value={'ok':True}):
            self.assertEqual(cloud.review(self.item['id'],True)['items'][0]['id'],'P-fixture')
            cloud.review(self.item['id'],True)
            command.assert_called_once_with({'action':'workflow.adopt','source':'selection','ids':['candidate-1'],'store':'youhealth'})

    def test_rejected_request_cannot_be_adopted(self):
        cloud.save(dict(self.item,status='RECEIVED_LOCAL'))
        with patch.object(cloud,'request',return_value={'ok':True}):cloud.review(self.item['id'],False)
        with self.assertRaises(ValueError):cloud.review(self.item['id'],True)

    def test_untrusted_ids_and_unbound_shop_are_rejected(self):
        for changes in ({'id':'../../config'},{'store':'not-bound'},{'selected':['../file']},{'selected':[]},{'taskType':'publish'},{'note':'x'*501}):
            with self.assertRaises(ValueError):cloud.validate(dict(self.item,**changes))

    def test_network_failure_preserves_local_inbox(self):
        cloud.save(dict(self.item,status='RECEIVED_LOCAL'))
        with patch.object(cloud,'request',side_effect=OSError()):self.assertEqual(cloud.sync_once()['status'],'FAILED')
        self.assertEqual(len(cloud.rows()),1)

    def seed_history(self):
        for _ in range(100):cloud.save(dict(self.item,id=str(uuid.uuid4()),status='REJECTED'))

    def test_pending_request_remains_visible_after_one_hundred_reviewed_requests(self):
        cloud.save(dict(self.item,status='RECEIVED_LOCAL'))
        self.seed_history()
        self.assertIn(self.item['id'],[r['id'] for r in cloud.rows()])

    def test_sync_keeps_old_review_and_retries_its_acknowledgement(self):
        cloud.save(dict(self.item,status='ADOPTED_LOCAL',items=[{'id':'P-fixture','revision':1}]))
        self.seed_history()
        with patch.object(cloud,'request',side_effect=lambda path,payload=None: {'requests':[self.item]} if payload is None else {'ok':True}) as remote:
            health=cloud.sync_once()
        self.assertEqual(health['status'],'SUCCESS')
        self.assertEqual(health['added'],0)
        remote.assert_called_with('/api/agent/status',{'id':self.item['id'],'status':'ADOPTED_LOCAL'})
        with patch('operations_api.command') as command:
            self.assertEqual(cloud.review(self.item['id'],True)['items'][0]['id'],'P-fixture')
            command.assert_not_called()

    def test_adopted_request_cannot_be_reported_as_successfully_rejected(self):
        cloud.save(dict(self.item,status='ADOPTED_LOCAL',items=[]))
        with self.assertRaises(ValueError):cloud.review(self.item['id'],False)

    def test_pending_count_includes_requests_beyond_the_display_limit(self):
        for _ in range(101):cloud.save(dict(self.item,id=str(uuid.uuid4()),status='RECEIVED_LOCAL'))
        with patch.object(cloud,'request',return_value={'requests':[]}):health=cloud.sync_once()
        self.assertEqual(health['pending'],101)
        self.assertEqual(len(cloud.rows()),100)

    def test_duplicate_identity_in_one_sync_cannot_replace_the_original_request(self):
        with patch.object(cloud,'request',side_effect=lambda path,payload=None: {'requests':[self.item,dict(self.item,note='changed')]} if payload is None else {'ok':True}):
            self.assertEqual(cloud.sync_once()['status'],'FAILED')
        self.assertEqual(cloud.rows()[0]['note'],self.item['note'])

    def test_real_adoption_preserves_reference_boundary_and_does_not_start_jobs(self):
        fixture={'id':'candidate-1','title':'Fixture powder','form':'Powder','markets':[{'country':'US'}],
                 'differentiation':'Original design','product_references':[{'url':'https://example.com/product'}]}
        cloud.save(dict(self.item,status='RECEIVED_LOCAL'))
        state=cloud.STATE/'operations'
        with patch.object(cloud.task_store,'STATE',state),patch.object(cloud.task_store,'DB',state/'test.sqlite'), \
             patch('selection_jobs.source',return_value=[fixture]),patch.object(cloud,'request',return_value={'ok':True}):
            result=cloud.review(self.item['id'],True)
            product=cloud.task_store.product(result['items'][0]['id'])
            self.assertEqual(product['facts']['mode'],'concept')
            self.assertEqual(product['facts']['store'],'youhealth')
            self.assertEqual(product['facts']['formula'],'')
            self.assertEqual(cloud.task_store.records('jobs'),[])
            self.assertIn('外部参考',product['references'][0]['scope'])
