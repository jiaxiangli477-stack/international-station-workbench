"""Offline contracts for source-only attribute Skill and publication evidence."""
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[2]

def adapter():
    tree=ast.parse((BASE/'workbench/listing_adapter.py').read_text(encoding='utf-8-sig'))
    tree.body=[n for n in tree.body if not (isinstance(n,ast.Import) and any(a.name=='task_store' for a in n.names))]
    env={'__name__':'fixture'}; exec(compile(tree,'listing_adapter.py','exec'),env)
    return env

class PublicationTests(unittest.TestCase):
    product={'id':'P-local','facts':{'store':'fixture'},'draft':{'draft_id':'123','store':'fixture'}}
    def setUp(self):
        # This class exercises normalization only; the real source/file verifier
        # has separate signed-DOM fixtures in test_listing_browser_publication.py.
        self.source=patch('listing_browser_publication.verify_observation',return_value={'mapping_verified':True})
        self.source.start();self.addCleanup(self.source.stop)
    def observation(self,status='已发布'):
        return {'identity':{'verified':True,'account_id':'account'},
            'source':{'url':'https://i.alibaba.com/prod/product_manage','method':'GET','kind':'product_manager_row'},
            'observed_at':datetime.now(timezone.utc).isoformat(),
            'row':{'item_id':'123','draft_id':'123','status_text':status,'status_field':'商品状态'}}
    def test_without_authoritative_collector_is_unknown_not_unpublished(self):
        result=adapter()['read_publication_status'](self.product)
        self.assertEqual(result['status'],'unknown'); self.assertIsNone(result['published'])
    def test_unverified_manager_evidence_cannot_be_normalized_as_published(self):
        with patch('listing_browser_publication.verify_observation',side_effect=ValueError('missing real evidence')):
            result=adapter()['read_publication_status'](self.product,lambda _:self.observation(),expected_account='account')
        self.assertEqual(result['status'],'unknown');self.assertIsNone(result['published'])
    def test_readonly_collector_targets_id_account_and_retains_evidence(self):
        calls=[]
        def reader(target): calls.append(target); return self.observation()
        result=adapter()['read_publication_status'](self.product,reader,expected_account='account')
        self.assertEqual(result['status'],'published'); self.assertTrue(result['published'])
        self.assertEqual(calls,[{'store':'fixture','draft_id':'123','product_id':'123','expected_account':'account'}])
        self.assertEqual(result['authority']['method'],'GET')
        self.assertTrue(result['authority']['identity_verified']); self.assertTrue(result['evidence']['sha256'])
    def test_wrong_identity_id_host_or_unscoped_status_never_claims_publish(self):
        cases=[('identity','account_id','other'),('identity','verified',False),('row','item_id','other'),
            ('row','draft_id','other'),('row','status_field',''),('row','status_text','发布成功？'),
            ('source','method','POST'),('source','url','https://example.test/product_manage'),
            ('source','url','https://i.alibaba.com/prod/product_manage?access_token=secret')]
        for section,key,value in cases:
            with self.subTest(key=key,value=value):
                data=self.observation(); data[section][key]=value
                result=adapter()['read_publication_status'](self.product,lambda _:data,expected_account='account')
                self.assertEqual(result['status'],'unknown'); self.assertIsNone(result['published'])
                self.assertNotIn('secret',json.dumps(result))
    def test_draft_and_explicit_unpublished_are_distinct_from_unknown(self):
        for label,status in [('草稿','draft'),('已下架','unpublished')]:
            result=adapter()['read_publication_status'](self.product,lambda _:self.observation(label),expected_account='account')
            self.assertEqual(result['status'],status); self.assertFalse(result['published'])

class SourceOnlyTests(unittest.TestCase):
    def test_reviewed_content_entry_is_offline_and_does_not_mutate_skill(self):
        skill=BASE/'vendor/attribute-helper-v9.2.38/reviewed/alibaba-attribute-filler'
        self.assertFalse((skill/'node_modules').exists()); self.assertFalse((skill/'runtime').exists())
        root=BASE/'docs/single-approval/sandbox/listing-content'; root.mkdir(parents=True,exist_ok=True)
        before={str(p.relative_to(skill)):hashlib.sha256(p.read_bytes()).hexdigest() for p in skill.rglob('*') if p.is_file()}
        manifest={'product_id':'OFFLINE-FIXTURE','fields':{'product_name':'Whey Protein Powder','dosage_form':'Powder',
            'main_ingredient':'Whey Protein','product_specification':'100g / pouch','net_weight':'100g',
            'origin_country':'China','origin_province':'Guangdong'},'custom_attributes':[],
            'visual_evidence':{'net_weight':'100g','sources':['OFFLINE SYNTHETIC FIXTURE']}}
        (root/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        env=adapter()['environment']()
        command=[shutil.which('node'),str(BASE/'workbench/listing_runner.cjs'),'content',str(root),str(skill)]
        result=subprocess.run(command,cwd=root,env=env,capture_output=True,text=True,encoding='utf-8',timeout=60)
        (root/'content.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
        audit=json.loads((root/'reports/OFFLINE-FIXTURE-fill-content-audit.json').read_text(encoding='utf-8'))
        self.assertEqual(audit['status'],'passed')
        proposed=json.loads((root/'reports/OFFLINE-FIXTURE-fill-manifest.json').read_text(encoding='utf-8'))
        self.assertTrue(proposed['company_intro'])
        self.assertTrue(proposed['lead_time']['quantity'])
        self.assertTrue(proposed['logistics'])
        self.assertTrue({'company_intro','lead_time','logistics'} <= set(proposed['_adapter_effective_defaults']))
        self.assertIn('未连接浏览器',result.stdout)
        self.assertEqual(before,{str(p.relative_to(skill)):hashlib.sha256(p.read_bytes()).hexdigest() for p in skill.rglob('*') if p.is_file()})
        self.assertFalse(list((skill/'assets').glob('_tmp_*')))
        # Strict preflight still blocks real saving instead of pretending the ZIP provides evidence methods.
        check=subprocess.run([*command[:2],'preflight',str(root),str(skill)],cwd=root,env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
        self.assertNotEqual(check.returncode,0)
        report=json.loads((root/'listing-preflight.json').read_text(encoding='utf-8'))
        self.assertTrue(report['imageEvidence']['adapter']['implemented'])
        self.assertFalse(report['imageEvidence']['liveVerified'])
        self.assertTrue(report['imageEvidence']['required_live_evidence'])
        self.assertTrue(any('隐式默认' in message for message in report['blockers']))

if __name__=='__main__': unittest.main()
