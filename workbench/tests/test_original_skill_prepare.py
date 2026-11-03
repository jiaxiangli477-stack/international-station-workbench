import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import listing_adapter as adapter


class OriginalSkillPrepareTests(unittest.TestCase):
    def test_original_skill_keeps_its_steps_and_only_overlays_marked_attributes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'run';calls=[]
            fields={'product_name':'Energy Gel','main_ingredient':'Synthetic Ingredient','benefits':'Old Function',
                    'target_audience':'Old Audience','shelf_life':'12months','product_advantages':'Old Advantage'}
            manifest={'fields':fields,'pricing':{'source':'synthetic'},'company_intro':'Original company','custom_attributes':[]}
            product={'id':'p','revision':1,'facts':{'store':'youhealth'},'attributePlan':{'manifest':manifest,'fingerprint':'base'},'visual':{'job':'visual'}}
            pairs=[('Function','Providing Energy'),('Applicable People','Adult'),('Shelf-Life','24months'),('product benefits','Immune Support')]
            handoff={'topicId':'test','sourceFingerprint':'test','requirements':[{'kind':'attribute','name':name,'expected':[value]} for name,value in pairs]}
            config={'category_id':'202029902','dropdown_options':{'benefits':['Providing Energy'],'target_audience':['Adult'],'shelf_life':['24months'],'product_advantages':['Immune Support']}}
            def inspect(command,**kwargs):
                calls.append(command)
                (root/'skill-routing.json').write_text(json.dumps({'route':{'category':'supplement'},'categories':{'supplement':{'catId':'202029902','config':config}}}),encoding='utf-8')
                return SimpleNamespace(returncode=0)
            def content(folder,skills,original_flow=False):
                self.assertTrue(original_flow)
                return json.loads((folder/'manifest.json').read_text(encoding='utf-8')),[]
            with patch.object(adapter,'command',return_value=['node','listing_runner.cjs','inspect']),patch.object(adapter.subprocess,'run',side_effect=inspect),patch('topic_workflow.handoff',return_value=handoff),patch.object(adapter,'export_images',return_value=[{'slot':'m1'}]),patch.object(adapter,'prepare_content',side_effect=content):
                result=adapter.prepare_original_skill(product,root,Path('skills'))
            prepared=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
            context=json.loads((root/'listing-context.json').read_text(encoding='utf-8'))
            self.assertEqual(result['status'],'READY');self.assertFalse(result['draftSaved'])
            self.assertEqual(prepared['fields']['benefits'],'Providing Energy')
            self.assertEqual(prepared['fields']['product_advantages'],'Immune Support')
            self.assertEqual(prepared['fields']['target_audience'],'Adult')
            self.assertEqual(prepared['fields']['shelf_life'],'24months')
            for key in ['pricing','company_intro','custom_attributes']:self.assertEqual(prepared[key],manifest[key])
            self.assertEqual(manifest['fields']['benefits'],'Old Function')
            self.assertEqual(context['listingMechanism'],'original-skill-v1')
            self.assertEqual(len(result['field_replacements']),4);self.assertEqual(len(calls),1)


if __name__=='__main__':unittest.main()
