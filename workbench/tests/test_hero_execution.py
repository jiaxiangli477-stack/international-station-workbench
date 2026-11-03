"""Single-module executor and exact approved-hero reuse; no model or platform calls."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import skill_jobs
import task_store as store


class HeroExecutionTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT.parent/'docs/single-approval/hero-tests';folder.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=folder)
        self.root=Path(self.temp.name)
        self.paths=patch.multiple(store,STATE=self.root,DB=self.root/'test.sqlite');self.paths.start()

    def tearDown(self):
        self.paths.stop();self.temp.cleanup()

    def test_hero_is_only_one_real_m1(self):
        Image.new('RGB',(1000,1000),'blue').save(self.root/'m1.png')
        result={'status':'completed','images':[{'slot':'m1','file':'m1.png'}]}
        self.assertEqual(skill_jobs.validate_result(self.root,'hero',result),result['images'])
        result['images'][0]['slot']='A0'
        with self.assertRaises(ValueError):skill_jobs.validate_result(self.root,'hero',result)

    def test_approved_hero_reuse_binds_real_pixels_and_keeps_original(self):
        import hero_execution
        from native_template_runner import image_hash
        source=self.root/'runs/source';source.mkdir(parents=True)
        Image.new('RGB',(1000,1000),'blue').save(source/'m1.png')
        product={'id':'P','revision':1,'hero':{'job':'source','images':[{'slot':'m1','file':'m1.png'}]}}
        scope={'heroJob':'source','pixelHash':image_hash(source/'m1.png')}
        target=self.root/'runs/target';target.mkdir()
        policy={}
        with patch('single_approval_flow.require_hero',return_value=scope):
            hero_execution.prepare_reuse(product,target,policy)
            row=hero_execution.verify_reuse(product,target,{'slot':'m1','file':'images/m1.png'},policy)
            self.assertEqual(row['approvedHeroJob'],'source')
            self.assertEqual(image_hash(target/'images/m1.png'),scope['pixelHash'])
            self.assertTrue((source/'m1.png').is_file())
            Image.new('RGB',(1000,1000),'red').save(target/'images/m1.png')
            with self.assertRaises(ValueError):hero_execution.verify_reuse(product,target,{'slot':'m1','file':'images/m1.png'},policy)

    def test_publication_refresh_ignores_client_assertion(self):
        import operations_api
        p=store.create_product('synthetic:publication','Synthetic',facts={'store':'youhealth'})
        result=operations_api.command({'action':'publication.refresh','id':p['id'],'published':True,'status':'published'})
        self.assertEqual(result['publication']['status'],'unknown')
        self.assertIsNone(result['publication']['published'])

    def test_migrated_waiting_task_does_not_restart_generation(self):
        import production_flow
        p=store.create_product('synthetic:hold','Synthetic',facts={'mode':'concept'})
        p['workflow']={'status':'ACTIVE','revision':1,'migrationHold':True}
        store.save_product(p)
        production_flow.advance(p['id'])
        self.assertEqual(store.records('jobs'),[])

    def test_unmapped_collector_result_never_claims_publication(self):
        import listing_adapter
        product={'facts':{'store':'youhealth'},'draft':{'draft_id':'123','product_id':'123','store':'youhealth'}}
        with patch('listing_publication.collect',return_value={'row':{'status':'published'}}) as collector:
            result=listing_adapter.refresh_publication(product,self.root/'publication')
        self.assertEqual(collector.call_count,1)
        self.assertEqual(result['status'],'unknown')
        self.assertIsNone(result['published'])


if __name__=='__main__':unittest.main()
