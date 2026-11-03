"""Rectification displays saved-draft evidence without confirming seller facts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import task_store as store
import topic_workflow as topic


class DraftReadbackTests(unittest.TestCase):
    def setUp(self):
        names = [('Protein Grams Per Serving', '20-29g'), ('Function', 'Immune & Anti-fatigue'),
                 ('Dosage Form', 'Gummy'), ('Shelf-Life', '24months')]
        self.product = {'id': 'P-fixture', 'revision': 6, 'facts': {'store': 'youhealth', 'mode': 'concept'},
            'recruitment': {'store': 'youhealth', 'topicId': '123', 'businessType': 'HOT_PRODUCT',
                'captured': 'fixture', 'fingerprint': 'fixture', 'entries': {}, 'snapshot': {
                    'id': '123', 'title': 'Fixture', 'ruleSummary': {'categoryId': '3', 'priceTo': 10,
                        'minOrdQtyTo': 2000, 'attrDTOList': [
                            {'productPropertyId': index, 'attrName': name, 'categoryId': '3',
                             'attrValueDTOList': [{'attrValueName': value, 'productValueId': index + 10}]}
                            for index, (name, value) in enumerate(names, 1)]}}},
            'attributePlan': {'sources': {'dosage_form': {'kind': 'DESIGN'}}},
            'draft': {'revision': 6, 'store': 'youhealth', 'expected_store': 'youhealth',
                'draft_id': '456', 'draft_url': 'https://post.alibaba.com/product/publish.htm?itemId=456&pubAction=draft',
                'job': 'fixture-job', 'readback_verified': True, 'category_id': '3',
                'evidence_file': 'readback-refresh.json', 'fields': {
                    key: {'expected': value, 'actual': value, 'matched': True}
                    for key, value in zip(('protein_per_serving', 'benefits', 'dosage_form', 'shelf_life'),
                                          (value for _, value in names))}}}

    def rows(self, product=None):
        return {row['key']: row for row in topic.report(product or self.product)['rows']}

    def test_saved_values_are_independent_of_supply_facts_and_platform_verdict(self):
        before = copy.deepcopy(self.product)
        rows = self.rows()
        for key, expected in [('category', '3'), ('attr:1', '20-29g'), ('attr:2', 'Immune & Anti-fatigue'),
                              ('attr:3', 'Gummy'), ('attr:4', '24months')]:
            with self.subTest(key=key):
                self.assertEqual(rows[key]['draftActual'], expected)
                self.assertEqual(rows[key]['actual'], '')
                self.assertEqual(rows[key]['status'], 'TO_CONFIRM')
        self.assertEqual(self.product, before)
        result = topic.report(self.product)
        self.assertFalse(result['readyForDraft'])
        self.assertFalse(result['readyToPublish'])
        self.assertEqual(result['platform']['status'], 'NOT_RUN')

    def test_wrong_revision_store_unverified_or_missing_draft_cannot_show_values(self):
        for key, value in [('revision', 5), ('revision', None), ('store', 'other'),
                           ('expected_store', 'other'), ('readback_verified', False), ('draft_id', ''),
                           ('draft_id', '999'), ('draft_url', 'https://[invalid')]:
            with self.subTest(key=key, value=value):
                product = copy.deepcopy(self.product)
                product['draft'][key] = value
                self.assertTrue(all(row['draftActual'] == '未回读' for row in self.rows(product).values()))
        self.product['facts']['store'] = 'other'
        self.assertTrue(all(row['draftActual'] == '未回读' for row in self.rows().values()))

    def test_missing_actual_or_unmatched_field_never_falls_back_to_expected(self):
        for field in ({'expected': 'Gummy', 'matched': True},
                      {'expected': 'Gummy', 'actual': '', 'matched': True},
                      {'expected': 'Gummy', 'actual': 'Gummy', 'matched': False}):
            with self.subTest(field=field):
                self.product['draft']['fields']['dosage_form'] = field
                self.assertEqual(self.rows()['attr:3']['draftActual'], '未回读')
        self.product['draft']['fields'].pop('dosage_form')
        self.assertEqual(self.rows()['attr:3']['draftActual'], '未回读')

    def test_unknown_requirement_and_absent_structured_report_keep_unread(self):
        self.product['recruitment']['snapshot']['ruleSummary']['attrDTOList'][2]['attrName'] = 'Unknown Attribute'
        self.assertEqual(self.rows()['attr:3']['draftActual'], '未回读')
        self.assertEqual(self.rows()['price']['draftActual'], '未回读')
        self.assertEqual(self.rows()['moq']['draftActual'], '未回读')

    def test_supply_fact_is_preserved_even_when_draft_differs(self):
        self.product['recruitment']['entries']['attr:3'] = {'actual': 'Capsule', 'evidence': 'Supplier sheet'}
        row = self.rows()['attr:3']
        self.assertEqual(row['actual'], 'Capsule')
        self.assertEqual(row['draftActual'], 'Gummy')
        self.assertEqual(row['status'], 'MISMATCH')

    def test_structured_pricing_uses_actual_tiers_from_same_saved_draft_only(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(store, 'STATE', Path(tmp)):
            root = store.STATE / 'runs' / 'fixture-job'
            root.mkdir(parents=True)
            report = {'product_id': self.product['id'], 'status': 'completed', 'post_save_verification': {
                'status': 'verified', 'resolved_draft_url': self.product['draft']['draft_url'],
                'structured_validation': {'pricing': {'matched': True, 'actual_unit': 'Piece/Pieces',
                    'expected_tiers': [{'qty': 9999, 'price': 99}],
                    'actual_tiers': [{'qty': '1000', 'price': '8.25'}, {'qty': '3000', 'price': '7.99'}]}}}}
            path = root / 'readback-refresh-report.json'
            def write():
                path.write_text(json.dumps(report), encoding='utf-8')
            write()
            self.assertEqual(self.rows()['price']['draftActual'], '8.25 Piece/Pieces')
            self.assertEqual(self.rows()['moq']['draftActual'], '1000 Piece/Pieces')
            for key, value in [('product_id', 'other'), ('status', 'failed')]:
                original = report[key]
                report[key] = value
                write()
                self.assertEqual(self.rows()['price']['draftActual'], '未回读')
                report[key] = original
            verified = report['post_save_verification']
            verified['resolved_draft_url'] = 'https://post.alibaba.com/product/publish.htm?itemId=999&pubAction=draft'
            write()
            self.assertEqual(self.rows()['price']['draftActual'], '未回读')
            verified['resolved_draft_url'] = self.product['draft']['draft_url']
            verified['structured_validation']['pricing'].pop('actual_tiers')
            write()
            self.assertEqual(self.rows()['price']['draftActual'], '未回读')
            self.assertEqual(self.rows()['moq']['draftActual'], '未回读')


if __name__ == '__main__':
    unittest.main()
