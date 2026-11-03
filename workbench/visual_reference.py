"""Carry reviewed competitor examples across visual jobs without creating SKU facts."""
import hashlib
import ast
import copy
from html import escape, unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import tempfile

import task_store as store
from shared_scan import atomic_json

SOURCE_REVIEW = '已检查本地结构、来源摘录一致性及文件哈希；未独立联网证明官网真实性。'
REFERENCE_GAPS = {
    'REFERENCE_SAMPLES_MISSING', 'REFERENCE_ASSETS_MISSING', 'REFERENCE_NUTRITION_MISSING',
    'referenceSamples must contain both m2 and d2',
    'd2 requires all three source-bound ingredient images',
    'nutrition reference is missing; m6 requires a bound sample or confirmed real formula',
    'Current workflow requires reference-sample-v1 but input.json has no bound referenceSamples.m2. No confirmed gummy ingredient formula. Do not substitute powder reference ingredients as this SKU formula.',
    'Current workflow requires reference-sample-v1 but referenceSamples.d2 and all three referenceAssetFiles/source bindings are absent. No confirmed gummy ingredient formula.',
    'referenceNutrition is absent under the current reference-sample-v1 binding; facts.mode is concept with no real formula. Existing SEEQ powder reference cannot pass the required bound nutrition check and is not a gummy formula.',
}


def _required(context, product=None, policy=None):
    return bool((policy or {}).get('referenceRequired') or any(
        str(value).endswith('reference-sample-v1') for value in (
            context.get('freshVisualContract'), (context.get('workflow') or {}).get('freshVisualContract'),
            ((product or {}).get('workflow') or {}).get('freshVisualContract'))))


