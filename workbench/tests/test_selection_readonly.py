import json
import unittest
from unittest.mock import patch
import selection_readonly as view


class ReadonlySelectionTests(unittest.TestCase):
 def test_original_shell_and_assets_are_namespaced(self):
  with patch.object(view,'fetch',return_value=(b'<script src="/assets/main.js"></script>','text/html')):
   body,_=view.resource('/selection-app/')
  self.assertIn(b'/selection-app/assets/main.js',body)
  with patch.object(view,'fetch',return_value=(b'fetch("/api/bootstrap");fetch("/api/datasets")','text/javascript')):
   body,_=view.resource('/selection-app/assets/main.js')
  self.assertIn(b'/selection-app/api/bootstrap',body)
 def test_owner_permissions_and_secrets_are_not_forwarded(self):
  source={'sharing':{'role':'owner','permissions':{'research':True}},'candidates':[{'title':'Visible'}],
          'ai_engine':{'model':'Visible model','apiKey':'never-forward','accessToken':'never-forward','password':'never-forward'}}
  with patch.object(view,'fetch',return_value=(json.dumps(source).encode(),'application/json')):
   body,_=view.resource('/selection-app/api/bootstrap')
  data=json.loads(body)
  self.assertEqual(data['sharing']['role'],'viewer');self.assertFalse(data['sharing']['permissions']['research'])
  self.assertNotIn(b'never-forward',body);self.assertEqual(data['candidates'][0]['title'],'Visible')
 def test_only_named_get_routes_and_safe_queries_are_forwarded(self):
  for path in ['/selection-app/api/ai-engine','/selection-app/api/session','/selection-app/../secret','/selection-app/assets/%2e%2e.py','/selection-app/api/bootstrap?run_id=../../private']:
   with patch.object(view,'fetch') as upstream:
    with self.assertRaises(ValueError):view.resource(path)
    upstream.assert_not_called()

if __name__=='__main__':unittest.main()
