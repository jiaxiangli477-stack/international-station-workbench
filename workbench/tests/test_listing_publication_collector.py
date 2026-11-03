"""No gateway calls: recorded schema shape and injected read-only dependencies."""
import importlib.util
import json
from pathlib import Path
import unittest

BASE=Path(__file__).resolve().parents[2]
ROOT=BASE/'docs/single-approval/sandbox/publication-collector'

def load():
    spec=importlib.util.spec_from_file_location('publication_fixture',BASE/'workbench/listing_publication.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

class CollectorTests(unittest.TestCase):
    def schema(self):
        return {'success':True,'command':'workctl icbu product query-product-by-id',
            'params':[{'name':'productId','agent_flag':'--prod-id','type':'integer','required':True}]}
    def test_unknown_state_never_infers_published_and_all_calls_are_readonly(self):
        calls=[]; identities=[]
        def run(command,cwd,timeout,env):
            calls.append(command)
            self.assertTrue(str(env['WORKCTL_CONFIG_DIR']).startswith(str(ROOT)))
            self.assertEqual(env['TMP'],env['TEMP'])
            if command[1]=='schema': return json.dumps(self.schema())
            output=Path(command[command.index('--output')+1])
            output.write_text(json.dumps({'success':True,'data':{'productQueryResult':json.dumps({'productId':123,'status':999})}}),encoding='utf-8')
            return '{}'
        def identity(bridge,output,expected,env): identities.append(str(output))
        observation=load().collect({'store':'fixture','draft_id':'123','product_id':'123','expected_account':'account'},
            ROOT/'unknown',bridge=ROOT/'bridge',run=run,require_identity=identity)
        self.assertEqual(len(identities),2)
        self.assertEqual(calls[0][1:4],['schema','icbu.product.query-product-by-id','--format'])
        self.assertEqual(calls[1][1:4],['icbu','product','query-product-by-id'])
        self.assertNotIn('--yes',calls[1]); self.assertNotEqual(observation['row'].get('status'),'published')
        self.assertEqual(observation['source']['kind'],'workctl-tool')
    def test_schema_changes_or_account_failure_block_queries(self):
        for failure in ('schema','identity'):
            calls=[]
            def run(command,**kwargs):
                calls.append(command)
                schema=self.schema(); schema['params'][0]['agent_flag']='--unknown-flag'
                return json.dumps(schema)
            def identity(*args,**kwargs):
                if failure=='identity': raise ValueError('mismatch')
            with self.assertRaises(ValueError):
                load().collect({'store':'fixture','draft_id':'123','product_id':'123','expected_account':'account'},
                    ROOT/failure,bridge=ROOT/'bridge',run=run,require_identity=identity)
            self.assertTrue(all(command[1]=='schema' for command in calls))

if __name__=='__main__': unittest.main()
