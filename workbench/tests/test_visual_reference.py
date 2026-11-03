import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image

import native_skill_jobs
import skill_jobs
import task_store as store
import visual_reference


def samples():
    common = {'mode': 'sample', 'source': {'brand': 'Example', 'product': 'Protein',
        'variant': 'One flavor', 'url': 'https://example.com/product', 'accessed': '2026-10-25',
        'evidenceSection': 'Ingredient label'}, 'ingredients': ['Whey Protein Isolate', 'Natural Flavors', 'Malic Acid'],
        'evidenceText': 'Whey Protein Isolate, Natural Flavors, Malic Acid',
        'disclaimer': "Competitor reference only; not this product's formula."}
    return {key: dict(copy.deepcopy(common), modules={key: dict(zip(slots, common['ingredients']))})
        for key, slots in {'m2': ['ITEM_1', 'ITEM_2', 'ITEM_3'],
                           'd2': ['D2_ING1_NAME', 'D2_ING2_NAME', 'D2_ING3_NAME']}.items()}


def nutrition_facts():
    source = ('https://example.com/product; Nutrition Facts, One flavor column, ' 
        'accessed 2026-10-25. Competitor reference for sample display only. Row: Protein 22 g.')
    return {'mode': 'sample', 'facts_title': 'Nutrition Facts', 'facts_header_name': 'Nutrition Facts',
        'serving_size': '1 stick (28 g)', 'source_copy': False, 'other_ingredients': '',
        'rows': [{'name': 'Protein', 'amount': 22, 'unit': 'g', 'dv': '44%', 'source': source}]}


