"""Recruitment constraints overlay only their exact original Skill attributes."""
import copy
import unittest

import recruitment_listing_overlay as overlay


def requirement(name, field_id, value, option_id):
    return {'key': 'attr:' + field_id, 'kind': 'attribute', 'name': name,
            'fieldId': field_id, 'categoryId': '3', 'expected': [value],
            'options': [{'name': value, 'id': option_id}]}


class RecruitmentOverlayTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {'fields': {'benefits': 'Original function', 'product_advantages': 'Original advantage'},
                         'custom_attributes': [{'name': 'Private label', 'value': 'OEM'}],
                         'company_intro': 'Original company', 'faqs': [{'answer': 'Original FAQ'}],
                         'pricing': {'unit': 'pouch', 'tiers': [{'qty': 500, 'price': 1.5}]},
                         'logistics': {'weight': 1}, 'lead_time': {'days': 30},
                         'images': {'main': ['D:/fixture/m1.png'], 'detail': ['D:/fixture/d1.png']}}
        self.rows = [requirement('Function', '101', 'Providing Energy', '201'),
                     requirement('Applicable People', '102', 'Adult', '202'),
                     requirement('Shelf-Life', '103', '24months', '203'),
                     requirement('Product Benefits', '104', 'muscle growth', '204')]
        self.handoff = {'topicId': 'topic', 'sourceFingerprint': 'snapshot', 'requirements': [
            {'key': 'category', 'kind': 'category', 'expected': ['3']}, *self.rows,
            {'key': 'price', 'kind': 'range', 'maximum': 10},
            {'key': 'moq', 'kind': 'range', 'maximum': 100},
            {'key': 'certificate', 'kind': 'manual', 'name': 'Certificate'}], 'attributeAssignments': []}
        self.config = {'category_id': '3', 'dropdown_options': {
            'benefits': ['Providing Energy'], 'target_audience': ['Adult'],
            'shelf_life': ['24months'], 'product_advantages': ['muscle growth']}}

    def compose(self, **kwargs):
        return overlay.compose(self.manifest, self.handoff, '3', category_config=self.config, **kwargs)

    def test_offline_overlay_keeps_original_business_content_and_uses_distinct_skill_keys(self):
        before = copy.deepcopy(self.manifest)
        result = self.compose()
        self.assertTrue(result['ready'])
        self.assertEqual(result['manifest']['fields'], {'benefits': 'Providing Energy',
            'target_audience': 'Adult', 'shelf_life': '24months', 'product_advantages': 'muscle growth'})
        self.assertEqual(self.manifest, before)
        for key in set(before) - {'fields'}: self.assertEqual(result['manifest'][key], before[key])
        self.assertEqual(len(result['field_replacements']), 4)
        for row in result['field_replacements']:
            self.assertEqual(row['source']['kind'], 'DESIGN')
            self.assertEqual(row['verification'], 'original-skill-runtime-required')
        self.assertEqual(result['category_constraint']['expected'], ['3'])
        self.assertEqual({row['key'] for row in result['passthrough']}, {'price', 'moq', 'certificate'})

    def test_category_is_a_route_constraint_and_never_an_attribute_replacement(self):
        result = overlay.compose(self.manifest, self.handoff, 'other', category_config=self.config)
        self.assertFalse(result['ready'])
        self.assertFalse(result['category_constraint']['matched'])
        self.assertEqual(result['manifest'], self.manifest)

    def test_native_topic_ids_can_propose_an_option_missing_from_sampled_skill_config(self):
        self.rows[0]['expected'] = ['Immune & Anti-fatigue']
        self.rows[0]['options'] = [{'id': '201', 'name': 'Immune & Anti-fatigue'}]
        result = self.compose()
        self.assertTrue(result['ready'])
        self.assertEqual(result['manifest']['fields']['benefits'], 'Immune & Anti-fatigue')
        replacement=next(row for row in result['field_replacements'] if row['field']=='benefits')
        self.assertEqual((replacement['fieldId'],replacement['optionId'],replacement['categoryId']),('101','201','3'))
        self.assertEqual(replacement['source']['kind'],'DESIGN')
        self.assertEqual(replacement['source']['fingerprint'],'snapshot')
        self.assertEqual(replacement['verification'],'original-skill-runtime-required')

    def test_missing_native_option_evidence_cannot_bypass_sampled_skill_config(self):
        for fault in ('field_id','option_id','category_id','topic_id','source_fingerprint','whitespace_source','expected_name','option_id_zero'):
            with self.subTest(fault=fault):
                handoff=copy.deepcopy(self.handoff)
                row=handoff['requirements'][1]
                row.update(expected=['Immune & Anti-fatigue'],options=[{'id':'201','name':'Immune & Anti-fatigue'}])
                if fault=='field_id':row['fieldId']=''
                elif fault=='option_id':row['options'][0]['id']=''
                elif fault=='category_id':row['categoryId']='other'
                elif fault=='topic_id':handoff['topicId']=''
                elif fault=='source_fingerprint':handoff['sourceFingerprint']=''
                elif fault=='whitespace_source':handoff['sourceFingerprint']='   '
                elif fault=='expected_name':row['expected']=['Different option']
                else:row['options'][0]['id']='0'
                result=overlay.compose(self.manifest,handoff,'3',category_config=self.config)
                self.assertFalse(result['ready'])
                self.assertEqual(result['manifest']['fields']['benefits'],'Original function')

    def test_page_evidence_remains_required_when_current_fields_are_provided(self):
        self.rows[0].update(expected=['Immune & Anti-fatigue'],options=[{'id':'201','name':'Immune & Anti-fatigue'}])
        self.assertFalse(self.compose(page_fields=[])['ready'])
        for options in ([],[{'id':'wrong','name':'Immune & Anti-fatigue'}],[{'id':'201','name':'Other name'}]):
            page=[{'key':key,'fieldId':row['fieldId'],'categoryId':'3','options':copy.deepcopy(row['options'])}
                  for key,row in zip(('benefits','target_audience','shelf_life','product_advantages'),self.rows)]
            page[0]['options']=options
            with self.subTest(options=options):
                result=self.compose(page_fields=page)
                self.assertFalse(result['ready'])
                self.assertEqual(result['manifest']['fields']['benefits'],'Original function')

    def test_explicitly_removed_field_stays_blocked_even_with_complete_native_topic_ids(self):
        self.rows[0].update(expected=['Immune & Anti-fatigue'],options=[{'id':'201','name':'Immune & Anti-fatigue'}])
        self.config['skip_fields']=['benefits']
        result=self.compose()
        self.assertFalse(result['ready'])
        self.assertTrue(any(row['code']=='unsupported_field' for row in result['pending']))

    def test_multiple_options_use_current_matching_value_or_explicit_assignment_only(self):
        self.rows[0].update(expected=['Providing Energy', 'Antioxidant'], options=[
            {'id': '201', 'name': 'Providing Energy'}, {'id': '205', 'name': 'Antioxidant'}])
        self.config['dropdown_options']['benefits'].append('Antioxidant')
        self.assertTrue(any(row['code'] == 'ambiguous_option' for row in self.compose()['pending']))
        self.handoff['attributeAssignments'] = [{'fieldId': '101', 'categoryId': '3',
                                                'valueIds': ['205'], 'value': 'Antioxidant'}]
        self.assertEqual(self.compose()['manifest']['fields']['benefits'], 'Antioxidant')

    def test_current_page_validates_native_ids_and_can_supply_an_option_missing_from_sampled_config(self):
        page = [{'key': key, 'fieldId': row['fieldId'], 'categoryId': '3', 'options': row['options']}
                for key, row in zip(('benefits', 'target_audience', 'shelf_life', 'product_advantages'), self.rows)]
        result = self.compose(page_fields=page)
        self.assertTrue(result['ready'])
        self.assertTrue(all(row['verification'] == 'current-page-verified' for row in result['field_replacements']))
        page[0]['options'][0] = {'id': '201', 'name': 'Immune & Anti-fatigue'}
        self.rows[0].update(expected=['Immune & Anti-fatigue'], options=[page[0]['options'][0]])
        self.assertEqual(self.compose(page_fields=page)['manifest']['fields']['benefits'], 'Immune & Anti-fatigue')

    def test_wrong_native_page_field_option_or_category_is_rejected(self):
        for fault in ('fieldId', 'categoryId', 'optionId', 'key'):
            page = [{'key': key, 'fieldId': row['fieldId'], 'categoryId': '3', 'options': copy.deepcopy(row['options'])}
                    for key, row in zip(('benefits', 'target_audience', 'shelf_life', 'product_advantages'), self.rows)]
            if fault == 'optionId': page[0]['options'][0]['id'] = 'wrong'
            elif fault == 'key': page[0]['key'] = 'product_advantages'
            else: page[0][fault] = 'wrong'
            with self.subTest(fault=fault):
                result = self.compose(page_fields=page)
                self.assertFalse(result['ready'])
                self.assertEqual(result['manifest']['fields']['benefits'], 'Original function')

    def test_unknown_field_cannot_be_guessed_from_a_similar_name(self):
        self.rows[0]['name'] = 'Benefits maybe'
        result = self.compose()
        self.assertTrue(any(row['code'] == 'unknown_field' for row in result['pending']))

    def test_changed_field_source_is_design_and_never_inherits_confirmed_provenance(self):
        self.manifest['field_sources'] = {'fields.benefits': {'kind': 'CONFIRMED', 'source': 'Old value evidence'}}
        result = self.compose()
        self.assertEqual(result['manifest']['field_sources']['fields.benefits']['kind'], 'DESIGN')

    def test_legacy_readable_single_option_can_use_config_without_inventing_ids(self):
        self.rows[0].update(fieldId='', options=[])
        result = self.compose()
        self.assertTrue(result['ready'])
        replacement = result['field_replacements'][0]
        self.assertEqual(replacement['fieldId'], '')
        self.assertEqual(replacement['optionId'], '')
        self.assertEqual(replacement['verification'], 'original-skill-runtime-required')

    def test_no_recruitment_leaves_manifest_untouched(self):
        result = overlay.compose(self.manifest, None, '3')
        self.assertTrue(result['ready']); self.assertEqual(result['manifest'], self.manifest)
        self.assertIsNot(result['manifest'], self.manifest)

    def test_real_topic_handoff_without_manual_assignments_still_prepares_skill_fields(self):
        import topic_workflow
        snapshot = {'id': '123', 'title': 'Fixture', 'businessType': 'CUSTOMIZATION_PRODUCT',
                    'categoryIds': ['3'], 'ruleSummary': {'categoryId': '3', 'attrDTOList': [
                        {'productPropertyId': 101, 'attrName': 'Function', 'categoryId': 3,
                         'attrValueDTOList': [{'productValueId': 201, 'attrValueName': 'Providing Energy'}]}]}}
        product = {'facts': {'store': 'fixture'}, 'recruitment': {
            'store': 'fixture', 'topicId': '123', 'businessType': 'CUSTOMIZATION_PRODUCT',
            'fingerprint': 'real-handoff-shape', 'captured': 'fixture', 'snapshot': snapshot, 'entries': {}}}
        handoff = topic_workflow.handoff(product)
        self.assertEqual(handoff['attributeAssignments'], [])
        result = overlay.compose(self.manifest, handoff, '3', category_config=self.config)
        self.assertTrue(result['ready'])
        self.assertEqual(result['manifest']['fields']['benefits'], 'Providing Energy')
        self.assertEqual(result['field_replacements'][0]['fieldId'], '101')
        self.assertEqual(result['field_replacements'][0]['optionId'], '201')

    def test_conflicting_marked_requirements_cannot_overwrite_the_same_skill_field(self):
        self.handoff['requirements'].append(requirement('Function', '105', 'Antioxidant', '205'))
        self.config['dropdown_options']['benefits'].append('Antioxidant')
        result = self.compose()
        self.assertFalse(result['ready'])
        self.assertEqual(result['manifest']['fields']['benefits'], 'Original function')
        self.assertEqual(sum(row['code'] == 'conflicting_requirements' for row in result['pending']), 2)

    def test_assignment_must_select_a_real_requirement_option(self):
        self.handoff['attributeAssignments'] = [{'fieldId': '101', 'categoryId': '3',
                                                'valueIds': ['999'], 'value': 'Invented'}]
        result = self.compose()
        self.assertFalse(result['ready'])
        self.assertEqual(result['manifest']['fields']['benefits'], 'Original function')

    def test_existing_multiselect_value_shape_is_preserved(self):
        self.manifest['fields']['benefits'] = ['Original function']
        result = self.compose()
        self.assertEqual(result['manifest']['fields']['benefits'], ['Providing Energy'])


if __name__ == '__main__': unittest.main()
