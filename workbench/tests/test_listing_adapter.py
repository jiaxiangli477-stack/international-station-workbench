import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
import task_store as store
import listing_adapter as adapter


class ListingAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = store.STATE, store.DB
        store.STATE = Path(self.tmp.name)
        store.DB = store.STATE / 'records.sqlite'

    def tearDown(self):
        store.STATE, store.DB = self.old
        self.tmp.cleanup()

    def test_export_keeps_19_outputs_and_routes_m7_to_parameters_without_mutating_sources(self):
        root = store.STATE / 'runs' / 'visual'
        root.mkdir(parents=True)
        slots = [f'm{i}' for i in range(1, 8)] + ['d1','d2','d3','d4','df','d5','d6','dfac','d7','dc','drev','d9']
        for key in slots:
            Image.new('RGB', (1000, 1000) if key.startswith('m') else (750, 200), 'white').save(root / (key + '.png'))
        p = {'visual': {'job': 'visual', 'images': [{'slot': k, 'file': k + '.png'} for k in slots]}}
        rows = adapter.export_images(p, store.STATE / 'runs' / 'listing')
        self.assertEqual(len(rows), 19)
        self.assertEqual(sum(row['section'] == 'main' for row in rows), 6)
        m7 = next(row for row in rows if row['slot'] == 'm7')
        self.assertEqual(m7['section'], 'parameters')
        self.assertTrue((root / 'm7.png').is_file())
        self.assertTrue(all(row['sourceHash'] == row['exportHash'] for row in rows))

    def test_latest_six_main_image_set_keeps_m6_in_main_and_exports_18_items(self):
        root = store.STATE / 'runs' / 'visual'
        root.mkdir(parents=True)
        slots = [f'm{i}' for i in range(1, 7)] + ['d1','d2','d3','d4','df','d5','d6','dfac','d7','dc','drev','d9']
        for key in slots:
            Image.new('RGB', (1000, 1000) if key.startswith('m') else (750, 200), 'white').save(root / (key + '.png'))
        p = {'visual': {'job': 'visual', 'revision': 1, 'images': [{'slot': k, 'file': k + '.png'} for k in slots]}}
        rows = adapter.export_images(p, store.STATE / 'runs' / 'listing')
        self.assertEqual(len(rows), 18)
        self.assertEqual([row['slot'] for row in rows if row['section'] == 'main'], [f'm{i}' for i in range(1, 7)])
        self.assertNotIn('parameters', {row['section'] for row in rows})

    def test_export_rejects_duplicate_slots_instead_of_silently_discarding_them(self):
        rows = [{'slot': slot, 'file': slot + '.png'} for slot in adapter.SLOTS]
        rows.append({'slot': 'm1', 'file': 'unreviewed-replacement.png'})
        source = store.STATE / 'runs' / 'visual'
        source.mkdir(parents=True)
        for row in rows:
            Image.new('RGB', (1000, 1000), 'white').save(source / row['file'])
        with self.assertRaisesRegex(ValueError, '重复'):
            adapter.export_images({'visual': {'job': 'visual', 'images': rows}},
                                  store.STATE / 'runs' / 'listing')

    def receipt(self):
        images, positions = [], {}
        for slot in adapter.SLOTS:
            section = 'parameters' if slot == 'm7' else 'main' if slot.startswith('m') else 'detail'
            index = positions.get(section, 0)
            positions[section] = index + 1
            images.append({'slot': slot, 'actual': 'https://example.test/' + slot, 'matched': True,
                           'evidenceVersion': 1, 'assetId': 'fixture-' + slot, 'expectedAssetId': 'fixture-' + slot,
                           'section': section, 'index': index, 'uploaded': True, 'exportHash': 'fixture-hash'})
        return {'draft_id': '123456', 'draft_url': 'https://post.alibaba.com/product/publish.htm?itemId=123456',
                'store': 'youhealth', 'published': False, 'actualAccountVerified': True,
                'category_id': '202029902', 'fields': {'product_name': {'actual': 'New Powder', 'matched': True}},
                'image_checks': images}

    def report(self):
        return {'status': 'completed', 'category_routing': {'selected_cat_id': '202029902'},
                'post_save_verification': {'status': 'verified', 'missing_required': [], 'structure_mismatches': []}}

    def test_original_skill_draft_records_manual_image_review_without_claiming_asset_readback(self):
        report=self.report();report['images']={'main_count':6,'detail_count':12}
        receipt=self.receipt();receipt.update(acceptancePolicy='original-skill-draft-review',image_review_required=True,image_readback_verified=False)
        delivery=[{'slot':row['slot'],'section':row['section'],'exportHash':'hash'} for row in receipt['image_checks']]
        receipt['image_checks']=[dict(row,matched=False,uploadInvoked=True,reviewRequired=True,exportHash='hash') for row in receipt['image_checks']]
        self.assertTrue(adapter.validate_receipt(report,receipt,'youhealth','202029902',delivery))
        receipt['image_checks'][0]['uploadInvoked']=False
        with self.assertRaises(ValueError):adapter.validate_receipt(report,receipt,'youhealth','202029902',delivery)

    def test_original_skill_policy_never_skips_actual_field_or_image_step_failure(self):
        report=self.report();report['images']={'main_count':6,'detail_count':12,'skipped':True}
        receipt=self.receipt();receipt.update(acceptancePolicy='original-skill-draft-review',image_review_required=True,image_readback_verified=False)
        delivery=[{'slot':row['slot'],'section':row['section'],'exportHash':'hash'} for row in receipt['image_checks']]
        receipt['image_checks']=[dict(row,matched=False,uploadInvoked=True,reviewRequired=True,exportHash='hash') for row in receipt['image_checks']]
        with self.assertRaises(ValueError):adapter.validate_receipt(report,receipt,'youhealth','202029902',delivery)
        report['images'].pop('skipped');receipt['fields']['product_name']['matched']=False
        with self.assertRaises(ValueError):adapter.validate_receipt(report,receipt,'youhealth','202029902',delivery)

    def test_verified_report_alone_cannot_hide_missing_actual_image_checks(self):
        readback = self.receipt()
        readback['image_checks'].pop()
        with self.assertRaises(ValueError):
            adapter.validate_receipt(self.report(), readback, 'youhealth', '202029902')

    def test_actual_category_identity_and_field_failures_block_success(self):
        for key, value in [('category_id', 'wrong'), ('actualAccountVerified', False), ('store', 'other')]:
            r = self.receipt(); r[key] = value
            with self.assertRaises(ValueError):
                adapter.validate_receipt(self.report(), r, 'youhealth', '202029902')
        r = self.receipt(); r['fields']['product_name']['matched'] = False
        with self.assertRaises(ValueError):
            adapter.validate_receipt(self.report(), r, 'youhealth', '202029902')

    def test_only_complete_real_readback_receipt_is_accepted(self):
        self.assertTrue(adapter.validate_receipt(self.report(), self.receipt(), 'youhealth', '202029902'))

    def test_execution_lock_prevents_second_writer(self):
        with adapter.session_lock('one'):
            with self.assertRaises(ValueError):
                with adapter.session_lock('two'):
                    pass

    def test_listing_job_uses_fixed_entry_and_strict_receipt_without_a_model_runner(self):
        import skill_jobs
        p=store.create_product('fixture:listing','New Powder',facts={'mode':'concept','store':'youhealth'})
        root=store.STATE/'runs/visual';root.mkdir(parents=True)
        for key in adapter.SLOTS:Image.new('RGB',(1000,1000) if key.startswith('m') else (750,200),'white').save(root/(key+'.png'))
        p.update(visual={'job':'visual','revision':1,'images':[{'slot':key,'file':key+'.png'} for key in adapter.SLOTS]},approvedVisual='visual',
                 attributePlan={'job':'attributes','revision':1,'fingerprint':'reviewed','unresolved':[],
                    'manifest':{'fields':{'product_name':'New Powder'}},'skillContract':adapter.skill_contract(skill_jobs.skill_root('alibaba-attribute-filler').parent)},
                 approvedAttributes='reviewed')
        import attribute_plan
        p['attributePlan']['fingerprint'] = attribute_plan.fingerprint(p['attributePlan'])
        p['approvedAttributes'] = p['attributePlan']['fingerprint']
        p['visual']['attributePlanFingerprint'] = p['attributePlan']['fingerprint']
        store.save_product(p)
        job=store.enqueue('listing','product:'+p['id'],{'product':p['id'],'revision':1})
        output=store.STATE/'runs'/job['id'];calls=[]
        def original_entry(args,**kwargs):
            calls.append(args)
            self.assertTrue(args[1].endswith('listing_runner.cjs'))
            if args[2]=='preflight':(output/'listing-preflight.json').write_text(json.dumps({'category':'202029902','blockers':[]}),encoding='utf-8')
            else:
                (output/'reports').mkdir()
                (output/'reports/run-all-report.json').write_text(json.dumps(self.report()),encoding='utf-8')
                receipt = self.receipt()
                delivery = json.loads((output/'upload-map.json').read_text(encoding='utf-8'))
                for row in receipt['image_checks']:
                    row['exportHash'] = next(item['exportHash'] for item in delivery if item['slot'] == row['slot'])
                (output/'readback.json').write_text(json.dumps(receipt),encoding='utf-8')
            return SimpleNamespace(returncode=0)
        with patch('bridge_catalog.current_bridge',return_value='fixture'),patch('weekly_update.require_identity'),patch.object(adapter.subprocess,'run',side_effect=original_entry),patch.object(skill_jobs.subprocess,'Popen',side_effect=AssertionError('model runner forbidden')):
            skill_jobs.run(job)
        self.assertEqual([call[2] for call in calls],['preflight','execute'])
        self.assertTrue(store.product(p['id'])['draft']['readback_verified'])


if __name__ == '__main__':
    unittest.main()
