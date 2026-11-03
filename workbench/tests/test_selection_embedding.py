import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import selection_readonly as view
import selection_service as service
import selection_jobs


class SelectionEmbeddingTests(unittest.TestCase):
    def test_same_origin_owner_keeps_original_owner_permissions(self):
        data={'sharing':{'role':'owner','permissions':{'research':True,'settings':True}},
              'candidates':[{'id':'reference'}], 'secret':'never-forward'}
        with patch.object(view,'fetch',return_value=(json.dumps(data).encode(),'application/json')):
            raw,_=view.resource('/selection-app/api/bootstrap',role='owner')
        result=json.loads(raw)
        self.assertEqual(result['sharing']['role'],'owner')
        self.assertTrue(result['sharing']['permissions']['research'])
        self.assertNotIn(b'never-forward',raw)

    def test_viewers_still_cannot_access_owner_settings(self):
        with patch.object(view,'fetch') as fetch:
            with self.assertRaises(ValueError):view.resource('/selection-app/api/ai-engine',role='viewer')
            fetch.assert_not_called()

    def test_owner_can_read_original_engine_status_without_changing_it(self):
        with patch.object(view,'fetch',return_value=(b'{"ready":true}','application/json')) as fetch:
            raw,_=view.resource('/selection-app/api/ai-engine',role='owner')
        self.assertEqual(json.loads(raw),{'ready':True});fetch.assert_called_once_with('/api/ai-engine')

    def test_candidates_use_managed_bootstrap_instead_of_dead_8788(self):
        with patch.object(service,'bootstrap',return_value={'candidates':[{'id':'c'}]}) as load:
            self.assertEqual(selection_jobs.source(),[{'id':'c'}])
        load.assert_called_once()

    def test_only_explicit_original_business_post_routes_are_accepted(self):
        self.assertTrue(service.write_allowed('/api/selection'))
        self.assertTrue(service.write_allowed('/api/candidates/0123456789abcdef-1'))
        for value in ('/api/session','/api/sharing/code','/api/delete-all','https://evil.test/api/selection','/../api/selection'):
            self.assertFalse(service.write_allowed(value))

    def test_headers_never_forward_browser_credentials_or_origin(self):
        with patch.object(service,'endpoint',return_value='http://127.0.0.1:12345'),patch.object(service,'urlopen') as opened:
            opened.return_value.__enter__.return_value.status=200
            opened.return_value.__enter__.return_value.read.return_value=b'{}'
            opened.return_value.__enter__.return_value.headers={'Content-Type':'application/json'}
            service.request('/api/selection',method='POST',body=b'{}')
        headers={k.lower():v for k,v in opened.call_args.args[0].header_items()}
        self.assertEqual(headers['x-workbench'],'1')
        self.assertNotIn('cookie',headers);self.assertNotIn('origin',headers);self.assertNotIn('authorization',headers)


if __name__=='__main__':unittest.main()
