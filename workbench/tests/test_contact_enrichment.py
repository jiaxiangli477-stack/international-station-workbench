import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from contact_enrichment import enrich


class ContactEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.folder=Path(self.tmp.name)
        self.data={'store':{'aliId':'321'},'window':{'since':'2026-10-09T00:00:00','until':'2026-10-15T23:59:59'},'conversations':[]}
        self.path=self.folder/'conversations.json'
        self.path.write_text(json.dumps(self.data),encoding='utf-8')
        self.original=self.path.read_bytes()
        self.module=SimpleNamespace(resolve_identity=Mock(return_value=({'CURRENT_SELF_ALIID':'321'},[{'aliId':'321'}])),
                                    call_tool=Mock(return_value={'success':True}))
        def main():
            current,_=self.module.resolve_identity()
            self.module.call_tool('query_conversation_info',{'selfAliId':321})
            self.path.write_text(json.dumps(dict(self.data,conversations=[{'crm':{'contactEmail':'test@example.com'}}])),encoding='utf-8')
            (self.folder/'contacts.json').write_text(json.dumps({'store':current,'window':{'start':'2026-10-09','end':'2026-10-15'},'contacts':{'test':{'email':'test@example.com'}}}),encoding='utf-8')
            return 0
        self.module.main=main

    def tearDown(self):
        self.tmp.cleanup()

    def run_enrichment(self):
        return enrich(self.module,self.folder,'321','2026-10-09','2026-10-15')

    def test_correct_store_result_can_update_contacts(self):
        self.assertEqual(self.run_enrichment()['withEmail'],1)
        self.assertNotEqual(self.path.read_bytes(),self.original)

    def test_different_logged_in_store_cannot_query_or_mutate(self):
        self.module.resolve_identity.return_value=({'CURRENT_SELF_ALIID':'999'},[{'aliId':'999'}])
        with self.assertRaises(ValueError):self.run_enrichment()
        self.module.call_tool.assert_not_called()
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_partial_platform_failure_rolls_back_both_files(self):
        old_contacts=b'{"previous":true}'
        (self.folder/'contacts.json').write_bytes(old_contacts)
        self.module.call_tool.return_value={'success':False}
        with self.assertRaises(ValueError):self.run_enrichment()
        self.assertEqual(self.path.read_bytes(),self.original)
        self.assertEqual((self.folder/'contacts.json').read_bytes(),old_contacts)

    def test_wrong_output_identity_is_rolled_back(self):
        original_main=self.module.main
        def invalid():
            original_main()
            (self.folder/'contacts.json').write_text('{}')
            return 0
        self.module.main=invalid
        with self.assertRaises(ValueError):self.run_enrichment()
        self.assertEqual(self.path.read_bytes(),self.original)
        self.assertFalse((self.folder/'contacts.json').exists())

    def test_old_period_cannot_be_silently_narrowed_by_upstream(self):
        with self.assertRaises(ValueError):enrich(self.module,self.folder,'321','2026-10-08','2026-10-15')
        self.module.resolve_identity.assert_not_called()


if __name__=='__main__':unittest.main()