def digest(samples):
    return hashlib.sha256(json.dumps(samples, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _helper(policy):
    script = Path(policy['skillRoot']) / 'scripts/reference_sample.py'
    if hashlib.sha256(script.read_bytes()).hexdigest() != policy['scriptHashes'].get('reference_sample.py'):
        raise ValueError('reference sample validator changed during execution')
    return runpy.run_path(str(script))


def validate(samples, policy, facts=None):
    if not isinstance(samples, dict) or set(samples) != {'m2', 'd2'}:
        raise ValueError('referenceSamples must contain both m2 and d2')
    helper = _helper(policy)
    for slot, sample in samples.items():
        errors = helper['validate_reference_sample'](sample, product_facts=facts, module=slot)
        if errors or set(sample.get('modules', {})) != {slot}:
            raise ValueError('invalid reference sample ' + slot + ': ' + '; '.join(errors))
    base = [{k: v for k, v in samples[slot].items() if k != 'modules'} for slot in ('m2', 'd2')]
    if base[0] != base[1]:
        raise ValueError('m2/d2 reference source, variant and evidence must match')
    return json.loads(json.dumps(samples))


def validate_nutrition(reference, samples, policy):
    if not isinstance(reference, dict) or reference.get('source') != samples['m2']['source']:
        raise ValueError('nutrition reference source must match the selected competitor SKU')
    facts = reference.get('facts')
    if not isinstance(facts, dict) or facts.get('mode') != 'sample' or not isinstance(facts.get('rows'), list) or not facts['rows']:
        raise ValueError('nutrition reference must contain the validated sample facts')
    needle = reference['source']['url']
    variant = reference['source']['variant']
    for row in facts['rows']:
        source = str(row.get('source') or '')
        if needle not in source or variant not in source or 'Competitor reference' not in source:
            raise ValueError('nutrition row source must identify the same competitor product and variant')
    _check_skill_facts(facts, policy)
    return json.loads(json.dumps(reference))


def _check_skill_facts(facts, policy):
    skill = Path(policy['skillRoot'])
    checker = skill / 'scripts/check_facts.py'
    if hashlib.sha256(checker.read_bytes()).hexdigest() != policy['scriptHashes'].get('check_facts.py'):
        raise ValueError('nutrition facts checker changed during execution')
    api = runpy.run_path(str(checker))
    table = api['load_dv_table'](skill / 'assets/schemas/dv_table.json')
    report = api['Report']()
    api['check_facts']({'m7': {'facts': facts}}, table, report, False)
    if report.errors:
        raise ValueError('nutrition facts failed Skill validation')


def _file(root, name):
    root = Path(root).resolve()
    path = (root / str(name)).resolve()
    if not path.is_relative_to(root) or path == root or not path.is_file() or path.is_symlink():
        raise ValueError('reference asset path is missing or outside its source job')
    return path


def _bound_context(root, product, identity):
    context = json.loads(_file(root, 'input.json').read_text(encoding='utf-8-sig'))
    expected = {'job': identity, 'product': product['id'], 'revision': product['revision'],
        'attributePlanFingerprint': (product.get('attributePlan') or {}).get('fingerprint', '')}
    if (context.get('id') != product['id'] or context.get('revision') != product['revision']
            or context.get('executionBinding') != expected):
        raise ValueError('reference source is not bound to this product revision')
    return context


def migrate(product, old_job, old_root, policy):
    """Read only explicitly bound current/history jobs; never scan unrelated runs."""
    candidates = [(old_job['id'], Path(old_root))]
    candidates += [(row['job'], store.STATE / 'runs' / row['job'])
        for row in reversed(product.get('visualHistory') or [])
        if row.get('revision') == product['revision'] and row.get('job') != old_job['id']]
    runs = (store.STATE / 'runs').resolve()
    for index, (identity, root) in enumerate(candidates):
        if not root.resolve().is_relative_to(runs) or root.resolve() == runs:
            raise ValueError('reference source job path is invalid')
        try:
            context = _bound_context(root, product, identity)
        except (OSError, ValueError):
            if index == 0:
                raise ValueError('old reference source executionBinding is invalid') from None
            continue
        samples = context.get('referenceSamples')
        detail = None
        main_spec = None
        if samples is None:
            samples = {}
            for slot, filenames in {'m2': ('product-concept.json', 'product.json'),
                                    'd2': ('detail-concept.json', 'detail.json')}.items():
                for filename in filenames:
                    path = root / filename
                    if not path.is_file():
                        continue
                    spec = json.loads(_file(root, filename).read_text(encoding='utf-8-sig'))
                    if slot == 'm2' and main_spec is None: main_spec = spec
                    sample = (spec.get(slot) or {}).get('sampleReference')
                    if sample is not None:
                        samples[slot] = sample
                        if slot == 'd2': detail = spec['d2']
                        break
            if not samples:
                continue
        samples = validate(samples, policy, product.get('facts'))
        nutrition = context.get('referenceNutrition')
        if nutrition is None:
            for filename in ('product-concept.json', 'product.json'):
                spec = main_spec if filename == 'product-concept.json' and main_spec is not None else None
                path = root / filename
                if spec is None and path.is_file(): spec = json.loads(_file(root, filename).read_text(encoding='utf-8-sig'))
                facts = (spec.get('m7') or {}).get('facts') if isinstance(spec, dict) else None
                if facts:
                    nutrition = {'source': samples['m2']['source'], 'facts': facts}
                    break
        if nutrition is not None:
            nutrition = validate_nutrition(nutrition, samples, policy)
        assets = context.get('referenceAssets') or {}
        if detail is not None:
            assets = {}
            for key in ('d2_ing1', 'd2_ing2', 'd2_ing3'):
                name = (detail.get('images') or {}).get(key)
                if name:
                    path = _file(root, name)
                    assets[key] = {'job': identity, 'file': str(path.relative_to(root.resolve())),
                                   'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        blockers = context.get('visualBlockers') or {}
        if not isinstance(blockers, dict):
            raise ValueError('visual blockers must identify module evidence gaps')
        blocked_file = root / 'blocked-modules.json'
        if blocked_file.is_file():
            previous = json.loads(_file(root, 'blocked-modules.json').read_text(encoding='utf-8-sig'))
            if not isinstance(previous, dict):
                raise ValueError('blocked modules file has an invalid shape')
            blockers = {**blockers, **previous}
        resolved = {'m2', 'd2'} | ({'m6'} if nutrition is not None else set())
        blockers = {key: str(value)[:500] for key, value in blockers.items()
                    if key in policy['templates'] and key not in resolved and value}
        result = {'referenceSamples': samples, 'referenceAssets': assets, 'visualBlockers': blockers}
        if nutrition is not None: result['referenceNutrition'] = nutrition
        return result
    raise ValueError('reference samples m2/d2 are missing; preserve the previous task')


def prepare(job, product, root, policy):
    required = _required(job, product, policy)
    if not required and not job.get('referenceSamples'):
        return {}
    blockers = job.get('visualBlockers') or {}
    if not isinstance(blockers, dict) or any(key not in policy['templates'] for key in blockers):
        raise ValueError('visual blocker module mapping is invalid')
    if required:
        policy['referenceRequired'] = True
    if not job.get('referenceSamples'):
        return {'referenceAcquisition': {'status': 'REQUIRED', 'submission': 'reference-submission.json',
                'response': 'reference-response.json', 'sourceReview': SOURCE_REVIEW},
                'visualBlockers': copy.deepcopy(blockers)}
    samples = validate(job.get('referenceSamples'), policy, product.get('facts'))
    files = {}
    assets = job.get('referenceAssets') or {}
    if not isinstance(assets, dict) or len(assets) > 3:
        raise ValueError('reference ingredient images must be a bounded slot mapping')
    for key, source in assets.items():
        if key not in {'d2_ing1', 'd2_ing2', 'd2_ing3'}:
            raise ValueError('unknown reference ingredient image slot')
        if not isinstance(source, dict):
            raise ValueError('reference ingredient image source is invalid')
        source_root = (store.STATE / 'runs' / str(source.get('job', ''))).resolve()
        if not source_root.is_relative_to((store.STATE / 'runs').resolve()):
            raise ValueError('reference source asset job is invalid')
        _bound_context(source_root, product, source['job'])
        original = _file(source_root, source.get('file', ''))
        if original.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
            raise ValueError('reference ingredient asset must be an image')
        if hashlib.sha256(original.read_bytes()).hexdigest() != source.get('sha256'):
            raise ValueError('reference ingredient image changed')
        target = Path(root) / 'assets/reference-ingredients' / (key + original.suffix.lower())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
        files[key] = str(target.relative_to(root)).replace('\\', '/')
    policy['referenceSamplesHash'] = digest(samples)
    nutrition = job.get('referenceNutrition')
    if nutrition is not None:
        nutrition = validate_nutrition(nutrition, samples, policy)
        policy['referenceNutritionHash'] = digest(nutrition)
    if blockers:
        (Path(root) / 'blocked-modules.json').write_text(json.dumps(blockers, ensure_ascii=False, indent=2), encoding='utf-8')
    result = {'referenceSamples': samples, 'referenceAssets': job.get('referenceAssets') or {},
              'referenceAssetFiles': files, 'visualBlockers': blockers,
              'referenceAcquisition': {'status': 'BOUND', 'sourceReview': SOURCE_REVIEW}}
    if nutrition is not None: result['referenceNutrition'] = nutrition
    return result


def _submission_reply(root, reply):
    path = root / 'reference-response.json'
    if path.is_symlink() or path.with_suffix('.tmp').is_symlink():
        return reply
    try:
        if json.loads(path.read_text(encoding='utf-8')) == reply:
            return reply
    except (OSError, ValueError):
        pass
    atomic_json(path, reply)
    return reply


def _reference_gap(value):
    if isinstance(value, dict):
        return value.get('kind') == 'reference-input' and value.get('code') in REFERENCE_GAPS
    return isinstance(value, str) and value.strip() in REFERENCE_GAPS


def accept_submission(product, job, root, context):
    """Accept only current-run references; no product facts, approval or m1 writes.

    The child writes a complete fixed submission file, then waits for the fixed
    response. All validation finishes before authoritative job/input writes.
    """
    root = Path(root).resolve()
    expected_root = (store.STATE / 'runs' / job['id']).resolve()
    if root != expected_root or not root.is_relative_to((store.STATE / 'runs').resolve()):
        return {'status': 'REJECTED', 'errors': ['reference submission does not belong to the current job directory'],
                'sourceReview': SOURCE_REVIEW}
    submission = root / 'reference-submission.json'
    if not submission.exists():
        return None
    submission_hash = ''
    old_input = None
    old_blocked = None
    input_written = blocked_written = False
    committed = False
    try:
        if submission.is_symlink() or submission.stat().st_size > 1024 * 1024:
            raise ValueError('reference submission file is invalid or too large')
        payload_bytes = submission.read_bytes()
        submission_hash = hashlib.sha256(payload_bytes).hexdigest()
        payload = json.loads(payload_bytes.decode('utf-8-sig'))
        if (not isinstance(payload, dict) or set(payload) - {
                'executionBinding', 'referenceSamples', 'referenceNutrition', 'referenceAssets'}):
            raise ValueError('reference submission must contain only the fixed reference fields')
        binding = context.get('executionBinding')
        if not isinstance(binding, dict) or payload.get('executionBinding') != binding:
            raise ValueError('reference submission executionBinding does not match the current job')
        old_input = _file(root, 'input.json').read_bytes()
        if json.loads(old_input.decode('utf-8-sig')) != context:
            raise ValueError('task input changed outside the server reference handoff')
        policy = context['nativeTemplateContract']
        samples = validate(payload.get('referenceSamples'), policy, product.get('facts'))
        nutrition = payload.get('referenceNutrition') or job.get('referenceNutrition')
        if nutrition is not None:
            nutrition = validate_nutrition(nutrition, samples, policy)
        if policy.get('referenceSamplesHash') and digest(samples) != policy['referenceSamplesHash']:
            raise ValueError('already bound reference samples cannot be replaced within this job')
        if (policy.get('referenceNutritionHash') and
                (nutrition is None or digest(nutrition) != policy['referenceNutritionHash'])):
            raise ValueError('already bound reference nutrition cannot be replaced within this job')
        assets = payload.get('referenceAssets')
        if not isinstance(assets, dict) or set(assets) != {'d2_ing1', 'd2_ing2', 'd2_ing3'}:
            raise ValueError('reference submission requires exactly three ingredient assets')
        from PIL import Image
        for key, source in assets.items():
            if not isinstance(source, dict) or source.get('job') != job['id']:
                raise ValueError('reference assets must belong to the current job')
            name = source.get('file')
            if not isinstance(name, str) or Path(name).is_absolute() or re.match(r'^[A-Za-z]:', name):
                raise ValueError('reference assets require current-job relative image paths')
            lexical = root / name
            if lexical.is_symlink() or any(parent.is_symlink() for parent in lexical.parents if parent != root and parent.is_relative_to(root)):
                raise ValueError('reference asset symlinks are not accepted')
            image = _file(root, name)
            if image.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
                raise ValueError('reference ingredient asset must be a PNG/JPG/WEBP image')
            if hashlib.sha256(image.read_bytes()).hexdigest() != source.get('sha256'):
                raise ValueError('reference ingredient image hash does not match submission')
            with Image.open(image) as decoded:
                decoded.verify()
            previous = (job.get('referenceAssets') or {}).get(key)
            if previous and previous.get('sha256') != source.get('sha256'):
                raise ValueError('already bound ingredient assets cannot be replaced within this job')
        blockers = {}
        resolved = {'m2', 'd2'} | ({'m6'} if nutrition is not None else set())
        cleared = set()
        blocked_file = root / 'blocked-modules.json'
        if blocked_file.is_symlink():
            raise ValueError('reference diagnostics must remain a regular current-job file')
        old_blocked = blocked_file.read_bytes() if blocked_file.is_file() else None
        file_blockers = json.loads(old_blocked.decode('utf-8-sig')) if old_blocked else {}
        if not isinstance(file_blockers, dict) or any(key not in policy['templates'] for key in file_blockers):
            raise ValueError('reference handoff encountered an invalid diagnostic-module mapping')
        diagnostics = {}
        for key, reason in file_blockers.items():
            if key in resolved and _reference_gap(reason):
                cleared.add(key)
            else:
                diagnostics[key] = copy.deepcopy(reason)
        # The child report is diagnostic data, not permission to add controller gates.
        for group in (job.get('visualBlockers') or {}, context.get('visualBlockers') or {}):
            if not isinstance(group, dict) or any(key not in policy['templates'] for key in group):
                raise ValueError('reference handoff encountered an invalid blocked-module mapping')
            for key, reason in group.items():
                if key in resolved and _reference_gap(reason):
                    cleared.add(key)
                elif key not in blockers:
                    blockers[key] = copy.deepcopy(reason)
                elif blockers[key] != reason:
                    blockers[key] = str(blockers[key]) + '; ' + str(reason)
        changes = {'referenceSamples': samples, 'referenceAssets': assets, 'visualBlockers': blockers}
        if nutrition is not None:
            changes['referenceNutrition'] = nutrition
        staged_policy = copy.deepcopy(policy)
        from native_skill_jobs import require_current_binding, policy_matches_skill
        with tempfile.TemporaryDirectory(dir=root, prefix='reference-stage-') as temporary:
            staging = Path(temporary)
            prepared = prepare(dict(job, **changes), product, staging, staged_policy)
            for key, relative in prepared['referenceAssetFiles'].items():
                if hashlib.sha256((staging / relative).read_bytes()).hexdigest() != assets[key]['sha256']:
                    raise ValueError('reference ingredient image changed while preparing the handoff')
            new_context = dict(copy.deepcopy(context), **prepared, nativeTemplateContract=staged_policy)
            with store.db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                row = conn.execute('SELECT data,status,scope FROM jobs WHERE id=?', (job['id'],)).fetchone()
                current_row = conn.execute('SELECT data FROM products WHERE id=?', (product['id'],)).fetchone()
                if not row or not current_row:
                    raise ValueError('reference job or product no longer exists')
                latest, current = json.loads(row['data']), json.loads(current_row['data'])
                require_current_binding(current, binding, latest)
                if (row['status'] != 'RUNNING' or row['scope'] != 'product:' + product['id']
                        or latest.get('kind') != 'visual' or latest.get('product') != product['id']
                        or latest.get('imageProvider') != 'codex-native'
                        or (current.get('workflow') or {}).get('status') in {'STOPPED', 'STALE'}):
                    raise ValueError('reference handoff requires this active native visual job')
                if not policy_matches_skill(Path(policy['skillRoot']), policy):
                    raise ValueError('reference handoff Skill contract changed')
                if latest.get('referenceSubmissionHash') == submission_hash:
                    reply = latest['referenceAcceptance']
                else:
                    reply = {'status': 'ACCEPTED', 'submissionSha256': submission_hash,
                             'executionBinding': binding, 'sourceReview': SOURCE_REVIEW,
                             'clearedReferenceBlocks': sorted(cleared), 'remainingBlockers': blockers,
                             'diagnosticBlocks': diagnostics,
                             'pendingReferenceModules': [] if nutrition is not None else ['m6']}
                    updated = dict(latest, **changes, referenceSubmissionHash=submission_hash,
                                   referenceAcceptance=reply, updated=store.now())
                    for output in (blocked_file, root / 'input.json'):
                        if output.is_symlink() or output.with_suffix('.tmp').is_symlink():
                            raise ValueError('reference output paths must remain regular current-job files')
                    for relative in prepared['referenceAssetFiles'].values():
                        if not (root / relative).resolve().is_relative_to(root):
                            raise ValueError('reference ingredient output escapes the current job directory')
                    for relative in prepared['referenceAssetFiles'].values():
                        target = root / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(staging / relative, target)
                    atomic_json(blocked_file, diagnostics)
                    blocked_written = True
                    atomic_json(root / 'input.json', new_context)
                    input_written = True
                    conn.execute('UPDATE jobs SET data=?,updated=? WHERE id=?',
                                 (json.dumps(updated, ensure_ascii=False), updated['updated'], job['id']))
            committed = True
        if input_written:
            policy.clear(); policy.update(staged_policy)
            context.clear(); context.update(new_context); context['nativeTemplateContract'] = policy
            job.clear(); job.update(updated)
        return _submission_reply(root, reply)
    except Exception as error:
        if not committed:
            for name, previous, written in (('input.json', old_input, input_written),
                                             ('blocked-modules.json', old_blocked, blocked_written)):
                if not written:
                    continue
                target = root / name
                if previous is None:
                    target.unlink(missing_ok=True)
                else:
                    temporary = target.with_suffix('.restore.tmp')
                    temporary.write_bytes(previous); os.replace(temporary, target)
        message = str(error)[:400] if isinstance(error, ValueError) else '参考提交失败：' + type(error).__name__
        return _submission_reply(root, {'status': 'REJECTED', 'submissionSha256': submission_hash,
                                       'errors': [message], 'sourceReview': SOURCE_REVIEW})


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.excluded = 0
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in ('style', 'script'): self.excluded += 1

    def handle_endtag(self, tag):
        if tag in ('style', 'script'): self.excluded = max(0, self.excluded - 1)

    def handle_data(self, data):
        if not self.excluded: self.text.append(data)


def prepare_render(context, policy, spec, html, slot='m6'):
    """Return HTML with original empty sample disclaimers filled; never write facts/files."""
    nutrition = context.get('referenceNutrition') or {}
    facts = nutrition.get('facts') or {}
    if slot != 'm6' or facts.get('mode') != 'sample' or facts.get('source_copy') is not True:
        return html
    binding = context.get('executionBinding')
    if (not isinstance(binding, dict) or not isinstance(policy.get('executionBinding'), dict)
            or not binding.get('job')
            or not policy.get('referenceSamplesHash') or not policy.get('referenceNutritionHash')):
        return html
    if (policy['executionBinding'] != binding or binding.get('product') != context.get('id')
            or binding.get('revision') != context.get('revision')
            or (context.get('attributePlan') and binding.get('attributePlanFingerprint')
                != context['attributePlan'].get('fingerprint'))):
        raise ValueError('sample disclaimer preparation executionBinding does not match the task')
    samples = validate(context.get('referenceSamples'), policy, context.get('facts'))
    if digest(samples) != policy['referenceSamplesHash'] or digest(nutrition) != policy['referenceNutritionHash']:
        raise ValueError('sample disclaimer preparation requires unchanged bound reference data')
    validate_nutrition(copy.deepcopy(nutrition), samples, policy)
    if (spec.get('m7') or {}).get('facts') != facts:
        raise ValueError('sample disclaimer preparation cannot change source-bound nutrition facts')
    skill = Path(policy['skillRoot'])
    script = skill / 'scripts/build.py'
    original = script.read_bytes()
    if hashlib.sha256(original).hexdigest() != policy.get('scriptHashes', {}).get('build.py'):
        raise ValueError('original Skill disclaimer source changed during execution')
    tree = ast.parse(original.decode('utf-8-sig'))
    constants = {target.id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                 for target in node.targets if isinstance(target, ast.Name) and target.id in {'_DISC_TOP', '_DISC_BOTTOM'}}
    if any(not isinstance(constants.get(key), str) or not constants[key] for key in ('_DISC_TOP', '_DISC_BOTTOM')):
        raise ValueError('original Skill sample disclaimers are unavailable')
    contract = policy['templates']['m6']
    template = skill / 'assets/templates' / contract['file']
    template_bytes = template.read_bytes()
    if hashlib.sha256(template_bytes).hexdigest() != contract['sha256']:
        raise ValueError('original m6 template changed during execution')
    for name, expected in (('top', constants['_DISC_TOP']),
                           ('bottom', constants['_DISC_BOTTOM'].replace('Supplement Facts', str(facts.get('facts_title', 'Supplement Facts'))))):
        token = '<div class="disc-' + name + '">{{DISCLAIMER_' + name.upper() + '}}</div>'
        if template_bytes.decode('utf-8-sig').count(token) != 1:
            raise ValueError('original m6 disclaimer slot is not unique: ' + name)
        pattern = r'(<div class="disc-' + name + r'">)([^<]*)(</div>)'
        matches = list(re.finditer(pattern, html))
        if len(matches) != 1:
            raise ValueError('built m6 disclaimer slot is missing or not unique: ' + name)
        match = matches[0]
        current = unescape(match[2]).strip()
        if current and current != expected:
            raise ValueError('nonempty m6 disclaimer differs from the original Skill: ' + name)
        if not current:
            html = html[:match.start(2)] + escape(expected, quote=False) + html[match.end(2):]
    return html


def require_render(context, policy, spec_path, html_path, slot):
    if slot in (context.get('visualBlockers') or {}):
        raise ValueError('unresolved factual evidence blocks module: ' + slot)
    if slot not in {'m2', 'd2'}:
        if slot != 'm6':
            return
        required = _required(context, policy=policy)
        nutrition = context.get('referenceNutrition')
        if not nutrition:
            spec = json.loads(Path(spec_path).read_text(encoding='utf-8-sig'))
            facts = (spec.get('m7') or {}).get('facts')
            product = context.get('facts') or {}
            if required:
                if (product.get('mode') != 'real' or not str(product.get('formula') or '').strip()
                        or not isinstance(facts, dict) or facts.get('mode') != 'real'):
                    raise ValueError('nutrition reference is missing; m6 requires a bound sample or confirmed real formula')
                _check_skill_facts(facts, policy)
                tree = ast.parse((Path(policy['skillRoot']) / 'scripts/build.py').read_text(encoding='utf-8-sig'))
                constants = {target.id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                    and isinstance(node.value, (ast.Constant, ast.BinOp, ast.JoinedStr))
                    for target in node.targets if isinstance(target, ast.Name) and target.id in {'_DISC_TOP_REAL'}}
                parser = _VisibleText(); parser.feed(Path(html_path).read_text(encoding='utf-8'))
                visible = re.sub(r'\s+', ' ', ' '.join(parser.text))
                if constants.get('_DISC_TOP_REAL') not in visible:
                    raise ValueError('m6 is missing the fixed real nutrition disclaimer')
                return
            if (context.get('visualReferenceScope') or {}).get('validatedSampleInput'):
                raise ValueError('nutrition reference is missing from the selected competitor sample')
            return
        samples = validate(context.get('referenceSamples'), policy, context.get('facts'))
        nutrition = validate_nutrition(nutrition, samples, policy)
        if policy.get('referenceNutritionHash') and digest(nutrition) != policy['referenceNutritionHash']:
            raise ValueError('nutrition reference changed after the task was bound')
        spec = json.loads(Path(spec_path).read_text(encoding='utf-8-sig'))
        if (spec.get('m7') or {}).get('facts') != nutrition['facts']:
            raise ValueError('m6 must use the source-bound sample nutrition facts')
        tree = ast.parse((Path(policy['skillRoot']) / 'scripts/build.py').read_text(encoding='utf-8-sig'))
        constants = {target.id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
            and isinstance(node.value, (ast.Constant, ast.BinOp, ast.JoinedStr))
            for target in node.targets if isinstance(target, ast.Name) and target.id in {'_DISC_TOP', '_DISC_BOTTOM'}}
        bottom = constants.get('_DISC_BOTTOM', '').replace('Supplement Facts', str(nutrition['facts'].get('facts_title', 'Supplement Facts')))
        parser = _VisibleText(); parser.feed(Path(html_path).read_text(encoding='utf-8'))
        visible = re.sub(r'\s+', ' ', ' '.join(parser.text))
        if constants.get('_DISC_TOP') not in visible or bottom not in visible:
            raise ValueError('m6 is missing the fixed sample nutrition disclaimer')
        return
    required = _required(context, policy=policy)
    if not required and not context.get('referenceSamples'):
        return
    samples = validate(context.get('referenceSamples'), policy, context.get('facts'))
    if policy.get('referenceSamplesHash') and digest(samples) != policy['referenceSamplesHash']:
        raise ValueError('reference sample payload changed after the task was bound')
    spec = json.loads(Path(spec_path).read_text(encoding='utf-8-sig'))
    if (spec.get(slot) or {}).get('sampleReference') != samples[slot]:
        raise ValueError(slot + ': reference sample is missing or differs from the bound source')
    if slot == 'd2':
        files = context.get('referenceAssetFiles') or {}
        image_fields = (spec.get('d2') or {}).get('images') or {}
        sources = context.get('referenceAssets') or {}
        if set(files) != {'d2_ing1', 'd2_ing2', 'd2_ing3'}:
            raise ValueError('d2 requires all three source-bound ingredient images')
        for key, relative in files.items():
            image_path = (Path(spec_path).parent / relative).resolve()
            if (image_fields.get(key) != relative or not image_path.is_file()
                    or hashlib.sha256(image_path.read_bytes()).hexdigest() != sources.get(key, {}).get('sha256')):
                raise ValueError('d2 ingredient image is missing or differs from its bound source: ' + key)
    helper = _helper(policy)
    product_facts = {}
    for key in ('product', 'productFacts'):
        if isinstance(spec.get(key), dict): product_facts.update(spec[key])
    fields = helper['reference_fields'](samples[slot], slot, product_facts)
    built = Path(html_path).read_text(encoding='utf-8')
    label = re.search(r'<div class="reference-note">([^<]*)</div>', built)
    if not label or label[1].strip() != helper['REFERENCE_LABEL']:
        raise ValueError(slot + ': visible reference label is missing')
    parser = _VisibleText()
    parser.feed(built)
    visible = re.sub(r'\s+', ' ', ' '.join(parser.text))
    for key, value in fields.items():
        if key != 'REFERENCE_CSS' and re.sub(r'\s+', ' ', unescape(value)) not in visible:
            raise ValueError(slot + ': fixed reference title or ingredient text is missing')
