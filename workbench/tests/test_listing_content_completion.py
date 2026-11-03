import copy
import json
from pathlib import Path
import tempfile
import unittest
import task_store as store
import listing_adapter as adapter


class ListingContentCompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=(store.STATE,store.DB)
        store.STATE=Path(self.tmp.name);store.DB=store.STATE/'fixture.sqlite'
        self.product=store.create_product('fixture:completion','Protein Gummies',facts={'mode':'concept','store':'youhealth'})
        self.manifest={'fields':{'product_name':'Protein Gummies','dosage_form':'Gummy','protein_per_serving':'20-29g','benefits':'Immune & Anti-fatigue','shelf_life':'24months'}}
        self.product.update(attributePlan={'manifest':copy.deepcopy(self.manifest),'fingerprint':'base'},heroApproval={'pixelHash':'preserve'},visual={'job':'preserve'},draft={'draft_id':'123','revision':1,'store':'youhealth'})
        store.save_product(self.product)
        self.sources={f'fields.{key}':{'kind':'DESIGN','source':'Synthetic approved development input'} for key in self.manifest['fields']}

    def tearDown(self):
        store.STATE,store.DB=self.old;self.tmp.cleanup()

    def test_listing_only_content_does_not_invalidate_images_or_existing_draft(self):
        manifest=copy.deepcopy(self.manifest);manifest['fields']['brand']='LIFEWORTH'
        sources={**self.sources,'fields.brand':{'kind':'DESIGN','source':'Approved brand'}}
        result=adapter.save_listing_content(self.product,manifest,sources)
        for key in ('attributePlan','heroApproval','visual','draft','revision'):
            self.assertEqual(result[key],self.product[key])
        self.assertEqual(result['listingContent']['attributePlanFingerprint'],'base')

    def test_recruitment_parameters_cannot_be_changed_by_listing_completion(self):
        manifest=copy.deepcopy(self.manifest);manifest['fields']['dosage_form']='Powder'
        with self.assertRaisesRegex(ValueError,'征品参数'):
            adapter.save_listing_content(self.product,manifest,self.sources)
        self.assertNotIn('listingContent',store.product(self.product['id']))

    def test_missing_sources_and_stale_revision_are_rejected(self):
        with self.assertRaises(ValueError):adapter.save_listing_content(self.product,self.manifest,{})
        current=store.product(self.product['id']);current['revision']+=1;store.save_product(current)
        with self.assertRaisesRegex(ValueError,'产品资料已变化'):
            adapter.save_listing_content(self.product,self.manifest,self.sources)

    def test_wrong_store_draft_is_blocked_before_browser_or_prepare(self):
        p=copy.deepcopy(self.product);p['workflow']={'listingMechanism':'original-skill-v1'};p['draft']['store']='lifeworthcn'
        with self.assertRaisesRegex(ValueError,'同店铺'):
            adapter.complete_saved_draft(p,store.STATE/'never-created',Path('unused'))
        self.assertFalse((store.STATE/'never-created').exists())
