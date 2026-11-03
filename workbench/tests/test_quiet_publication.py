"""Background publication checks must never open browser tabs or console windows."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock,patch
import listing_publication as polling
import listing_browser_publication as browser

class QuietPublicationTests(unittest.TestCase):
    def test_background_skips_browser_based_products_and_keeps_noninteractive_reads(self):
        original={'id':'original','facts':{'store':'fixture'},'draft':{'draft_id':'123','store':'fixture'},
                  'workflow':{'listingMechanism':'original-skill-v1'}}
        legacy=dict(original,id='legacy',workflow={'listingMechanism':'legacy'})
        refresh=Mock()
        with patch('weekly_update.STORES',{'fixture':{'expected_id':'fixture-account'}}):
            result=polling.poll_once(products=[original,legacy],refresh=refresh)
        self.assertEqual(result,{'refreshed':1,'failed':0,'skipped':1})
        refresh.assert_called_once_with({'action':'publication.refresh','id':'legacy'})

    def test_explicit_browser_reader_hides_its_node_console_and_cannot_wait_on_stdin(self):
        run=Mock(side_effect=OSError('offline fixture'))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                browser.collect({'store':'fixture','product_id':'123','draft_id':'123',
                                 'expected_account':'fixture-account'},Path(directory),run=run)
        run.assert_called_once()
        options=run.call_args.kwargs
        self.assertEqual(options.get('creationflags'),getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(options.get('stdin'),subprocess.DEVNULL)

if __name__=='__main__':unittest.main()