class ReferenceRenderTests(unittest.TestCase):
    def setUp(self):
        parent = store.ROOT / '.state' / 'test-runs'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.old = store.STATE, store.DB
        store.STATE = Path(self.temp.name)
        store.DB = store.STATE / 'test.sqlite'
        self.product = store.create_product('reference:test', 'Protein', facts={'mode': 'concept'})
        self.job = store.enqueue('visual', 'product:' + self.product['id'],
            {'product': self.product['id'], 'revision': 1, 'imageProvider': 'codex-native',
             'freshVisualContract': 'six-main-twelve-detail-reference-sample-v1', 'referenceSamples': samples()})
        self.root = store.STATE / 'runs' / self.job['id']
        (self.root / 'render-requests').mkdir(parents=True)
        (self.root / 'build').mkdir()
        self.policy = native_skill_jobs.contract(skill_jobs.SKILLS)
        self.binding = {'job': self.job['id'], 'product': self.product['id'], 'revision': 1,
                        'attributePlanFingerprint': ''}
        self.context = dict(self.product, executionBinding=self.binding,
            workflow={'freshVisualContract': self.job['freshVisualContract']}, referenceSamples=samples(),
            visualReferenceScope={'validatedSampleInput': 'local review'})
        (self.root / 'input.json').write_text(json.dumps(self.context), encoding='utf-8')

    def tearDown(self):
        store.STATE, store.DB = self.old
        self.temp.cleanup()

    def request(self, slot, sample=True, label=True):
        import runpy
        helper = runpy.run_path(str(Path(self.policy['skillRoot']) / 'scripts/reference_sample.py'))
        values = helper['reference_fields'](samples()[slot], slot)
        if not label:
            values['REFERENCE_LABEL'] = ''
        template = Path(self.policy['skillRoot']) / 'assets/templates' / self.policy['templates'][slot]['file']
        built = re.sub(r'\{\{([A-Z0-9_]+)\}\}', lambda m: values.get(m[1], 'fixture'), template.read_text(encoding='utf-8'))
        (self.root / 'build' / (slot + '.html')).write_text(built, encoding='utf-8')
        spec = {slot: {'sampleReference': samples()[slot]} if sample else {}}
        if slot == 'd2':
            (self.root / 'assets/reference-ingredients').mkdir(parents=True, exist_ok=True)
            refs = {}
            for i, key in enumerate(('d2_ing1', 'd2_ing2', 'd2_ing3'), 1):
                rel = 'assets/reference-ingredients/' + key + '.png'
                Image.new('RGBA', (4, 4), (i * 20, 10, 10, 255)).save(self.root / rel)
                refs[key] = {'job': 'source-job', 'file': key + '.png',
                             'sha256': hashlib.sha256((self.root / rel).read_bytes()).hexdigest()}
                spec[slot].setdefault('images', {})[key] = rel
            self.context['referenceAssets'] = refs
            self.context['referenceAssetFiles'] = {key: 'assets/reference-ingredients/' + key + '.png' for key in refs}
            (self.root / 'input.json').write_text(json.dumps(self.context), encoding='utf-8')
        (self.root / 'product.json').write_text(json.dumps(spec), encoding='utf-8')
        (self.root / 'render-requests/001.json').write_text(json.dumps(
            {'spec': 'product.json', 'build': 'build', 'modules': [slot]}), encoding='utf-8')

    def test_missing_module_reference_is_rejected_before_renderer(self):
        self.request('m2', sample=False)
        with patch.object(native_skill_jobs.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as renderer, \
             patch.object(native_skill_jobs, 'publish_receipts', return_value=[]):
            native_skill_jobs.process_render_requests(self.product, self.job, self.root, self.policy)
        self.assertFalse(renderer.called, 'invalid reference must not start the renderer')
        reply = json.loads((self.root / 'render-responses/001.json').read_text(encoding='utf-8'))
        self.assertEqual(reply['status'], 'REJECTED')
        self.assertIn('reference', reply['reason'].lower())

    def test_missing_visible_label_is_rejected_before_renderer(self):
        self.request('d2', label=False)
        with patch.object(native_skill_jobs.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as renderer, \
             patch.object(native_skill_jobs, 'publish_receipts', return_value=[]):
            native_skill_jobs.process_render_requests(self.product, self.job, self.root, self.policy)
        self.assertFalse(renderer.called, 'missing visible reference label must block rendering')

    def test_valid_reference_reaches_renderer(self):
        self.request('m2')
        with patch.object(native_skill_jobs.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as renderer, \
             patch.object(native_skill_jobs, 'publish_receipts', return_value=[]):
            renderer.return_value.returncode = 0
            native_skill_jobs.process_render_requests(self.product, self.job, self.root, self.policy)
        renderer.assert_called_once()

    def test_d2_without_source_bound_ingredient_images_is_rejected(self):
        self.request('d2')
        spec = json.loads((self.root / 'product.json').read_text(encoding='utf-8'))
        spec['d2']['images']['d2_ing2'] = 'assets/other.png'
        (self.root / 'product.json').write_text(json.dumps(spec), encoding='utf-8')
        with patch.object(native_skill_jobs.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as renderer, \
             patch.object(native_skill_jobs, 'publish_receipts', return_value=[]):
            native_skill_jobs.process_render_requests(self.product, self.job, self.root, self.policy)
        self.assertFalse(renderer.called, 'd2 must keep each source-bound ingredient image in its assigned slot')

    def test_changed_source_is_rejected_even_when_ingredient_text_matches(self):
        self.request('m2')
        path = self.root / 'product.json'
        spec = json.loads(path.read_text(encoding='utf-8'))
        spec['m2']['sampleReference']['source']['variant'] = 'Different flavor'
        path.write_text(json.dumps(spec), encoding='utf-8')
        with patch.object(native_skill_jobs.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as renderer, \
             patch.object(native_skill_jobs, 'publish_receipts', return_value=[]):
            native_skill_jobs.process_render_requests(self.product, self.job, self.root, self.policy)
        self.assertFalse(renderer.called, 'changed reference source must block rendering')

    def test_competitor_sample_never_coexists_with_formula_facts_in_spec(self):
        self.request('m2')
        spec_path = self.root / 'product.json'
        spec = json.loads(spec_path.read_text(encoding='utf-8'))
        spec['productFacts'] = {'formula': 'invented formula'}
        spec_path.write_text(json.dumps(spec), encoding='utf-8')
        with patch.object(native_skill_jobs.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as renderer, \
             patch.object(native_skill_jobs, 'publish_receipts', return_value=[]):
            native_skill_jobs.process_render_requests(self.product, self.job, self.root, self.policy)
        self.assertFalse(renderer.called, 'sample reference cannot be accepted as product facts')

    def test_existing_unlabelled_receipt_cannot_enter_partial_gallery(self):
        import native_template_runner
        self.request('m2', sample=False)
        (self.root / 'images').mkdir()
        (self.root / 'template-receipts').mkdir()
        image = self.root / 'images/m2.png'
        Image.new('RGB', (1000, 1000), 'blue').save(image)
        html = self.root / 'build/m2.html'
        spec = self.root / 'product.json'
        shutil.copy2(Path(self.policy['skillRoot']) / 'assets/templates/_brand.css', self.root / 'build/_brand.css')
        row = {'slot': 'm2', 'exitCode': 0, 'renderer': 'installed_render_v2', 'file': 'images/m2.png',
            'imagePixelHash': native_template_runner.image_hash(image), 'binding': self.binding, 'specCheck': 'ok',
            'html': 'build/m2.html', 'htmlHash': hashlib.sha256(html.read_bytes()).hexdigest(),
            'spec': 'product.json', 'specHash': hashlib.sha256(spec.read_bytes()).hexdigest()}
        (self.root / 'template-receipts/m2.json').write_text(json.dumps(row), encoding='utf-8')
        self.assertEqual(native_skill_jobs.publish_receipts(self.product, self.job, self.root, self.policy), [])
        self.assertFalse(store.product(self.product['id']).get('visualPartial'))

    def source_specs(self, root):
        context = dict(self.context)
        context.pop('referenceSamples')
        context['executionBinding'] = dict(self.binding, job=root.name)
        (root / 'input.json').write_text(json.dumps(context), encoding='utf-8')
        (root / 'product-concept.json').write_text(json.dumps({'m2': {'sampleReference': samples()['m2']},
            'm7': {'facts': nutrition_facts()}}), encoding='utf-8')
        images = {}
        for key in ('d2_ing1', 'd2_ing2', 'd2_ing3'):
            path = root / (key + '.png')
            Image.new('RGBA', (4, 4), 'white').save(path)
            images[key] = path.name
        (root / 'detail-concept.json').write_text(json.dumps(
            {'d2': {'sampleReference': samples()['d2'], 'images': images}}), encoding='utf-8')

    def test_old_specs_and_ingredient_assets_reach_new_input(self):
        self.source_specs(self.root)
        (self.root / 'blocked-modules.json').write_text(json.dumps({'m2': 'old ingredient gap', 'm6': 'old NSF sample missing',
            'd1': 'certificate and commercial claims lack evidence'}), encoding='utf-8')
        payload = visual_reference.migrate(self.product, self.job, self.root, self.policy)
        target = store.STATE / 'runs/repaired'
        target.mkdir()
        context = visual_reference.prepare(dict(self.job, **payload), self.product, target, self.policy)
        self.assertEqual(context['referenceSamples'], samples())
        self.assertEqual(len(context['referenceAssetFiles']), 3)
        for key, name in context['referenceAssetFiles'].items():
            self.assertEqual((target / name).read_bytes(), (self.root / (key + '.png')).read_bytes())
        self.assertEqual(self.policy['referenceSamplesHash'], visual_reference.digest(samples()))
        self.assertEqual(context.get('visualBlockers'), {'d1': 'certificate and commercial claims lack evidence'})
        self.assertEqual(context.get('referenceNutrition', {}).get('facts'), nutrition_facts())

    def test_m6_is_blocked_when_selected_nutrition_reference_was_not_carried(self):
        import visual_reference
        (self.root / 'product.json').write_text(json.dumps({'m7': {'facts': nutrition_facts()}}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'nutrition reference'):
            visual_reference.require_render(self.context, self.policy, self.root / 'product.json',
                self.root / 'build/m6.html', 'm6')

    def test_sample_nutrition_cannot_bypass_gate_without_scope_flag(self):
        import visual_reference
        context = dict(self.product, executionBinding=self.binding,
            workflow={'freshVisualContract': self.job['freshVisualContract']}, referenceSamples=samples())
        spec = {'m7': {'facts': nutrition_facts()}}
        (self.root / 'product.json').write_text(json.dumps(spec), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'nutrition reference'):
            visual_reference.require_render(context, self.policy, self.root / 'product.json',
                self.root / 'build/m6.html', 'm6')

    def test_m6_requires_the_bound_sample_facts_and_both_fixed_disclaimers(self):
        import ast
        import visual_reference
        facts = nutrition_facts()
        reference = {'source': samples()['m2']['source'], 'facts': facts}
        context = dict(self.context, referenceNutrition=reference)
        self.policy['referenceNutritionHash'] = visual_reference.digest(reference)
        spec = {'m7': {'facts': facts}}
        (self.root / 'product.json').write_text(json.dumps(spec), encoding='utf-8')
        build_script = Path(self.policy['skillRoot']) / 'scripts/build.py'
        tree = ast.parse(build_script.read_text(encoding='utf-8'))
        labels = {target.id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
            and isinstance(node.value, (ast.Constant, ast.BinOp, ast.JoinedStr))
            for target in node.targets if isinstance(target, ast.Name) and target.id in {'_DISC_TOP', '_DISC_BOTTOM'}}
        template = Path(self.policy['skillRoot']) / 'assets/templates/m6-process-facts-stacked.html'
        html = template.read_text(encoding='utf-8').replace('{{DISCLAIMER_TOP}}', labels['_DISC_TOP'])
        html = html.replace('{{DISCLAIMER_BOTTOM}}', labels['_DISC_BOTTOM'].replace('Supplement Facts', 'Nutrition Facts'))
        (self.root / 'build/m6.html').write_text(html, encoding='utf-8')
        visual_reference.require_render(context, self.policy, self.root / 'product.json',
            self.root / 'build/m6.html', 'm6')
        spec['m7']['facts'] = dict(facts, mode='real')
        (self.root / 'product.json').write_text(json.dumps(spec), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'm6 must use'):
            visual_reference.require_render(context, self.policy, self.root / 'product.json',
                self.root / 'build/m6.html', 'm6')

    def test_known_unresolved_company_claims_cannot_be_rendered(self):
        context = dict(self.context, visualBlockers={'d1': 'unverified certificate'})
        (self.root / 'input.json').write_text(json.dumps(context), encoding='utf-8')
        (self.root / 'product.json').write_text(json.dumps({'d1': {}}), encoding='utf-8')
        template = Path(self.policy['skillRoot']) / 'assets/templates' / self.policy['templates']['d1']['file']
        built = re.sub(r'\{\{([A-Z0-9_]+)\}\}', 'fixture', template.read_text(encoding='utf-8'))
        (self.root / 'build/d1.html').write_text(built, encoding='utf-8')
        (self.root / 'render-requests/001.json').write_text(json.dumps(
            {'spec': 'product.json', 'build': 'build', 'modules': ['d1']}), encoding='utf-8')
        with patch.object(native_skill_jobs.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as renderer, \
             patch.object(native_skill_jobs, 'publish_receipts', return_value=[]):
            native_skill_jobs.process_render_requests(self.product, self.job, self.root, self.policy)
        self.assertFalse(renderer.called, 'known unresolved facts must block the renderer')

    def test_missing_current_payload_recovers_only_bound_same_revision_history(self):
        prior = store.STATE / 'runs/prior'
        prior.mkdir()
        self.source_specs(prior)
        (self.root / 'input.json').write_text(json.dumps(dict(self.context, referenceSamples=None)), encoding='utf-8')
        product = dict(self.product, visualHistory=[{'job': 'prior', 'revision': 1}])
        payload = visual_reference.migrate(product, self.job, self.root, self.policy)
        self.assertEqual(payload['referenceSamples'], samples())
        self.assertEqual({value['job'] for value in payload['referenceAssets'].values()}, {'prior'})
        invalid = json.loads((prior / 'input.json').read_text(encoding='utf-8'))
        invalid['executionBinding']['product'] = 'other-product'
        (prior / 'input.json').write_text(json.dumps(invalid), encoding='utf-8')
        with self.assertRaises(ValueError):
            visual_reference.migrate(product, self.job, self.root, self.policy)

    def test_nutrition_is_recovered_when_module_samples_were_already_copied(self):
        self.source_specs(self.root)
        context = json.loads((self.root / 'input.json').read_text(encoding='utf-8'))
        context['referenceSamples'] = samples()
        (self.root / 'input.json').write_text(json.dumps(context), encoding='utf-8')
        payload = visual_reference.migrate(self.product, self.job, self.root, self.policy)
        self.assertEqual(payload['referenceNutrition']['facts'], nutrition_facts())

    def test_changed_ingredient_asset_blocks_preparation(self):
        self.source_specs(self.root)
        payload = visual_reference.migrate(self.product, self.job, self.root, self.policy)
        (self.root / 'd2_ing1.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'image changed'):
            visual_reference.prepare(dict(self.job, **payload), self.product, self.root / 'new', self.policy)


if __name__ == '__main__':
    unittest.main()
