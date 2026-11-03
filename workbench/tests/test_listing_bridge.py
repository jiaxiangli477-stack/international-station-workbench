import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import listing_bridge as bridge


class ListingBridgeTests(unittest.TestCase):
    def test_draft_submission_command_never_defaults_to_formal_publish(self):
        args=bridge.draft_command('fixture.json')
        self.assertEqual(args[args.index('--publish_type')+1],'draft')
        self.assertNotIn('product',args)

    def test_success_envelope_with_pending_dependency_is_not_uploaded_or_saved(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'run';calls=[]
            product={'id':'p','revision':5,'facts':{'store':'youhealth'},'attributePlan':{'manifest':{'fields':{'product_name':'Protein Powder'}}}}
            def export(_,where):
                file=where/'upload/main/m1.png';file.parent.mkdir(parents=True);file.write_bytes(b'fixture')
                return [{'slot':'m1','file':'upload/main/m1.png'}]
            def run(command,**kwargs):
                calls.append(command)
                if command[2]=='material-extract':
                    result=root/'material/result';result.mkdir()
                    (result/'image_list.json').write_text('["m1.png"]')
                    return json.dumps({'success':True,'imageCount':1})
                return json.dumps({'success':True,'ready':False,'status':'pending_dependency','missing':['image_list.json']})
            with patch('single_approval_flow.require_hero'),patch('single_approval_flow.visual_gaps',return_value=[]),patch('listing_adapter.export_images',side_effect=export),patch.object(bridge.weekly_update,'require_identity'):
                result=bridge.prepare(product,root,runner=run)
            self.assertEqual(result['status'],'PENDING_DEPENDENCY')
            self.assertFalse(result['materialUploaded']);self.assertFalse(result['draftSaved'])
            self.assertEqual(len(calls),2);self.assertTrue(all('publish-from-json' not in c and '--submit' not in c for c in calls))
            self.assertEqual(json.loads((root/'material/result/decoration_plan.json').read_text()),{'decorationPlan':'none'})
            self.assertNotIn('facts',result)

    def test_invalid_business_envelopes_stop_the_pipeline(self):
        for value in ('{}','[]','not json','{"success":false}'):
            with self.assertRaises(ValueError):bridge.read_result(value)

    def test_unavailable_cdn_stage_never_falls_back_to_browser_or_saves(self):
        with patch.object(bridge,'prepare',return_value={'materialUploaded':False,'message':'CDN pending'}):
            with self.assertRaisesRegex(ValueError,'未回退浏览器'):
                bridge.run({'id':'job'},{'id':'p'},Path('fixture'),None)


if __name__=='__main__':unittest.main()
