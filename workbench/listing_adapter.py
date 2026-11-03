"""Fixed original Skill entry, explicit image delivery, strict actual draft receipts."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from urllib.parse import urlsplit, parse_qsl
import task_store as store

SLOTS = [f'm{i}' for i in range(1, 7)] + ['d1','d2','d3','d4','df','d5','d6','dfac','d7','dc','drev','d9']
LEGACY_SLOTS = [f'm{i}' for i in range(1, 8)] + SLOTS[6:]


def read_publication_status(product, reader=None, expected_account=None):
    """Read-only collector boundary. Never accepts HTTP-client assertions as authority.

    The backend supplies a trusted collector; default is explicitly unconfigured.
    A saved draft, editor URL, local Job or old report cannot prove publication.
    """
    draft = product.get('draft') or {}
    key = str((product.get('facts') or {}).get('store') or '')
    draft_id = str(draft.get('draft_id') or '')
    product_id = str(draft.get('product_id') or draft_id)
    result = {'status': 'unknown', 'published': None, 'store': key, 'draft_id': draft_id,
              'product_id': product_id, 'draft_url': draft.get('draft_url', ''),
              'checked_at': datetime.now(timezone.utc).isoformat(), 'authority': {}, 'evidence': {},
              'reason': '尚未配置已验证的平台商品状态只读采集器；未推断是否已发布'}
    if reader is None:
        return result
    if not key or not draft_id or (draft.get('store') and draft['store'] != key):
        return dict(result, reason='草稿身份或目标店铺未明确，不能读取发布状态')
    if expected_account is None:
        import weekly_update
        expected_account = weekly_update.STORES.get(key, {}).get('expected_id')
    if not expected_account:
        return dict(result, reason='目标账号未配置，发布状态保持未知')
    target = {'store': key, 'draft_id': draft_id, 'product_id': product_id,
              'expected_account': str(expected_account)}
    if draft.get('category_id'):target['category_id']=str(draft['category_id'])
    try:
        observation = reader(target)
        source = observation.get('source') or {}
        identity = observation.get('identity') or {}
        row = observation.get('row') or {}
        observed = datetime.fromisoformat(str(observation.get('observed_at', '')).replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - observed).total_seconds()
        if (identity.get('verified') is not True or str(identity.get('account_id')) != str(expected_account)
                or str(row.get('item_id')) != product_id or str(row.get('draft_id')) != draft_id
                or not -30 <= age <= 300):
            raise ValueError('unverified publication identity or age')
        if source.get('kind') == 'workctl-tool':
            import listing_publication
            parsed = listing_publication.verify_observation(observation, product_id)
            evidence = {'item_id': product_id, 'draft_id': draft_id,
                        'status_field': parsed['status_field'], 'status_values': parsed['status_values'],
                        'observed_at': observation['observed_at'], 'source_command': source['command'],
                        'payload_sha256': source['payload_sha256'], 'schema_sha256': source['schema_sha256']}
            digest = hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
            # The response identity and raw values are evidence even before numeric enums are verified.
            status = parsed['status'] if parsed.get('mapping_verified') is True else 'unknown'
            if status not in ('published', 'draft', 'unpublished', 'unknown'):
                raise ValueError('unverified mapped publication status')
            return dict(result, status=status, published=None if status == 'unknown' else status == 'published',
                        reason=parsed.get('reason', '') if status == 'unknown' else '',
                        authority={'method': source['method'], 'source_kind': source['kind'],
                                   'command': source['command'], 'identity_verified': True,
                                   'observed_at': observation['observed_at']},
                        evidence=dict(evidence, sha256=digest))
        url = urlsplit(str(source.get('url', '')))
        permitted_queries = {'itemId', 'productId', 'draftId', 'page', 'status', 'from'}
        if (url.scheme != 'https' or url.hostname != 'i.alibaba.com' or url.username or url.password
                or url.port not in (None, 443) or url.path.rstrip('/') != '/prod/product_manage'
                or any(name not in permitted_queries for name, _ in parse_qsl(url.query))
                or source.get('method') != 'GET' or source.get('kind') != 'product_manager_row'
                or row.get('status_field') not in ('商品状态', 'Product status')):
            raise ValueError('unverified publication observation')
        import listing_browser_publication
        parsed=listing_browser_publication.verify_observation(observation,product_id,draft_id,str(expected_account))
        if parsed.get('mapping_verified') is not True:
            return dict(result,reason='商品管理页没有明确且一致的状态文字，保持未知')
        label = str(row.get('status_text', '')).strip().lower()
        statuses = {'已发布': 'published', '已上架': 'published', 'published': 'published',
                    '草稿': 'draft', 'draft': 'draft', '已下架': 'unpublished', 'unpublished': 'unpublished'}
        status = statuses.get(label)
        if status is None:
            return dict(result, reason='平台商品状态没有已验证映射，保持未知')
        evidence = {'item_id': product_id, 'draft_id': draft_id, 'status_field': row['status_field'],
                    'status_text': row['status_text'], 'source_url': source['url'],
                    'observed_at': observation['observed_at']}
        digest = hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
        return dict(result, status=status, published=status == 'published', reason='',
                    authority={'source_url': source['url'], 'method': 'GET', 'source_kind': source['kind'],
                               'identity_verified': True, 'observed_at': observation['observed_at']},
                    evidence=dict(evidence, sha256=digest))
    except Exception:
        # Do not echo collector exceptions: they can contain URLs, tokens or account data.
        return dict(result, reason='只读回读失败或账号、商品ID、状态字段、来源、时效未通过；保持未知')


def refresh_publication(product, evidence_root=None, recover_browser=False):
    """Consume the account-bound collector; unknown enums retain verified raw evidence."""
    result = read_publication_status(product)
    draft = product.get('draft') or {}
    key = str((product.get('facts') or {}).get('store') or '')
    import re
    if (not re.fullmatch(r'[1-9][0-9]{0,24}', result['product_id'])
            or not re.fullmatch(r'[1-9][0-9]{0,24}', result['draft_id'])
            or (draft.get('store') and draft['store'] != key)):
        return dict(result, reason='尚无明确的平台草稿/商品ID与店铺绑定；发布状态保持未知')
    import weekly_update
    expected = weekly_update.STORES.get(key, {}).get('expected_id')
    if not expected:
        return dict(result, reason='目标店铺未配置，发布状态保持未知')
    root = Path(evidence_root) if evidence_root else store.ROOT / '.state/runtime/publication-check' / uuid.uuid4().hex
    if (product.get('workflow') or {}).get('listingMechanism')=='original-skill-v1':
        import listing_browser
        import listing_browser_publication
        if recover_browser:
            try:listing_browser.ensure_ready(product)
            except ValueError as error:return dict(result,reason=str(error))
        elif listing_browser.status().get('status')!='READY':
            return dict(result,reason='原上品专用浏览器未就绪；请打开专用窗口或点击刷新发布状态恢复连接')
        return read_publication_status(product,lambda target:listing_browser_publication.collect(target,root),expected_account=expected)
    import listing_publication
    return read_publication_status(product, lambda target: listing_publication.collect(target, root),
                                   expected_account=expected)


def skill_contract(skills):
    root=skills/'alibaba-attribute-filler'
    files=[root/name for name in ('SKILL.md','scripts/run_all.cjs','scripts/browser_runner.cjs',
        'scripts/route_category.cjs','scripts/upload_images.cjs','scripts/content_preflight.cjs',
        'assets/_profile.json','subskills/price-filler/scripts/price_calc.cjs')]
    files.extend(sorted((root/'categories').glob('*/config.json')))
    if (root / 'package.json').is_file(): files.append(root / 'package.json')
    # v9.2.38 imports these at runtime. Bind all executable/data dependencies,
    # including the content generators, instead of fingerprinting only entry points.
    for pattern in ('scripts/*.cjs', 'subskills/*/scripts/*.cjs', 'subskills/*/scripts/*.py',
                    'references/company/*.json'):
        files.extend(sorted(root.glob(pattern)))
    files = sorted(set(files))
    contract = {file.relative_to(root).as_posix():hashlib.sha256(file.read_bytes()).hexdigest() for file in files}
    contract['__workbench_contract_version__'] = 'listing-source-v2'
    for file in (Path(__file__), Path(__file__).with_name('listing_runner.cjs'),
                 Path(__file__).with_name('listing_image_evidence.cjs'),
                 Path(__file__).with_name('recruitment_listing_overlay.py'),
                 Path(__file__).with_name('listing_completion.cjs')):
        contract['__workbench__/' + file.name] = hashlib.sha256(file.read_bytes()).hexdigest()
    return contract


@contextmanager
def session_lock(job):
    target = store.STATE / 'browser-write.lock'
    target.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    try:
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError('后台浏览器会话被其他任务占用，请先核对原任务；未自动覆盖锁') from None
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        json.dump({'job': job, 'pid': os.getpid(), 'token': token, 'created': store.now()}, output)
    try:
        yield
    finally:
        try:
            if json.loads(target.read_text(encoding='utf-8')).get('token') == token:
                target.unlink()
        except (OSError, ValueError):
            pass


def export_images(product, root):
    from skill_jobs import artifact
    visual = product['visual']
    images = {row['slot']: row for row in visual['images']}
    if len(images) != len(visual['images']):
        raise ValueError('上品图片槽位重复，不能丢弃或替换已审核产物')
    slots = SLOTS if set(images) == set(SLOTS) else LEGACY_SLOTS if set(images) == set(LEGACY_SLOTS) else None
    if slots is None:
        raise ValueError('上品交接必须包含完整的6主图+12详情，或完整旧版7主图+12详情')
    rows = []
    for slot in slots:
        source = artifact(store.STATE / 'runs' / visual['job'], images[slot]['file'])
        if slot.startswith('m') and slot != 'm7':
            section, relative = 'main', 'upload/main/' + slot + source.suffix.lower()
        elif slot == 'm7':
            # Original uploader recognizes d3@1x as a parameter image. Original d3 is retained.
            section, relative = 'parameters', 'upload/detail/d3@1x' + source.suffix.lower()
        else:
            section, relative = 'detail', 'upload/detail/' + slot + source.suffix.lower()
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        rows.append({'slot': slot, 'section': section, 'file': relative,
                     'sourceHash': hashlib.sha256(source.read_bytes()).hexdigest(),
                     'exportHash': hashlib.sha256(target.read_bytes()).hexdigest()})
    (root / 'upload-map.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    return rows


def validate_receipt(report, readback, key, category, delivery=None):
    if (report.get('status') == 'blocked_critical_transaction_fields'
            and (report.get('save') or {}).get('status') == 'not_saved'):
        errors = report.get('critical_fill_errors') or []
        details = '、'.join(str(row.get('field', '')) + ': ' + str(row.get('error', ''))
                           for row in errors if isinstance(row, dict))[:500]
        raise ValueError('原Skill在保存前阻断，未保存草稿：' + details)
    verified = report.get('post_save_verification') or {}
    if (report.get('status') != 'completed' or verified.get('status') != 'verified'
            or verified.get('missing_required') or verified.get('structure_mismatches')):
        raise ValueError('原Skill保存后字段核验未完整通过，保留草稿结果待核对')
    url = urlsplit(str(readback.get('draft_url', '')))
    if (not readback.get('draft_id') or url.scheme != 'https'
            or not (url.hostname or '').endswith('.alibaba.com') or readback.get('published') is not False
            or readback.get('store') != key or readback.get('actualAccountVerified') is not True
            or str(readback.get('category_id')) != str(category)
            or str(report.get('category_routing', {}).get('selected_cat_id')) != str(category)):
        raise ValueError('草稿实际店铺、类目、身份或链接未通过核验')
    fields = readback.get('fields') or {}
    if not fields or any(not row.get('matched') or not row.get('actual') for row in fields.values()):
        raise ValueError('草稿字段缺少实际回读值或存在差异')
    images = readback.get('image_checks') or []
    if readback.get('acceptancePolicy')=='original-skill-draft-review':
        if (not delivery or readback.get('image_review_required') is not True
                or readback.get('image_readback_verified') is not False
                or len(images)!=len(delivery) or len({r.get('slot') for r in images})!=len(images)):
            raise ValueError('原Skill图片交接或后台终检标记缺失')
        for entry in delivery:
            matching=[row for row in images if row.get('slot')==entry['slot']]
            if (len(matching)!=1 or matching[0].get('uploadInvoked') is not True
                    or matching[0].get('exportHash')!=entry.get('exportHash')
                    or matching[0].get('reviewRequired') is not True):
                raise ValueError('原Skill未完整处理本次本地图片')
        expected_main=sum(row['section']=='main' for row in delivery)
        if (report.get('images',{}).get('main_count')!=expected_main
                or report.get('images',{}).get('detail_count')!=len(delivery)-expected_main
                or report.get('images',{}).get('skipped')):
            raise ValueError('原Skill图片处理数量未通过，不能登记草稿成功')
        return True
    received_slots = {row.get('slot') for row in images}
    slots = (delivery and [row['slot'] for row in delivery]) or (
        SLOTS if received_slots == set(SLOTS) else LEGACY_SLOTS if received_slots == set(LEGACY_SLOTS) else [])
    if not slots or len(images) != len(slots) or received_slots != set(slots) or any(
            not row.get('actual') or row.get('matched') is not True for row in images):
        raise ValueError('图片上传去向尚未按当前套图版本全部回读，不登记完整成功')
    positions = {}
    for slot in slots:
        section = 'parameters' if slot == 'm7' else 'main' if slot.startswith('m') else 'detail'
        positions[slot] = (section, sum(s == section for s, _ in positions.values()))
    for row in images:
        section, index = positions[row['slot']]
        if (row.get('evidenceVersion') != 1 or not row.get('assetId')
                or row.get('assetId') != row.get('expectedAssetId')
                or row.get('section') != section or row.get('index') != index
                or row.get('uploaded') is not True or not row.get('exportHash')):
            raise ValueError('图片缺少文件到asset身份、保存后分区或顺序证据')
        if delivery is not None:
            entry = next((item for item in delivery if item['slot'] == row['slot']), {})
            if row['exportHash'] != entry.get('exportHash'):
                raise ValueError('图片回读与当前审核导出文件哈希不一致')
        if row.get('identityKind') is not None:
            import re
            if (row['identityKind'] not in ('platform-url','platform-asset-id')
                    or not all(re.fullmatch(r'[a-f0-9]{64}', str(row.get(k,''))) for k in ('requestHash','responseHash'))
                    or row.get('groupIndex') is None
                    or row['identityKind']=='platform-url' and row['assetId']!=row['actual']):
                raise ValueError('逐文件上传或实际分区证据缺失')
    if len({row['assetId'] for row in images}) != len(slots):
        raise ValueError('图片asset身份重复，不能证明套图中的每项图片均独立')
    return True


def persist_attempt(job, product, context, root, begin=False):
    """Commit before execute; keep even absent/malformed receipts as uncertain."""
    evidence, errors = {}, []
    for name in ('readback.json', 'reports/run-all-report.json', 'upload-evidence.json'):
        file = root / name
        if file.is_file():
            try:
                value = json.loads(file.read_text(encoding='utf-8-sig'))
                if not isinstance(value, list if name == 'upload-evidence.json' else dict):
                    raise ValueError('invalid evidence structure')
                evidence[name] = value
            except (OSError, ValueError) as error:
                errors.append({'file': name, 'error': type(error).__name__})
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        current = json.loads(c.execute('SELECT data FROM products WHERE id=?', (product['id'],)).fetchone()['data'])
        if begin:
            if current.get('draft') or current.get('draftHistory'):
                raise ValueError('已有草稿线索，先对账，不重复新建')
            if current['revision'] != job['revision']:
                raise ValueError('资料版本已变化，未执行保存')
            current['draft'] = {'job': job['id'], 'revision': job['revision'], 'attempt_id': job['id'],
                'attemptStartedAt': store.now(), 'store': context['store'], 'published': None,
                'readback_verified': False, 'reconciliationRequired': True,
                'evidence_file': 'readback.json', 'run_directory': str(root)}
        clue = current.get('draft')
        if not clue or clue.get('attempt_id') != job['id']:
            clue = next((item for item in current.get('draftHistory', [])
                         if item.get('attempt_id') == job['id']), None)
        if clue and clue.get('attempt_id') == job['id']:
            readback = evidence.get('readback.json', {})
            for key in ('draft_id', 'draft_url'):
                if readback.get(key): clue[key] = readback[key]
            clue.update(evidence=evidence, evidenceErrors=errors, reconciliationRequired=True)
        c.execute('UPDATE products SET data=? WHERE id=?', (json.dumps(current, ensure_ascii=False), product['id']))


def _reconcile_not_saved(job, product, root, skills, report):
    """Only the original immutable script's explicit before-save stop can clear a clue.

    Controller fixes may change their hashes after a failure. Compare every vendor
    source hash to the recorded run instead; this is not platform draft verification.
    """
    draft = product['draft']
    context = json.loads((root/'listing-context.json').read_text(encoding='utf-8'))
    prepared = json.loads((root/'skill-preparation.json').read_text(encoding='utf-8'))
    recorded = json.loads((root/'skill-contract.json').read_text(encoding='utf-8'))
    current_contract = skill_contract(skills)
    vendor = lambda contract: {key:value for key,value in contract.items() if not key.startswith('__')}
    if (recorded.get('__workbench_contract_version__') != 'listing-source-v2'
            or current_contract.get('__workbench_contract_version__') != 'listing-source-v2'
            or not vendor(recorded).get('scripts/run_all.cjs')
            or vendor(recorded) != vendor(current_contract)):
        raise ValueError('原Skill源合同已变化，不能确认原执行未保存')
    if (root.resolve() != (store.STATE/'runs'/job['id']).resolve()
            or job.get('product') != product.get('id')
            or job.get('revision') != product.get('revision')
            or draft.get('job') != job['id'] or draft.get('revision') != job['revision']
            or context.get('listingMechanism') != 'original-skill-v1'
            or (product.get('workflow') or {}).get('listingMechanism') != 'original-skill-v1'
            or context.get('product') != product['id'] or context.get('revision') != job['revision']
            or context.get('store') != product['facts']['store'] or draft.get('store') != context['store']
            or prepared.get('status') != 'READY' or prepared.get('revision') != job['revision']
            or not prepared.get('attributePlanFingerprint')
            or prepared['attributePlanFingerprint'] != product.get('attributePlan', {}).get('fingerprint')
            or not prepared.get('visualJob') or prepared['visualJob'] != product.get('visual', {}).get('job')):
        raise ValueError('未保存对账的任务、产品、版本或资料范围不一致')
    save, verified = report.get('save') or {}, report.get('post_save_verification') or {}
    errors = report.get('critical_fill_errors')
    if (report.get('product_id') != product['id']
            or report.get('status') != 'blocked_critical_transaction_fields'
            or save.get('status') != 'not_saved' or 'button' not in save or save['button'] is not None
            or save.get('published') is not False or save.get('reason') != 'critical_transaction_fill_failed'
            or verified != {'status':'not_run', 'reason':'critical_transaction_fill_failed'}
            or not isinstance(errors, list) or not errors or save.get('errors') != errors
            or any(not isinstance(row, dict) or not row.get('field') or not row.get('error') for row in errors)):
        raise ValueError('缺少原Skill明确保存前阻断的完整证据，保留防重线索')
    def has_save_trace(value):
        if isinstance(value, dict):
            return any((key.replace('_', '').lower() in ('draftid', 'drafturl', 'saveddraftid', 'saveddrafturl', 'itemid', 'readback')
                        or key.replace('_', '').lower() == 'productid' and item != product['id']
                        or key == 'published' and item is True or has_save_trace(item))
                       for key,item in value.items())
        if isinstance(value, str):
            import re
            for address in re.findall(r'https?://[^\s<>"\']+', value):
                try:
                    url = urlsplit(address)
                    if ((url.hostname or '') == 'alibaba.com' or (url.hostname or '').endswith('.alibaba.com')):
                        if any(key.lower() in ('itemid', 'productid', 'draftid')
                               for key,_ in parse_qsl(url.query, keep_blank_values=True)):
                            return True
                except ValueError:
                    pass
        return isinstance(value, list) and any(has_save_trace(item) for item in value)
    evidence = draft.get('evidence') or {}
    if ((root/'readback.json').exists() or 'readback.json' in evidence
            or draft.get('evidenceErrors') or product.get('draftHistory')
            or has_save_trace(draft) or has_save_trace(report)
            or evidence.get('reports/run-all-report.json') != report):
        raise ValueError('发现保存/回读线索或证据不一致，未解除防重')
    proof = {'reportSha256':hashlib.sha256((root/'reports/run-all-report.json').read_bytes()).hexdigest(),
             'vendorContractVerified':True, 'controllerSourceChanged':recorded != current_contract,
             'scope':'original-script-before-save'}
    with store.db() as connection:
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('SELECT data FROM products WHERE id=?', (product['id'],)).fetchone()
        current = json.loads(row['data']) if row else {}
        if (current.get('revision') != job['revision'] or current.get('draft') != draft
                or current.get('draftHistory')
                or current.get('facts', {}).get('store') != context['store']
                or current.get('workflow', {}).get('listingMechanism') != 'original-skill-v1'
                or current.get('attributePlan', {}).get('fingerprint') != prepared['attributePlanFingerprint']
                or current.get('visual', {}).get('job') != prepared['visualJob']):
            raise ValueError('产品或保存尝试已变化，未解除当前防重线索')
        history = current.setdefault('listingReconciliations', [])
        history.append({'job':job['id'], 'revision':job['revision'], 'status':'no_save_verified',
                        'checkedAt':store.now(), 'evidence':proof, 'attempt':current.pop('draft')})
        connection.execute('UPDATE products SET data=? WHERE id=?', (json.dumps(current, ensure_ascii=False), product['id']))
    return {'status':'no_save_verified', 'reconciliationRequired':False, 'evidence':proof,
            'next':'原Skill明确在保存前阻断；原诊断已保留，可修复原因后另行启动。未核验平台草稿或发布状态。'}


def reconcile_saved(job, product, root, skills):
    """Read local evidence only; saved/ambiguous attempts keep their original guard."""
    draft = product.get('draft') or {}
    if draft.get('attempt_id') != job['id'] or Path(draft.get('run_directory', '')) != root:
        raise ValueError('对账任务或目录与保存尝试不一致')
    report = json.loads((root / 'reports/run-all-report.json').read_text(encoding='utf-8-sig'))
    if report.get('status') == 'blocked_critical_transaction_fields':
        return _reconcile_not_saved(job, product, root, skills, report)
    if skill_contract(skills) != product['attributePlan'].get('skillContract'):
        raise ValueError('原Skill配置已变化，需重新核对')
    readback = json.loads((root / 'readback.json').read_text(encoding='utf-8-sig'))
    category = json.loads((root / 'listing-preflight.json').read_text(encoding='utf-8'))['category']
    delivery = json.loads((root / 'upload-map.json').read_text(encoding='utf-8'))
    validate_receipt(report, readback, product['facts']['store'], category, delivery)
    return {'status': 'evidence_validated', 'readback': readback, 'reconciliationRequired': True,
            'next': '需核对当前平台权威状态；本地证据检查不自动解除防重或重新执行保存'}


def refresh_saved(job, product, root, skills):
    """Reopen only a proven existing draft; leave the guard until the API commits."""
    draft = product.get('draft') or {}
    context = json.loads((root/'listing-context.json').read_text(encoding='utf-8'))
    prepared = json.loads((root/'skill-preparation.json').read_text(encoding='utf-8'))
    report = json.loads((root/'reports/run-all-report.json').read_text(encoding='utf-8-sig'))
    original = json.loads((root/'readback.json').read_text(encoding='utf-8-sig'))
    recorded = json.loads((root/'skill-contract.json').read_text(encoding='utf-8'))
    contract = skill_contract(skills)
    vendor = lambda value: {key:val for key,val in value.items() if not key.startswith('__')}
    if (recorded.get('__workbench_contract_version__') != 'listing-source-v2'
            or contract.get('__workbench_contract_version__') != 'listing-source-v2'
            or not vendor(recorded).get('scripts/run_all.cjs') or vendor(recorded) != vendor(contract)):
        raise ValueError('原Skill源合同已变化，不能回读该次保存结果')
    if (root.resolve() != (store.STATE/'runs'/job['id']).resolve()
            or job.get('product') != product.get('id') or job.get('revision') != product.get('revision')
            or draft.get('attempt_id') != job['id'] or draft.get('job') != job['id']
            or draft.get('revision') != job['revision'] or Path(draft.get('run_directory', '')) != root
            or context.get('listingMechanism') != 'original-skill-v1'
            or product.get('workflow', {}).get('listingMechanism') != 'original-skill-v1'
            or context.get('product') != product['id'] or context.get('revision') != job['revision']
            or draft.get('store') != context.get('store') or context.get('store') != product['facts']['store']
            or prepared.get('status') != 'READY' or prepared.get('revision') != job['revision']
            or not prepared.get('attributePlanFingerprint')
            or prepared['attributePlanFingerprint'] != product.get('attributePlan', {}).get('fingerprint')
            or not prepared.get('visualJob') or prepared['visualJob'] != product.get('visual', {}).get('job')):
        raise ValueError('已存草稿回读的任务、版本、店铺或资料范围不一致')
    import re
    draft_id = str(draft.get('draft_id') or '')
    def valid_url(address):
        try:
            parsed = urlsplit(str(address))
            pairs = parse_qsl(parsed.query, keep_blank_values=True)
            ids = [value for key,value in pairs if key in ('itemId', 'productId')]
            return (parsed.scheme == 'https' and parsed.hostname == 'post.alibaba.com'
                    and parsed.port in (None,443) and not parsed.username and not parsed.password
                    and parsed.path == '/product/publish.htm' and not parsed.fragment
                    and ids == [draft_id] and all(value == 'draft' for key,value in pairs if key == 'pubAction'))
        except ValueError:
            return False
    verified = report.get('post_save_verification') or {}
    save = report.get('save') or {}
    evidence = draft.get('evidence') or {}
    if (not re.fullmatch(r'[1-9][0-9]{0,24}', draft_id) or not valid_url(draft.get('draft_url'))
            or original.get('draft_id') != draft_id or original.get('draft_url') != draft.get('draft_url')
            or original.get('store') != context['store'] or original.get('published') is not False
            or original.get('actualAccountVerified') is not True
            or report.get('product_id') != product['id'] or report.get('status') != 'completed'
            or save.get('status') != 'draft_saved' or not save.get('button') or save.get('published') is not False
            or verified.get('status') != 'verified' or not valid_url(verified.get('resolved_draft_url'))
            or evidence.get('reports/run-all-report.json') != report or evidence.get('readback.json') != original
            or draft.get('evidenceErrors')):
        raise ValueError('缺少本次已保存草稿的明确ID、链接与原始验收证据；不会新建或再次保存')
    def check_scope():
        with store.db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT data FROM products WHERE id=?', (product['id'],)).fetchone()
            current = json.loads(row['data']) if row else {}
            if (current.get('revision') != job['revision'] or current.get('draft') != draft
                    or current.get('facts', {}).get('store') != context['store']
                    or current.get('attributePlan', {}).get('fingerprint') != prepared['attributePlanFingerprint']
                    or current.get('visual', {}).get('job') != prepared['visualJob']):
                raise ValueError('产品或已有草稿已变化，保留原防重线索')
    check_scope()
    import listing_browser
    with session_lock(job['id']):
        listing_browser.ensure_ready(product)
        target = {'product':product['id'], 'revision':job['revision'], 'store':context['store'],
                  'draft_id':draft_id, 'draft_url':draft['draft_url']}
        (root/'readback-target.json').write_text(json.dumps(target, ensure_ascii=False, indent=2), encoding='utf-8')
        paths = [root/'readback-refresh.json', root/'readback-refresh-report.json']
        previous = [path.stat().st_mtime_ns if path.exists() else None for path in paths]
        with (root/'listing-readback.log').open('wb') as log:
            result = subprocess.run(command(root, skills, 'readback'), stdout=log, stderr=log,
                                    env=environment(), timeout=300,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode or any(not path.is_file() or path.stat().st_mtime_ns == prior
                                    for path,prior in zip(paths,previous)):
            raise ValueError('已有草稿只读回读失败或未产生新证据；防重线索保留')
        refreshed, refresh_report = [json.loads(path.read_text(encoding='utf-8-sig')) for path in paths]
        category = json.loads((root/'listing-preflight.json').read_text(encoding='utf-8'))['category']
        delivery = json.loads((root/'upload-map.json').read_text(encoding='utf-8'))
        if (refreshed.get('draft_id') != draft_id or not valid_url(refreshed.get('draft_url'))
                or refresh_report.get('product_id') != product['id']):
            raise ValueError('只读回读返回了其他草稿，未解除原防重')
        validate_receipt(refresh_report, refreshed, context['store'], category, delivery)
        if skill_contract(skills) != contract:
            raise ValueError('回读期间执行源码变化，保留草稿待核对')
        check_scope()
    return {'status':'completed', 'store':context['store'], 'expected_store':context['store'],
            'draft_id':draft_id, 'draft_url':refreshed['draft_url'], 'published':False,
            'readback_verified':True, 'evidence_file':'readback-refresh.json', 'fields':refreshed['fields'],
            'readback_scope':['draft_id','store','category','fields'], 'category_id':category,
            'image_review_required':refreshed.get('image_review_required',False),
            'image_readback_verified':refreshed.get('image_readback_verified',True),
            'intentional_blank_fields':refreshed.get('intentional_blank_fields',[]),
            'warnings':refreshed.get('warnings',[]), 'image_checks':refreshed['image_checks']}


def environment():
    env = dict(os.environ)
    for key in ('SKIP_POST_VERIFY', 'SKIP_IMAGE_UPLOAD', 'SKIP_PRICE_FILL', 'MANIFEST', 'IMG_DIR'):
        env.pop(key, None)
    approved_modules = os.environ.get('WORKBENCH_NODE_MODULES', '').strip()
    if not approved_modules:
        bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'
        approved_modules = str(bundled) if bundled.is_dir() else ''
    if approved_modules:
        env['NODE_PATH'] = approved_modules
    env.update(PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1', SKIP_BROWSER_CLOSE='1',
               CODEX_PYTHON=os.environ.get('WORKBENCH_PYTHON', sys.executable))
    return env


def command(root, skills, mode):
    executable = shutil.which('node')
    if not executable:
        raise ValueError('原上品Skill需要本机Node执行器')
    return [executable, str(store.ROOT / 'listing_runner.cjs'), mode, str(root), str(skills / 'alibaba-attribute-filler')]


def prepare_content(root, skills, original_flow=False):
    """Original content-only entry: never connects to a browser or saves a draft."""
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8-sig'))
    normalized = root / 'reports' / (manifest['product_id'] + '-fill-manifest.json')
    audit = root / 'reports' / (manifest['product_id'] + '-fill-content-audit.json')
    # A failed retry must not reinstall a previous attempt's normalized content.
    for report in (normalized, audit):
        report.unlink(missing_ok=True)
    with (root / 'content-preflight.log').open('wb') as log:
        result = subprocess.run(command(root, skills, 'content'), stdout=log, stderr=log, env=environment(),
                                timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if not normalized.is_file() or not audit.is_file():
        return manifest, ['原Skill内容预检未交回可用报告，请查看任务私有日志']
    data = json.loads(normalized.read_text(encoding='utf-8-sig'))
    data = data[0] if isinstance(data, list) else data
    review = json.loads(audit.read_text(encoding='utf-8-sig'))
    problems = [str(row.get('message', row))[:300] for row in review.get('blockers', [])]
    if not original_flow:
        for key in data.get('_adapter_effective_defaults', {}):
            problems.append('原Skill隐式默认字段需核验来源：' + str(key))
    if result.returncode and not problems:
        problems.append('原Skill内容检查异常，需核对后确认')
    return data, problems


def prepare_original_skill(product,root,skills):
    """Apply only marked recruitment fields, then hand content to the original Skill."""
    import topic_workflow
    import recruitment_listing_overlay
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    proposal=product.get('attributePlan') or {}
    content=product.get('listingContent') or {}
    if content and (content.get('revision')!=product['revision'] or content.get('attributePlanFingerprint')!=proposal.get('fingerprint')):
        raise ValueError('上品补全资料已过期，请按当前属性方案重新准备')
    manifest=json.loads(json.dumps(content.get('manifest') or proposal.get('manifest') or {}))
    if not isinstance(manifest.get('fields'),dict):raise ValueError('缺少原Skill格式的属性方案')
    workflow=product.get('workflow') or {}
    allow_blank_net=workflow.get('listingMechanism')=='original-skill-v1' and workflow.get('allowMissingNetWeight') is True
    if allow_blank_net:manifest['fields']['net_weight']=''
    manifest['product_id']=product['id']
    (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
    checked=subprocess.run(command(root,skills,'inspect'),capture_output=True,env=environment(),timeout=30,
                           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if checked.returncode:raise ValueError('原Skill类目读取未完成')
    routing=json.loads((root/'skill-routing.json').read_text(encoding='utf-8'))
    handoff=topic_workflow.handoff(product)
    expected=[str(v) for row in (handoff or {}).get('requirements',[]) if row.get('kind')=='category' for v in row.get('expected',[])]
    categories=routing['categories'];selected=routing['route']['category'];override=None
    candidates=[key for key,info in categories.items() if str(info['catId']) in expected]
    if len(candidates)==1:
        selected=candidates[0]
        override={'category':selected,'categoryId':str(categories[selected]['catId']),'source':'recruitment-requirement'}
    config=categories[selected]['config'];category=str(categories[selected]['catId'])
    overlay=recruitment_listing_overlay.compose(manifest,handoff,category,category_config=config)
    manifest=overlay['manifest']
    context={'listingMechanism':'original-skill-v1','recruitmentMatchPolicy':'visual-reference',
             'allowMissingNetWeight':allow_blank_net,
             'recruitment':handoff,'categoryOverride':override,'store':product['facts'].get('store'),
             'product':product['id'],'revision':product['revision']}
    (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (root/'listing-context.json').write_text(json.dumps(context,ensure_ascii=False,indent=2),encoding='utf-8')
    (root/'recruitment-overlay.json').write_text(json.dumps(overlay,ensure_ascii=False,indent=2),encoding='utf-8')
    delivery=export_images(product,root)
    generated,gaps=prepare_content(root,skills,original_flow=True)
    coverage_path=root/'listing-content-coverage.json'
    coverage=json.loads(coverage_path.read_text(encoding='utf-8')) if coverage_path.is_file() else None
    if not coverage:gaps.append('原Skill完整内容覆盖检查未返回')
    (root/'manifest.json').write_text(json.dumps(generated,ensure_ascii=False,indent=2),encoding='utf-8')
    pending=list(overlay['pending'])
    for row in overlay['field_replacements']:
        if row['field']=='dosage_form' and product.get('heroApproval'):
            def form(value):
                value=''.join(str(value or '').lower().split())
                return 'powder' if value in ('powder','instantpowder','粉剂','粉末') else value
            if form(row['value'])!=form(product.get('facts',{}).get('form')):
                pending.append({'name':row['name'],'expected':[row['value']],'code':'approved_hero_form_conflict'})
    if expected and not overlay['category_constraint']['matched']:pending.append({'name':'类目','expected':expected,'code':'category_unavailable'})
    status='BLOCKED' if gaps or pending else 'READY'
    rows=[{'key':row['field'],'from':row.get('previous'),'to':row['value'],'requirement':row.get('name'),'fieldId':row.get('fieldId'),'optionId':row.get('optionId'),'status':'DESIGN'} for row in overlay['field_replacements']]
    result={'revision':product['revision'],'status':status,'images':len(delivery),
            'attributePlanFingerprint':proposal.get('fingerprint'),
            'visualJob':(product.get('visual') or {}).get('job'),
            'message':'原Skill内容预检完成；仅覆盖征品标出属性，图片由原脚本处理' if status=='READY' else '原Skill预检已执行，具体未通过项已列出；无需独立CDN流程',
            'content_preflight':{'status':'PASS' if not gaps else 'BLOCKED','blockingDiagnostics':gaps},
            'field_replacements':rows,'pending_requirements':pending,'category_id':category,
            'content_coverage':coverage,
            'draftSaved':False,'published':False,'checkedAt':store.now()}
    if allow_blank_net:
        result['allowMissingNetWeight']=True
        result['message']+='；用户要求净重留空，后台是否允许保存尚待实际校验'
    (root/'skill-preparation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def persist_skill_preparation(product, result):
    """Expose only the current preparation scope; preserve all other product data."""
    with store.db() as connection:
        connection.execute('BEGIN IMMEDIATE')
        row=connection.execute('SELECT data FROM products WHERE id=?',(product['id'],)).fetchone()
        if row is None:raise ValueError('产品档案已变化，原Skill预检保留但未回填')
        current=json.loads(row['data'])
        if current['revision']!=product['revision']:
            raise ValueError('产品资料已变化，原Skill预检保留但未覆盖当前档案')
        if ((current.get('attributePlan') or {}).get('fingerprint')!=(product.get('attributePlan') or {}).get('fingerprint')
                or (current.get('visual') or {}).get('job')!=(product.get('visual') or {}).get('job')):
            raise ValueError('属性方案或图片已变化，原Skill预检保留但未覆盖当前档案')
        current['listingSkill']=result
        connection.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(current,ensure_ascii=False),product['id']))
    return current


def save_listing_content(product, manifest, sources):
    """Listing-only completion stays separate from approved image parameters."""
    import attribute_plan
    normalized=attribute_plan.normalize(manifest,sources,[])
    if normalized['unresolved']:raise ValueError('上品补全字段必须记录来源：'+'、'.join(normalized['unresolved']))
    base=product.get('attributePlan') or {}
    for key in ('dosage_form','protein_per_serving','benefits','shelf_life'):
        if normalized['manifest']['fields'].get(key)!=(base.get('manifest') or {}).get('fields',{}).get(key):
            raise ValueError('上品补全不能更改已确认的征品参数：'+key)
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        current=json.loads(c.execute('SELECT data FROM products WHERE id=?',(product['id'],)).fetchone()['data'])
        if current['revision']!=product['revision'] or current.get('attributePlan',{}).get('fingerprint')!=base.get('fingerprint'):
            raise ValueError('产品资料已变化，请刷新')
        current['listingContent']={**normalized,'revision':product['revision'],'attributePlanFingerprint':base.get('fingerprint'),'created':store.now()}
        c.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(current,ensure_ascii=False),product['id']))
    return current


def complete_saved_draft(product, root, skills):
    """Explicitly fill the same saved draft through original Skill functions."""
    import weekly_update
    import listing_browser
    root=Path(root);draft=product.get('draft') or {}
    if (product.get('workflow') or {}).get('listingMechanism')!='original-skill-v1' or not draft.get('draft_id') or draft.get('store')!=product['facts'].get('store') or draft.get('revision')!=product['revision']:
        raise ValueError('需要当前版本、同店铺的原Skill已保存草稿')
    if any(j.get('product')==product['id'] and j.get('status') in ('QUEUED','RUNNING') for j in store.records('jobs')):
        raise ValueError('当前产品仍有活动任务，请结束后补全草稿')
    prepared=prepare_original_skill(product,root,skills)
    persist_skill_preparation(product,prepared)
    if prepared['status']!='READY':raise ValueError('完整资料预检未通过：'+'、'.join(prepared['content_preflight']['blockingDiagnostics']))
    context=json.loads((root/'listing-context.json').read_text(encoding='utf-8'))
    context['expectedAccount']=str(weekly_update.STORES[product['facts']['store']]['expected_id'])
    (root/'listing-context.json').write_text(json.dumps(context,ensure_ascii=False),encoding='utf-8')
    target={'product':product['id'],'revision':product['revision'],'store':product['facts']['store'],'draft_id':str(draft['draft_id']),
            'draft_url':'https://post.alibaba.com/product/publish.htm?itemId='+str(draft['draft_id'])+'&pubAction=draft'}
    (root/'completion-target.json').write_text(json.dumps(target),encoding='utf-8')
    contract=skill_contract(skills)
    with session_lock('complete-'+root.name):
        listing_browser.ensure_ready(product)
        with (root/'completion.log').open('wb') as log:
            done=subprocess.run(command(root,skills,'complete'),stdout=log,stderr=log,env=environment(),timeout=900,
                                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),stdin=subprocess.DEVNULL)
    report_path=root/'completion-report.json'
    report=json.loads(report_path.read_text(encoding='utf-8')) if report_path.is_file() else {}
    if done.returncode or report.get('status')!='completed':
        raise ValueError('原Skill草稿补全未通过：'+str(report.get('error') or '请查看任务日志')[:250])
    if report.get('draft_id')!=str(draft['draft_id']) or report.get('published') is not False or skill_contract(skills)!=contract:
        raise ValueError('草稿补全目标或执行版本变化，结果保留待核验')
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        current=json.loads(c.execute('SELECT data FROM products WHERE id=?',(product['id'],)).fetchone()['data'])
        if current['revision']!=product['revision'] or current.get('draft',{}).get('draft_id')!=draft['draft_id'] or current.get('listingContent')!=product.get('listingContent'):
            raise ValueError('补全期间产品或草稿变化，结果保留未覆盖')
        current['draft'].update(fields=report['fieldsReadback'],content_coverage=report['coverage'],content_readback_verified=True,
            completion_evidence=str(report_path.relative_to(store.STATE)),completedAt=store.now(),readback_verified=True)
        current['draft']['warnings']=[w for w in current['draft'].get('warnings',[]) if '是否允许保存尚待' not in w]
        current['events'].append({'time':store.now(),'message':'原Skill完整属性、10自定义属性、8FAQ和5卖点已保存至原草稿并回读；图片沿用，未发布'})
        c.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(current,ensure_ascii=False),product['id']))
    return current


def run(job, product, root, skills):
    import attribute_plan
    import weekly_update
    original_flow=(product.get('workflow') or {}).get('listingMechanism')=='original-skill-v1'
    if not original_flow and attribute_plan.blockers(product):
        raise ValueError('请先准备并确认当前新品属性方案')
    contract=skill_contract(skills)
    if not original_flow and product['attributePlan'].get('skillContract')!=contract:
        raise ValueError('原上品Skill或类目配置已变化，请重新准备并审核属性方案')
    if product.get('draft') or product.get('draftHistory'):
        raise ValueError('已有草稿线索，先回读或更新，不重复新建')
    expected = weekly_update.STORES[product['facts']['store']]['expected_id']
    root.mkdir(parents=True, exist_ok=True)
    if original_flow:
        prepared=prepare_original_skill(product,root,skills)
        persist_skill_preparation(product,prepared)
        if prepared['status']!='READY':
            issues=prepared['content_preflight']['blockingDiagnostics']+[str(row.get('name') or row.get('code')) for row in prepared['pending_requirements']]
            raise ValueError('原Skill上品预检未通过：'+'、'.join(issues)[:300])
        prior_context=json.loads((root/'listing-context.json').read_text(encoding='utf-8'))
    else:
        manifest = json.loads(json.dumps(product['attributePlan']['manifest']))
        manifest['product_id'] = product['id']
        (root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        prior_context={}
    import topic_workflow
    context = {**prior_context,'store': product['facts']['store'], 'expectedAccount': str(expected),
               'revision': product['revision'], 'product': product['id'],
               'recruitmentMatchPolicy': 'visual-reference',
               'recruitment': topic_workflow.handoff(product)}
    (root / 'listing-context.json').write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding='utf-8')
    (root / 'skill-contract.json').write_text(json.dumps(contract,indent=2),encoding='utf-8')
    delivery = export_images(product, root)
    if not original_flow:
        import bridge_catalog
        bridge = bridge_catalog.current_bridge()
    with session_lock(job['id']):
        if not original_flow:weekly_update.require_identity(bridge, root / 'identity.json', expected)
        checked = subprocess.run(command(root, skills, 'preflight'), capture_output=True, encoding='utf-8',
                                 errors='replace', timeout=30, env=environment(),
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if checked.returncode:
            report = root / 'listing-preflight.json'
            info = json.loads(report.read_text(encoding='utf-8')) if report.is_file() else {}
            raise ValueError('上品预检未通过：' + '、'.join(info.get('blockers', ['类目/运行环境待核对']))[:200])
        if original_flow:
            import listing_browser
            listing_browser.ensure_ready(product)
        persist_attempt(job, product, context, root, begin=True)
        store.job_update(job['id'], recoveryRequired=True, progress='保存尝试已登记；异常时必须先对账，禁止重复新建')
        try:
            with (root / 'listing-executor.log').open('wb') as log:
                result = subprocess.run(command(root, skills, 'execute'), stdout=log, stderr=log, env=environment(),
                                        timeout=1800, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if not original_flow:weekly_update.require_identity(bridge, root / 'identity-after.json', expected)
        finally:
            persist_attempt(job, product, context, root)
    report_file, receipt_file = root / 'reports/run-all-report.json', root / 'readback.json'
    report = json.loads(report_file.read_text(encoding='utf-8-sig')) if report_file.is_file() else {}
    readback = json.loads(receipt_file.read_text(encoding='utf-8-sig')) if receipt_file.is_file() else {}
    category = json.loads((root / 'listing-preflight.json').read_text(encoding='utf-8'))['category']
    validate_receipt(report, readback, context['store'], category, delivery)
    if skill_contract(skills)!=contract:
        raise ValueError('执行期间原Skill配置变化，草稿保留待重新核验')
    if result.returncode:
        raise ValueError('原上品执行器异常结束，实际结果保留待核验')
    store.job_update(job['id'], recoveryRequired=False)
    return {'status': 'completed', 'store': context['store'], 'expected_store': context['store'],
            'draft_id': readback['draft_id'], 'draft_url': readback['draft_url'], 'published': False,
            'readback_verified': True, 'evidence_file': 'readback.json', 'fields': readback['fields'],
            'readback_scope':['draft_id','store','category','fields'],
            'image_review_required':readback.get('image_review_required',False),
            'image_readback_verified':readback.get('image_readback_verified',True),
            'intentional_blank_fields':readback.get('intentional_blank_fields',[]),
            'warnings':readback.get('warnings',[]),
            'image_checks': readback['image_checks'], 'category_id': category}
