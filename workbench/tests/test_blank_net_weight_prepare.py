"""The user exception affects only copied original-Skill run material."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import listing_adapter as adapter


class BlankNetWeightPreparationTests(unittest.TestCase):
    def test_blank_weight_authorization_cannot_mask_platform_required_or_failed_save_verification(self):
        report={'status':'completed','post_save_verification':{'status':'verified','missing_required':[]},
                'category_routing':{'selected_cat_id':'3'},'images':{'main_count':1,'detail_count':0}}
        receipt={'draft_id':'123','draft_url':'https://post.alibaba.com/product/publish.htm?itemId=123',
                 'store':'fixture','published':False,'actualAccountVerified':True,'category_id':'3',
                 'fields':{'product_name':{'matched':True,'actual':'Synthetic'}},
                 'acceptancePolicy':'original-skill-draft-review','image_review_required':True,'image_readback_verified':False,
                 'intentional_blank_fields':['net_weight'],
                 'image_checks':[{'slot':'m1','uploadInvoked':True,'reviewRequired':True,'exportHash':'hash'}]}
        delivery=[{'slot':'m1','section':'main','exportHash':'hash'}]
        self.assertTrue(adapter.validate_receipt(report,receipt,'fixture','3',delivery))
        for reason in ('missing_required','failed_save'):
            actual=copy.deepcopy(report)
            if reason=='missing_required':actual['post_save_verification']['missing_required']=['净重']
            else:actual['status']='completed_without_verification'
            with self.subTest(reason=reason),self.assertRaises(ValueError):
                adapter.validate_receipt(actual,receipt,'fixture','3',delivery)

    def test_only_original_skill_exact_authorization_is_forwarded_without_changing_product(self):
        sandbox=Path(__file__).resolve().parents[2]/'docs/blank-net-weight-test'
        sandbox.mkdir(parents=True,exist_ok=True)
        for mechanism,flag,enabled in [('original-skill-v1',True,True),('original-skill-v1',1,False),('legacy',True,False)]:
            with self.subTest(mechanism=mechanism,flag=flag),tempfile.TemporaryDirectory(dir=sandbox) as directory:
                root=Path(directory)
                product={'id':'fixture','revision':6,'facts':{'store':'fixture'},'workflow':{'listingMechanism':mechanism,'allowMissingNetWeight':flag},
                         'attributePlan':{'fingerprint':'unchanged','manifest':{'fields':{'product_name':'Synthetic','net_weight':'35g'}}},
                         'visual':{'job':'existing'},'heroApproval':{'signed':'unchanged'}}
                before=copy.deepcopy(product)
                def inspect(*args,**kwargs):
                    (root/'skill-routing.json').write_text(json.dumps({'route':{'category':'supplement'},'categories':{
                        'supplement':{'catId':'3','config':{'category_id':'3'}}}}),encoding='utf-8')
                    return SimpleNamespace(returncode=0)
                def content(*args,**kwargs):return json.loads((root/'manifest.json').read_text(encoding='utf-8')),[]
                with patch.object(adapter,'command',return_value=['offline']),patch.object(adapter,'environment',return_value={}),\
                     patch.object(adapter.subprocess,'run',side_effect=inspect),patch('topic_workflow.handoff',return_value=None),\
                     patch.object(adapter,'export_images',return_value=[]),patch.object(adapter,'prepare_content',side_effect=content):
                    result=adapter.prepare_original_skill(product,root,Path('offline-skills'))
                context=json.loads((root/'listing-context.json').read_text(encoding='utf-8'))
                self.assertIs(context['allowMissingNetWeight'],enabled)
                prepared=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
                self.assertEqual(prepared['fields']['net_weight'],'' if enabled else '35g')
                self.assertEqual(product,before);self.assertFalse(result['draftSaved'])
                if enabled:self.assertIn('用户要求净重留空，后台是否允许保存尚待实际校验',result['message'])


if __name__=='__main__':unittest.main()
