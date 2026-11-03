"""Offline reference handoff; isolated D-drive files/SQLite, no service or model."""
import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
import attribute_plan
import native_skill_jobs
import skill_jobs
import task_store as store
import visual_reference as reference


class ReferenceSubmissionTests(unittest.TestCase):
    def setUp(self):
        sandbox = Path(__file__).resolve().parents[2] / 'docs/visual-reference-submission-tests'
        sandbox.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=sandbox)
        self.state = Path(self.temporary.name)
        self.paths = patch.multiple(store, STATE=self.state, DB=self.state / 'fixture.sqlite')
        self.paths.start()
        self.product = store.create_product('reference:fixture', 'Synthetic gummy', facts={'mode': 'concept'})
        plan = {'revision': 1, 'manifest': {'fields': {'product_name': 'Synthetic gummy'}},
                'field_sources': {}, 'unresolved': []}
        plan['fingerprint'] = attribute_plan.fingerprint(plan)
        self.product.update(attributePlan=plan, heroApproval={'signature': 'unchanged'},
            workflow={'freshVisualContract': 'six-main-twelve-detail-reference-sample-v1', 'status': 'ACTIVE'})
        store.save_product(self.product)
        self.job = store.enqueue('visual', 'product:' + self.product['id'], {
            'product': self.product['id'], 'revision': 1, 'imageProvider': 'codex-native'})
        self.job = store.job_update(self.job['id'], status='RUNNING')
        self.root = self.state / 'runs' / self.job['id']
        self.root.mkdir(parents=True)
        self.policy = native_skill_jobs.contract(skill_jobs.SKILLS)
        self.binding = {'job': self.job['id'], 'product': self.product['id'], 'revision': 1,
                        'attributePlanFingerprint': plan['fingerprint']}
        self.context = dict(copy.deepcopy(self.product), executionBinding=self.binding,
                            nativeTemplateContract=self.policy)
        self.write('input.json', self.context)
        (self.root / 'images').mkdir()
        Image.new('RGBA', (1000, 1000), (20, 30, 40, 255)).save(self.root / 'images/m1.png')
        self.hero_bytes = (self.root / 'images/m1.png').read_bytes()
        common = {'mode': 'sample', 'source': {'brand': 'Synthetic fixture', 'product': 'Protein gummy',
            'variant': 'One flavor', 'url': 'https://example.test/gummy', 'accessed': '2026-10-30',
            'evidenceSection': 'Ingredient label'}, 'ingredients': ['Gelatin', 'Water', 'Fruit Powder'],
            'evidenceText': 'Gelatin, Water, Fruit Powder',
            'disclaimer': "Competitor reference only; not this product's formula."}
        samples = {slot: dict(copy.deepcopy(common), modules={slot: dict(zip(keys, common['ingredients']))})
                   for slot, keys in {'m2': ['ITEM_1', 'ITEM_2', 'ITEM_3'],
                                     'd2': ['D2_ING1_NAME', 'D2_ING2_NAME', 'D2_ING3_NAME']}.items()}
        nutrition = {'source': common['source'], 'facts': {'mode': 'sample', 'facts_title': 'Nutrition Facts',
            'facts_header_name': 'Nutrition Facts', 'serving_size': '4 gummies (30 g)', 'source_copy': False,
            'other_ingredients': '', 'rows': [{'name': 'Protein', 'amount': 22, 'unit': 'g', 'dv': '44%',
                'source': 'https://example.test/gummy; One flavor; Competitor reference; Protein 22 g label row.'}]}}
        assets = {}
        (self.root / 'reference-sources').mkdir()
        for index in range(1, 4):
            key = 'd2_ing' + str(index)
            relative = 'reference-sources/' + key + '.png'
            Image.new('RGBA', (12, 12), (index * 20, 10, 30, 255)).save(self.root / relative)
            assets[key] = {'job': self.job['id'], 'file': relative,
                           'sha256': hashlib.sha256((self.root / relative).read_bytes()).hexdigest()}
        self.submission = {'executionBinding': self.binding, 'referenceSamples': samples,
                           'referenceNutrition': nutrition, 'referenceAssets': assets}

    def tearDown(self):
        self.paths.stop()
        self.temporary.cleanup()

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def submit(self):
        self.write('reference-submission.json', self.submission)
        return reference.accept_submission(self.product, self.job, self.root, self.context)

    def assert_protected(self):
        self.assertEqual(store.product(self.product['id']), self.product)
        self.assertEqual((self.root / 'images/m1.png').read_bytes(), self.hero_bytes)

    def test_workflow_only_reference_contract_starts_collection_but_still_blocks_reference_rendering(self):
        result = reference.prepare(self.job, self.product, self.root, self.policy)
        self.assertEqual(result['referenceAcquisition']['status'], 'REQUIRED')
        self.assertTrue(self.policy['referenceRequired'])
        self.context.update(result)
        with self.assertRaises(ValueError):
            reference.require_render(self.context, self.policy, self.root / 'absent.json', self.root / 'absent.html', 'm2')
        reference.require_render(self.context, self.policy, self.root / 'absent.json', self.root / 'absent.html', 'm3')

    def test_valid_submission_binds_job_input_policy_and_preserves_hero_product_and_approval(self):
        reply = self.submit()
        self.assertEqual(reply['status'], 'ACCEPTED')
        latest = next(row for row in store.records('jobs') if row['id'] == self.job['id'])
        self.assertEqual(latest['referenceSamples'], self.submission['referenceSamples'])
        self.assertEqual(self.context, json.loads((self.root / 'input.json').read_text(encoding='utf-8')))
        self.assertEqual(self.policy['referenceSamplesHash'], reference.digest(self.submission['referenceSamples']))
        self.assertEqual(self.policy['referenceNutritionHash'], reference.digest(self.submission['referenceNutrition']))
        self.assertEqual(set(self.context['referenceAssetFiles']), {'d2_ing1', 'd2_ing2', 'd2_ing3'})
        self.assertIn('未独立联网', reply['sourceReview'])
        self.assert_protected()

    def test_duplicate_submission_does_not_rebind_or_rewrite_accepted_input(self):
        first = self.submit(); before_job = copy.deepcopy(store.records('jobs')[0])
        before_bytes = (self.root / 'input.json').read_bytes()
        second = reference.accept_submission(self.product, self.job, self.root, self.context)
        self.assertEqual(second, first)
        self.assertEqual(store.records('jobs')[0], before_job)
        self.assertEqual((self.root / 'input.json').read_bytes(), before_bytes)

    def test_same_job_resume_reuses_bound_reference_payload(self):
        self.submit()
        latest = store.records('jobs')[0]
        fresh_policy = native_skill_jobs.contract(skill_jobs.SKILLS)
        resumed = reference.prepare(latest, self.product, self.root, fresh_policy)
        self.assertEqual(resumed['referenceSamples'], self.submission['referenceSamples'])
        self.assertEqual(resumed['referenceNutrition'], self.submission['referenceNutrition'])
        self.assert_protected()

    def test_invalid_binding_sources_facts_or_assets_do_not_pollute_job_input_policy(self):
        valid = copy.deepcopy(self.submission)
        faults = ('binding', 'source', 'nutrition', 'other_job', 'escape', 'absolute', 'hash', 'invalid_image')
        for fault in faults:
            with self.subTest(fault=fault):
                self.submission = copy.deepcopy(valid)
                if fault == 'binding': self.submission['executionBinding']['attributePlanFingerprint'] = 'stale'
                if fault == 'source': self.submission['referenceSamples']['d2']['source']['variant'] = 'Other flavor'
                if fault == 'nutrition': self.submission['referenceNutrition']['facts']['rows'][0]['dv'] = '999%'
                asset = self.submission['referenceAssets']['d2_ing1']
                if fault == 'other_job': asset['job'] = 'other-job'
                if fault == 'escape': asset['file'] = '../other.png'
                if fault == 'absolute': asset['file'] = 'C:/unapproved.png'
                if fault == 'hash': asset['sha256'] = '0' * 64
                if fault == 'invalid_image':
                    (self.root / 'reference-sources/invalid.png').write_bytes(b'not an image')
                    asset.update(file='reference-sources/invalid.png', sha256=hashlib.sha256(b'not an image').hexdigest())
                original_input = (self.root / 'input.json').read_bytes()
                original_job, original_policy = copy.deepcopy(store.records('jobs')[0]), copy.deepcopy(self.policy)
                reply = self.submit()
                self.assertEqual(reply['status'], 'REJECTED')
                self.assertTrue(reply['errors'])
                self.assertEqual(store.records('jobs')[0], original_job)
                self.assertEqual(self.policy, original_policy)
                self.assertEqual((self.root / 'input.json').read_bytes(), original_input)
                self.assert_protected()

    def test_changed_current_product_is_rejected_even_when_submission_binding_is_well_formed(self):
        newer = copy.deepcopy(self.product); newer['revision'] += 1; store.save_product(newer)
        reply = self.submit()
        self.assertEqual(reply['status'], 'REJECTED')
        self.assertEqual(store.product(self.product['id']), newer)
        self.assertNotIn('referenceSamples', store.records('jobs')[0])

    def test_only_reference_blockers_are_cleared_while_certificate_and_commitment_gaps_remain(self):
        blockers = {'m2': 'referenceSamples must contain both m2 and d2',
                    'd2': 'd2 requires all three source-bound ingredient images',
                    'm6': 'certificate evidence missing', 'm5': 'unverified capacity commitment'}
        self.job = store.job_update(self.job['id'], visualBlockers=blockers)
        self.context['visualBlockers'] = copy.deepcopy(blockers)
        self.write('input.json', self.context); self.write('blocked-modules.json', blockers)
        reply = self.submit()
        self.assertEqual(reply['status'], 'ACCEPTED')
        self.assertEqual(self.context['visualBlockers'], {'m6': blockers['m6'], 'm5': blockers['m5']})
        self.assertEqual(json.loads((self.root / 'blocked-modules.json').read_text(encoding='utf-8')),
                         self.context['visualBlockers'])

    def test_nutrition_may_be_added_later_without_replacing_already_bound_sources(self):
        nutrition = self.submission.pop('referenceNutrition')
        first = self.submit()
        self.assertEqual(first['status'], 'ACCEPTED')
        self.assertIn('m6', first['pendingReferenceModules'])
        self.submission['referenceNutrition'] = nutrition
        self.assertEqual(self.submit()['status'], 'ACCEPTED')
        self.submission['referenceSamples']['m2']['source']['variant'] = 'Changed'
        self.submission['referenceSamples']['d2']['source']['variant'] = 'Changed'
        self.assertEqual(self.submit()['status'], 'REJECTED')

    def test_job_only_contract_cannot_skip_render_checks_when_workflow_marker_is_absent(self):
        product = copy.deepcopy(self.product); product['workflow'].pop('freshVisualContract')
        job = dict(self.job, freshVisualContract='six-main-twelve-detail-reference-sample-v1')
        prepared = reference.prepare(job, product, self.root, self.policy)
        context = dict(product, **prepared)
        with self.assertRaises(ValueError):
            reference.require_render(context, self.policy, self.root / 'absent.json', self.root / 'absent.html', 'd2')

    def test_known_gummy_reference_only_messages_clear_but_mixed_certificate_message_does_not(self):
        messages = [message for message in reference.REFERENCE_GAPS if message.startswith(('Current workflow', 'referenceNutrition is absent'))]
        self.assertEqual(len(messages), 3)
        blockers = dict(zip(('m2', 'd2', 'm6'), [
            next(message for message in messages if 'referenceSamples.m2' in message),
            next(message for message in messages if 'referenceSamples.d2' in message),
            next(message for message in messages if message.startswith('referenceNutrition'))]))
        self.write('blocked-modules.json', blockers)
        self.assertEqual(self.submit()['status'], 'ACCEPTED')
        self.assertEqual(self.context['visualBlockers'], {})

    def test_child_only_certificate_and_business_diagnostics_never_become_controller_gates(self):
        diagnostics = {'m2': 'REFERENCE_SAMPLES_MISSING', 'd2': 'REFERENCE_ASSETS_MISSING',
                       'm6': 'REFERENCE_NUTRITION_MISSING', 'm5': 'Review company certificate source',
                       'df': 'Review company MOQ table'}
        self.write('blocked-modules.json', diagnostics)
        reply = self.submit()
        remaining = {'m5': diagnostics['m5'], 'df': diagnostics['df']}
        self.assertEqual(reply['status'], 'ACCEPTED')
        self.assertEqual(reply['diagnosticBlocks'], remaining)
        self.assertEqual(json.loads((self.root / 'blocked-modules.json').read_text(encoding='utf-8')), remaining)
        self.assertEqual(self.context['visualBlockers'], {})
        self.assertEqual(store.records('jobs')[0]['visualBlockers'], {})
        self.assert_protected()

    def test_mixed_reference_and_certificate_reason_is_not_silently_cleared(self):
        reason = 'REFERENCE_NUTRITION_MISSING; confirmed certificate evidence also missing'
        self.write('blocked-modules.json', {'m6': reason})
        reply = self.submit()
        self.assertEqual(reply['diagnosticBlocks'], {'m6': reason})
        self.assertEqual(json.loads((self.root / 'blocked-modules.json').read_text(encoding='utf-8')), {'m6': reason})

    def test_worker_accepts_submission_before_render_and_passes_auto_collection_protocol(self):
        self.write('reference-submission.json', self.submission)
        self.write('result.json', {'status': 'partial', 'images': [], 'reason': 'Offline fixture'})
        child = SimpleNamespace(pid=None, returncode=0)
        child.communicate = unittest.mock.Mock(side_effect=[skill_jobs.subprocess.TimeoutExpired('fixture', 5), (None, None)])
        seen = []
        def renderer(product, job, root, policy):
            actual = json.loads((root / 'input.json').read_text(encoding='utf-8'))
            seen.append(actual['referenceSamples'])
        with patch.object(skill_jobs, 'missing', return_value=[]), \
                patch.object(skill_jobs, 'executor_blocked', return_value=False), \
                patch.object(skill_jobs, 'skill_preflight', return_value={'available': True}), \
                patch.object(skill_jobs.shutil, 'which', return_value='fixture-codex'), \
                patch.object(skill_jobs.subprocess, 'Popen', return_value=child), \
                patch.object(native_skill_jobs, 'process_render_requests', side_effect=renderer), \
                patch.object(native_skill_jobs, 'publish_receipts', return_value=[]), \
                patch.object(native_skill_jobs, 'save_pending_images'), \
                patch.object(native_skill_jobs, 'save_partial'):
            with self.assertRaisesRegex(ValueError, '固定模板已完成'):
                skill_jobs.run(self.job)
        self.assertEqual(seen, [self.submission['referenceSamples']])
        prompt = (self.root / 'request.txt').read_text(encoding='utf-8')
        self.assertIn('reference-submission.json', prompt)
        self.assertIn('自行搜集公开', prompt)
        self.assertIn('不反复要求用户交参考', prompt)
        self.assertIn('不能把旧模型判断当成新用户要求', prompt)
        self.assert_protected()

    def test_database_write_failure_rolls_back_authoritative_input_and_job(self):
        original_db = store.db
        @contextmanager
        def failing_db():
            with original_db() as connection:
                class Proxy:
                    def execute(self, sql, parameters=()):
                        if sql.startswith('UPDATE jobs SET data='):
                            raise RuntimeError('Offline database failure')
                        return connection.execute(sql, parameters)
                yield Proxy()
        original_input = (self.root / 'input.json').read_bytes()
        original_job, original_policy = copy.deepcopy(store.records('jobs')[0]), copy.deepcopy(self.policy)
        with patch.object(store, 'db', failing_db):
            reply = self.submit()
        self.assertEqual(reply['status'], 'REJECTED')
        self.assertEqual((self.root / 'input.json').read_bytes(), original_input)
        self.assertEqual(store.records('jobs')[0], original_job)
        self.assertEqual(self.policy, original_policy)
        self.assert_protected()

    def test_noncurrent_output_directory_is_rejected_without_writing_a_response_there(self):
        other = self.state / 'unrelated'
        other.mkdir()
        reply = reference.accept_submission(self.product, self.job, other, self.context)
        self.assertEqual(reply['status'], 'REJECTED')
        self.assertEqual(list(other.iterdir()), [])

    def test_stopped_controller_flow_rejects_submission_without_rearming_it(self):
        stopped = copy.deepcopy(self.product); stopped['workflow']['status'] = 'STOPPED'; store.save_product(stopped)
        reply = self.submit()
        self.assertEqual(reply['status'], 'REJECTED')
        self.assertEqual(store.product(self.product['id']), stopped)
        self.assertNotIn('referenceSamples', store.records('jobs')[0])

    def test_worker_ignores_old_progress_but_accepts_a_fresh_update_without_deleting_history(self):
        self.write('result.json', {'status': 'partial', 'images': [], 'reason': 'Offline fixture'})
        self.write('progress.json', {'message': 'Old 9/18 missing references'})
        progress = self.root / 'progress.json'
        old_bytes = progress.read_bytes(); old_time = time.time_ns() - 60_000_000_000
        os.utime(progress, ns=(old_time, old_time))
        observations, calls = [], []
        def communicate(*args, **kwargs):
            calls.append(True)
            if len(calls) > 1:
                observations.append(store.records('jobs')[0]['progress'])
            if len(calls) == 2:
                self.assertEqual(progress.read_bytes(), old_bytes)
                self.write('progress.json', {'message': 'Current 10/18 references bound'})
                fresh = time.time_ns() + 60_000_000_000
                os.utime(progress, ns=(fresh, fresh))
            if len(calls) < 3: raise skill_jobs.subprocess.TimeoutExpired('fixture', 5)
            return None, None
        child = SimpleNamespace(pid=None, returncode=0, communicate=communicate)
        with patch.object(skill_jobs, 'missing', return_value=[]), \
                patch.object(skill_jobs, 'executor_blocked', return_value=False), \
                patch.object(skill_jobs, 'skill_preflight', return_value={'available': True}), \
                patch.object(skill_jobs.shutil, 'which', return_value='fixture-codex'), \
                patch.object(skill_jobs.subprocess, 'Popen', return_value=child), \
                patch.object(native_skill_jobs, 'process_render_requests'), \
                patch.object(native_skill_jobs, 'publish_receipts', return_value=[]), \
                patch.object(native_skill_jobs, 'save_pending_images'), \
                patch.object(native_skill_jobs, 'save_partial'):
            with self.assertRaisesRegex(ValueError, '固定模板已完成'):
                skill_jobs.run(self.job)
        self.assertNotEqual(observations[0], 'Old 9/18 missing references')
        self.assertEqual(observations[1], 'Current 10/18 references bound')

    def source_copy_m6(self):
        self.policy['executionBinding'] = copy.deepcopy(self.binding)
        self.write('input.json', self.context)
        self.submission['referenceNutrition']['facts']['source_copy'] = True
        self.assertEqual(self.submit()['status'], 'ACCEPTED')
        facts = copy.deepcopy(self.context['referenceNutrition']['facts'])
        spec = {'m7': {'facts': facts}}
        original = runpy.run_path(str(Path(self.policy['skillRoot']) / 'scripts/build.py'))
        values = original['facts_html'](copy.deepcopy(facts))
        self.assertEqual(values['DISCLAIMER_TOP'], '')
        self.assertEqual(values['DISCLAIMER_BOTTOM'], '')
        template = Path(self.policy['skillRoot']) / 'assets/templates' / self.policy['templates']['m6']['file']
        html = re.sub(r'\{\{([A-Z0-9_]+)\}\}', lambda match: str(values.get(match[1], 'fixture')),
                      template.read_text(encoding='utf-8'))
        return spec, html, template

    def test_source_copy_sample_fills_original_empty_slots_and_passes_existing_render_gate(self):
        spec, html, template = self.source_copy_m6()
        original_spec, original_context = copy.deepcopy(spec), copy.deepcopy(self.context)
        original_template = template.read_bytes()
        prepared = reference.prepare_render(self.context, self.policy, spec, html, 'm6')
        erase = lambda value: re.sub(r'(<div class="disc-(?:top|bottom)">)[^<]*(</div>)',
                                    lambda match: match[1] + match[2], value)
        self.assertEqual(erase(prepared), erase(html))
        self.assertNotEqual(prepared, html)
        self.write('source-copy-spec.json', spec)
        (self.root / 'source-copy-m6.html').write_text(prepared, encoding='utf-8')
        reference.require_render(self.context, self.policy, self.root / 'source-copy-spec.json',
                                 self.root / 'source-copy-m6.html', 'm6')
        self.assertEqual(reference.prepare_render(self.context, self.policy, spec, prepared, 'm6'), prepared)
        self.assertEqual(spec, original_spec)
        self.assertEqual(self.context, original_context)
        self.assertEqual(template.read_bytes(), original_template)
        self.assert_protected()

    def test_source_copy_wrong_nonempty_slot_or_changed_bound_data_is_rejected(self):
        spec, html, template = self.source_copy_m6()
        for slot in ('top', 'bottom'):
            corrupted = html.replace('<div class="disc-' + slot + '"></div>',
                                     '<div class="disc-' + slot + '">Wrong declaration</div>')
            with self.subTest(slot=slot), self.assertRaises(ValueError):
                reference.prepare_render(self.context, self.policy, spec, corrupted, 'm6')
        changed = copy.deepcopy(spec); changed['m7']['facts']['rows'][0]['amount'] = 23
        with self.assertRaises(ValueError): reference.prepare_render(self.context, self.policy, changed, html, 'm6')
        policy = copy.deepcopy(self.policy); policy['scriptHashes']['build.py'] = '0' * 64
        with self.assertRaises(ValueError): reference.prepare_render(self.context, policy, spec, html, 'm6')
        policy = copy.deepcopy(self.policy); policy['templates']['m6']['sha256'] = '0' * 64
        with self.assertRaises(ValueError): reference.prepare_render(self.context, policy, spec, html, 'm6')
        context = copy.deepcopy(self.context); context['executionBinding']['product'] = 'other'
        with self.assertRaises(ValueError): reference.prepare_render(context, self.policy, spec, html, 'm6')
        with self.assertRaises(ValueError): reference.prepare_render(self.context, self.policy, spec,
            html.replace('<div class="disc-top"></div>', '<div class="disc-top"></div>' * 2), 'm6')

    def test_disclaimer_preparation_does_not_apply_to_other_modes_or_missing_binding(self):
        spec, html, template = self.source_copy_m6()
        cases = []
        context = copy.deepcopy(self.context); context.pop('executionBinding'); cases.append((context, self.policy, spec, 'm6'))
        policy = copy.deepcopy(self.policy); policy.pop('referenceNutritionHash'); cases.append((self.context, policy, spec, 'm6'))
        policy = copy.deepcopy(self.policy); policy.pop('executionBinding'); cases.append((self.context, policy, spec, 'm6'))
        for mode in ('real', 'demo'):
            context = copy.deepcopy(self.context); context['referenceNutrition']['facts']['mode'] = mode
            cases.append((context, self.policy, spec, 'm6'))
        cases.append((self.context, self.policy, spec, 'm1'))
        for context, policy, candidate, slot in cases:
            self.assertEqual(reference.prepare_render(context, policy, candidate, html, slot), html)

    def test_render_bridge_prepares_source_copy_slots_before_original_gate_and_renderer(self):
        spec, html, template = self.source_copy_m6()
        build = self.root / 'source-copy-build'; build.mkdir()
        (build / 'm6.html').write_text(html, encoding='utf-8')
        self.write('source-copy-spec.json', spec)
        requests = self.root / 'render-requests'; requests.mkdir()
        self.write('render-requests/m6.json', {'spec': 'source-copy-spec.json',
                                              'build': 'source-copy-build', 'modules': ['m6']})
        with patch.object(native_skill_jobs.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as renderer, \
                patch.object(native_skill_jobs, 'publish_receipts', return_value=[]):
            native_skill_jobs.process_render_requests(self.product, self.job, self.root, self.policy)
        renderer.assert_called_once()
        reference.require_render(self.context, self.policy, self.root / 'source-copy-spec.json', build / 'm6.html', 'm6')
        self.assert_protected()


if __name__ == '__main__': unittest.main()
