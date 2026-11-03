import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import bridge_catalog
import bridge_reads
from bridge_materialization import verified_summary


class BridgeMappingTests(unittest.TestCase):
    def test_generating_tools_are_not_classified_as_readonly(self):
        row = bridge_catalog.describe('product', 'icbu.product.ai-image-generate-facade', {'success': True, 'mutating': False, 'params': []})
        self.assertEqual(row['risk'], 'confirm')
        self.assertEqual(row['execution'], 'NOT_CONNECTED')

    def test_query_intent_without_mutation_contract_is_explicitly_distinct(self):
        row = bridge_catalog.describe('advisor', 'icbu.advisor.data-advisor-shop-summary', {'success': True, 'params': []})
        self.assertEqual(row['risk'], 'query')
        self.assertNotEqual(row['risk'], 'read')

    def test_topic_normalization_keeps_reference_boundary_and_rejects_bad_image(self):
        records = [{'id': 42, 'title': 'Example', 'categoryIds': '1', 'sampleImgUrl': 'javascript:alert(1)', 'capacityNameList': ['OEM']}]
        value = bridge_reads.normalize_topics(records, {'value': {'1': {'name': 'Nutrition'}}})[0]
        self.assertEqual(value['image'], '')
        self.assertEqual(value['categories'], ['Nutrition'])
        self.assertIn('待', value['review'])

    def test_unbound_store_never_calls_gateway(self):
        with patch.object(bridge_reads, '_call') as call:
            self.assertEqual(bridge_reads.refresh_topics('not-bound')['status'], 'FAILED')
            call.assert_not_called()

    def test_compacted_result_requires_complete_matching_materialized_window(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            conv = root / 'conv.json'
            conv.write_text(json.dumps({'meta':{'startDate':'2026-10-09','endDate':'2026-10-15','failureRatio':0,'totalAccounts':2,'totalFailedAccounts':0,'totalConversations':1},'conversations':[{'conversationId':'c1'}]}))
            summary = verified_summary({'data':{'artifact_id':'sample'}}, conv, 'conversations', '2026-10-09', '2026-10-15', expected_accounts=2)
            self.assertEqual(summary['status'], 'success')
            self.assertIsNone(verified_summary({}, conv, 'conversations', '2026-10-10', '2026-10-15', expected_accounts=2))
            msg = root / 'messages.json'
            msg.write_text(json.dumps({'meta':{'startDate':'2026-10-09','endDate':'2026-10-15','failureRatio':0,'sourceConversationFile':str(conv),'totalInputConversations':1,'sourceTotalConversations':1,'totalMessages':1,'totalConversationsWithMessages':1},'conversations':[{'conversationId':'c1','messages':[{'text':'fixture'}]}]}))
            self.assertEqual(verified_summary({}, msg, 'messages', '2026-10-09', '2026-10-15')['totalMessages'], 1)
            data=json.loads(msg.read_text());data['meta']['failureRatio']=0.2;msg.write_text(json.dumps(data))
            self.assertIsNone(verified_summary({}, msg, 'messages', '2026-10-09', '2026-10-15'))


if __name__ == '__main__':
    unittest.main()
