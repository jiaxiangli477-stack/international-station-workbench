import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import task_store as store
import operations_api as api
import native_template_runner as runner


class NativeChainTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=store.STATE,store.DB
        self.root=Path(self.temp.name);store.STATE=self.root;store.DB=self.root/'test.sqlite'
        self.p=store.create_product('native:test','Test',facts={'mode':'concept','market':'INTERNAL_B2B','form':'Oral Liquid','design':'Approved concept'})
        self.p.update(packaging={'revision':1,'job':'package','images':[],'executionSource':'codex-native-imagegen'},
                      selectionFlow={'revision':1,'status':'STOPPED','target':'PACKAGING'})
        store.save_product(self.p)

    def tearDown(self):
        store.STATE,store.DB=self.old;self.temp.cleanup()

    def test_latest_b2b_skill_contract_defaults_to_six_main_images_and_twelve_details(self):
        import skill_jobs,native_skill_jobs
        policy=native_skill_jobs.contract(skill_jobs.SKILLS)
        self.assertEqual(len(policy['templates']),18)
        self.assertNotIn('m7',policy['templates'])
        self.assertEqual(policy['templates']['m6']['file'],'m6-process-facts-stacked.html')
        self.assertIn('reference_sample.py',policy['scriptHashes'])
        altered=dict(policy)
        altered['scriptHashes']=dict(policy['scriptHashes'])
        del altered['scriptHashes']['reference_sample.py']
        self.assertFalse(native_skill_jobs.policy_matches_skill(skill_jobs.SKILLS/'b2b-image-skill',altered))

    def test_review_rearms_import_trial_and_queues_native_visuals(self):
        api.command({'action':'product.approve','id':self.p['id'],'revision':1,'phase':'packaging','artifactJob':'package'})
        p=store.product(self.p['id']);jobs=store.records('jobs')
        self.assertEqual(p['selectionFlow']['status'],'ACTIVE')
        self.assertEqual(len(jobs),1);self.assertEqual(jobs[0]['kind'],'visual')
        self.assertEqual(jobs[0]['imageProvider'],'codex-native')
        self.assertFalse(any(j['kind']=='listing' for j in jobs))

    def test_explicit_stop_is_not_undone_by_repeated_review(self):
        p=store.product(self.p['id']);p['selectionFlow']['target']='VISUALS';store.save_product(p)
        api.command({'action':'product.approve','id':p['id'],'revision':1,'phase':'packaging','artifactJob':'package'})
        self.assertEqual(store.records('jobs'),[])
        self.assertEqual(store.product(p['id'])['selectionFlow']['status'],'STOPPED')

    def test_explicit_continue_requires_ack_and_current_approved_packaging(self):
        with self.assertRaises(ValueError):api.command({'action':'product.run','id':self.p['id'],'revision':1,'kind':'visual','acknowledgeExecution':True})
        p=store.product(self.p['id']);p['approvedPackaging']='package';store.save_product(p)
        with self.assertRaises(ValueError):api.command({'action':'product.run','id':p['id'],'revision':1,'kind':'visual'})
        with patch('skill_jobs.capability',return_value={'available':True}):
            j=api.command({'action':'product.run','id':p['id'],'revision':1,'kind':'visual','acknowledgeExecution':True})
            again=api.command({'action':'product.run','id':p['id'],'revision':1,'kind':'visual','acknowledgeExecution':True})
        self.assertEqual(j['id'],again['id']);self.assertEqual(j['imageProvider'],'codex-native')

    def test_native_cache_is_bound_to_actual_template_and_product_pixels(self):
        scene=self.root/'base.png';product=self.root/'product.png';image=self.root/'native.png'
        Image.new('RGB',(10,10),'blue').save(scene);Image.new('RGB',(10,10),'white').save(product)
        Image.new('RGB',(10,10),'purple').save(image)
        output=self.root/'_v2/m1_swapped.png'
        cmd=['python','gen_image.py','replace bottle','--scene',str(scene),'--product',str(product),'-o',str(output)]
        with self.assertRaisesRegex(ValueError,'等待GPT'):runner.native_swap(cmd,[],self.root)
        self.assertFalse(output.exists())
        runner.register(self.root/'native-requests/m1.json',image)
        runner.native_swap(cmd,[],self.root);self.assertEqual(runner.image_hash(output),runner.image_hash(image))
        Image.new('RGB',(10,10),'red').save(scene)
        with self.assertRaisesRegex(ValueError,'已变化'):runner.native_swap(cmd,[],self.root)

    def test_completed_modules_count_only_reusable_receipts_for_current_contract(self):
        import hashlib
        root=self.root/'receipt-check';(root/'template-receipts').mkdir(parents=True)
        build=root/'build';build.mkdir();output=root/'images';output.mkdir()
        spec=root/'product.json'
        modules={'m1':{},'m2':{},'m3':{},'m4':{},'m5':{},'m7':{}}
        spec.write_text(json.dumps({'nativeTemplateContract':{'templates':modules},'shared':'same'}),encoding='utf-8')
        binding={'job':'job-current','product':'product-current','revision':2,'attributePlanFingerprint':'fp-current'}

        def receipt(key, receipt_binding=None, mutate_html_hash=False, mutate_image_hash=False, slot=None):
            html=build/(key+'.html');html.write_text('template '+key,encoding='utf-8')
            image=output/(key+'.png');Image.new('RGB',(12,12),{'m1':'blue','m2':'green','m3':'yellow','m4':'purple','m5':'orange','m7':'red'}[key]).save(image)
            row={'slot':slot or key,'binding':receipt_binding or binding,'specHash':'old-spec-hash',
                'specDependencyHash':runner.spec_dependency_hash(spec,key),'renderer':'installed_render_v2','exitCode':0,
                'specCheck':'ok','html':'build/'+key+'.html','file':'images/'+key+'.png',
                'htmlHash':hashlib.sha256(html.read_bytes()).hexdigest(),
                'imagePixelHash':runner.image_hash(image)}
            if mutate_html_hash: row['htmlHash']='stale'
            if mutate_image_hash: row['imagePixelHash']='stale'
            (root/'template-receipts'/(key+'.json')).write_text(json.dumps(row),encoding='utf-8')

        receipt('m1')
        receipt('m2',receipt_binding={**binding,'job':'old-job'})
        receipt('m3',mutate_html_hash=True)
        receipt('m4',mutate_image_hash=True)
        receipt('m5',slot='m1')
        receipt('m7')
        self.assertEqual(runner.reusable_modules(root,binding,spec,build,output),['m1','m7'])

    def test_cache_rejects_an_external_output_file(self):
        outside=Path(self.temp.name).parent/'unregistered.png'
        with self.assertRaises(ValueError):runner.inside(self.root,'../unregistered.png')

    def test_concept_toolbar_previews_images_without_listing_facts(self):
        import recruitment_images
        p=store.product(self.p['id']);p['facts']['store']='youhealth';p['recruitment']={'store':'youhealth'}
        p['approvedPackaging']='package';store.save_product(p)
        result=recruitment_images.preview_products([{'id':p['id'],'revision':1}],'youhealth')
        self.assertEqual(result['target'],'VISUALS');self.assertEqual(result['eligible'],1)
        self.assertEqual(result['items'][0]['kind'],'visual')

    def test_partial_template_output_does_not_become_full_visual_success(self):
        import hashlib,re,shutil
        import skill_jobs,native_skill_jobs
        policy=native_skill_jobs.contract(skill_jobs.SKILLS)
        root=self.root/'runs'/'native';(root/'build').mkdir(parents=True);(root/'images').mkdir()
        template=skill_jobs.SKILLS/'b2b-image-skill/assets/templates/m1-brand-hero.html'
        html=root/'build/m1.html';html.write_text(re.sub(r'\{\{[A-Z0-9_]+\}\}','fixture',template.read_text(encoding='utf-8')),encoding='utf-8')
        shutil.copy2(template.parent/'_brand.css',html.parent/'_brand.css')
        (root/'product.json').write_text('{}')
        image=root/'images/m1.png';Image.new('RGB',(1000,1000),'blue').save(image)
        (root/'template-receipts').mkdir()
        row={'slot':'m1','exitCode':0,'renderer':'installed_render_v2','file':'images/m1.png','imagePixelHash':runner.image_hash(image),
             'html':'build/m1.html','htmlHash':hashlib.sha256(html.read_bytes()).hexdigest(),'spec':'product.json','specHash':hashlib.sha256((root/'product.json').read_bytes()).hexdigest(),'specCheck':'ok'}
        (root/'template-receipts/m1.json').write_text(json.dumps(row))
        job=store.enqueue('visual','product:'+self.p['id'],{'product':self.p['id'],'revision':1})
        binding={'job':job['id'],'product':self.p['id'],'revision':1,'attributePlanFingerprint':''}
        (root/'input.json').write_text(json.dumps(dict(self.p,executionBinding=binding)))
        row['binding']=binding
        (root/'template-receipts/m1.json').write_text(json.dumps(row))
        native_skill_jobs.save_partial(self.p,job,root,{'images':[{'slot':'m1','file':'images/m1.png'}],'reason':'其他模块待资料'},policy)
        p=store.product(self.p['id']);self.assertIsNone(p['visual']);self.assertEqual(len(p['visualPartial']['images']),1)
        self.assertIsNone(p.get('approvedVisual'));self.assertIsNone(p.get('draft'))
        html.write_text(html.read_text(encoding='utf-8').replace('background:var(--blue)','background:red'),encoding='utf-8')
        row['htmlHash']=hashlib.sha256(html.read_bytes()).hexdigest()
        (root/'template-receipts/m1.json').write_text(json.dumps(row))
        with self.assertRaisesRegex(ValueError,'模板结构'):
            native_skill_jobs.verify(root,[{'slot':'m1','file':'images/m1.png'}],policy)

    def test_generated_but_unchecked_images_are_pending_only(self):
        import native_skill_jobs
        root=self.root/'runs'/'pending';(root/'native-cache').mkdir(parents=True)
        (root/'native-requests').mkdir();(root/'build/v2').mkdir(parents=True)
        image=root/'native.png';Image.new('RGB',(1000,1000),'blue').save(image)
        row={'slot':'m1','scenePixelHash':'scene','productPixelHash':'product','subject':'replace bottle','image':'native.png','imagePixelHash':runner.image_hash(image)}
        (root/'native-cache/m1.json').write_text(json.dumps(row));(root/'native-requests/m1.json').write_text(json.dumps(row))
        Image.new('RGB',(1000,1000),'blue').save(root/'build/v2/m1_fit.png')
        job=store.enqueue('visual','product:'+self.p['id'],{'product':self.p['id'],'revision':1})
        binding={'job':job['id'],'product':self.p['id'],'revision':1,'attributePlanFingerprint':''}
        (root/'input.json').write_text(json.dumps(dict(self.p,executionBinding=binding)))
        row['binding']=binding
        (root/'native-cache/m1.json').write_text(json.dumps(row));(root/'native-requests/m1.json').write_text(json.dumps(row))
        # The fitted image is produced after cache registration in the real renderer.
        import os
        stamp=(root/'native-cache/m1.json').stat().st_mtime + 1
        os.utime(root/'build/v2/m1_fit.png',(stamp,stamp))
        native_skill_jobs.save_pending_images(self.p,job,root)
        p=store.product(self.p['id'])
        self.assertEqual(p['visualPending']['images'][0]['review'],'PENDING')
        self.assertIsNone(p['visual']);self.assertIsNone(p.get('approvedVisual'))

    def test_renderer_bridge_rejects_unknown_modules_without_spawning_commands(self):
        import native_skill_jobs,skill_jobs
        root=self.root/'runs'/'request';(root/'render-requests').mkdir(parents=True)
        (root/'render-requests/bad.json').write_text(json.dumps({'modules':['m1; arbitrary command'],'spec':'product.json','build':'build'}))
        job={'id':'request','product':self.p['id'],'revision':1}
        with patch.object(native_skill_jobs.subprocess,'run') as run:
            native_skill_jobs.process_render_requests(self.p,job,root,native_skill_jobs.contract(skill_jobs.SKILLS))
        run.assert_not_called()
        self.assertEqual(json.loads((root/'render-responses/bad.json').read_text(encoding='utf-8'))['status'],'REJECTED')

    def test_resume_reuses_only_this_tasks_context_and_requires_confirmation(self):
        p=store.product(self.p['id']);p['approvedPackaging']='package';store.save_product(p)
        job=store.enqueue('visual','product:'+p['id'],{'product':p['id'],'revision':1,'imageProvider':'codex-native'})
        store.job_update(job['id'],status='NEEDS_ATTENTION')
        root=self.root/'runs'/job['id'];root.mkdir(parents=True)
        (root/'executor.log').write_text(json.dumps({'type':'thread.started','thread_id':'019c6e27-e55b-73d1-87d8-4e01f1f75043'})+'\n')
        with self.assertRaises(ValueError):api.command({'action':'job.resume-native','id':job['id'],'revision':1})
        resumed=api.command({'action':'job.resume-native','id':job['id'],'revision':1,'acknowledgeExecution':True})
        self.assertEqual(resumed['id'],job['id']);self.assertEqual(resumed['status'],'QUEUED')
        self.assertEqual(len(store.records('jobs')),1)


if __name__=='__main__':unittest.main()
