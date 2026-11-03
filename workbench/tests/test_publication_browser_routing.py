"""Only fresh verified product-manager evidence can drive original-Skill publication state."""
from datetime import datetime,timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import listing_adapter as adapter
import listing_browser as browser
import listing_browser_publication as publication

class PublicationBrowserRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.product={'id':'P','revision':1,'facts':{'store':'fixture'},'workflow':{'listingMechanism':'original-skill-v1'},
                      'draft':{'draft_id':'123','store':'fixture'}}
        self.observation={'identity':{'verified':True,'account_id':'account'},
            'source':{'url':'https://i.alibaba.com/prod/product_manage','kind':'product_manager_row','method':'GET'},
            'observed_at':datetime.now(timezone.utc).isoformat(),
            'row':{'item_id':'123','draft_id':'123','status_field':'商品状态','status_text':'草稿'}}
        self.parsed={'mapping_verified':True,'status':'draft','status_text':'草稿'}
        self.account=patch('weekly_update.STORES',{'fixture':{'expected_id':'account'}});self.account.start();self.addCleanup(self.account.stop)

    def test_original_skill_uses_real_manager_collector_and_rechecks_source(self):
        with patch.object(browser,'status',return_value={'status':'READY'}), \
             patch.object(publication,'collect',return_value=self.observation) as collect, \
             patch.object(publication,'verify_observation',return_value=self.parsed) as verify, \
             patch('listing_publication.collect',side_effect=AssertionError('unrelated bridge')):
            result=adapter.refresh_publication(self.product,self.root)
        self.assertEqual(result['status'],'draft');self.assertFalse(result['published'])
        self.assertEqual(result['authority']['source_kind'],'product_manager_row')
        self.assertEqual(result['authority']['method'],'GET')
        collect.assert_called_once();verify.assert_called_once()

    def test_unverified_manager_source_never_sets_published(self):
        self.observation['row']['status_text']='已上架'
        with patch.object(publication,'verify_observation',side_effect=ValueError('changed source')) as verify:
            result=adapter.read_publication_status(self.product,lambda _:self.observation,expected_account='account')
        verify.assert_called_once();self.assertEqual(result['status'],'unknown');self.assertIsNone(result['published'])

    def test_background_does_not_launch_closed_browser_but_explicit_recovery_can(self):
        with patch.object(browser,'status',return_value={'status':'DISCONNECTED'}), \
             patch.object(browser,'ensure_ready') as recover,patch.object(publication,'collect') as collect:
            result=adapter.refresh_publication(self.product,self.root)
        self.assertEqual(result['status'],'unknown');recover.assert_not_called();collect.assert_not_called()
        with patch.object(browser,'ensure_ready') as recover, \
             patch.object(publication,'collect',return_value=self.observation), \
             patch.object(publication,'verify_observation',return_value=self.parsed):
            result=adapter.refresh_publication(self.product,self.root,recover_browser=True)
        recover.assert_called_once_with(self.product);self.assertEqual(result['status'],'draft')

if __name__=='__main__':unittest.main()
