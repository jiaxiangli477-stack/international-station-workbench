"""Proposed new-product attributes: provenance, immutable review, no platform writes."""
import hashlib
import json
import re
import task_store as store
from project_paths import skill_root


def fingerprint(plan):
    return hashlib.sha256(json.dumps({k: plan.get(k) for k in ('manifest', 'field_sources', 'unresolved','skillContract')},
                                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def artifact_matches(product, artifact):
    """Legacy products without a proposal keep their existing revision contract."""
    plan = product.get('attributePlan')
    if not plan:
        return True
    return bool(plan.get('revision') == product['revision']
                and plan.get('fingerprint') == fingerprint(plan)
                and artifact.get('attributePlanFingerprint') == plan.get('fingerprint')
                and not artifact.get('needsRegeneration'))


def normalize(manifest, sources, unresolved):
    if not isinstance(manifest, dict) or not isinstance(manifest.get('fields'), dict):
        raise ValueError('属性方案缺少原Skill格式的fields')
    if len(json.dumps(manifest, ensure_ascii=False)) > 50000:
        raise ValueError('属性方案过大')
    if not manifest['fields'].get('product_name'):
        raise ValueError('属性方案缺少产品标题')
    if not isinstance(sources, dict) or not isinstance(unresolved, list):
        raise ValueError('属性方案缺少来源或未解决项清单')
    missing = []
    for key, value in manifest['fields'].items():
        if not re.fullmatch(r'[a-zA-Z0-9_]{1,80}', key) or key in ('__proto__','constructor','prototype'):
            raise ValueError('属性字段名称无效')
        source = sources.get('fields.' + key, {})
        if value not in ('', None, []) and (not isinstance(source, dict) or not source.get('source')
                or source.get('kind') not in ('REFERENCE', 'DESIGN', 'CONFIRMED')):
            missing.append('字段缺来源：' + key)
    return {'manifest': json.loads(json.dumps(manifest)), 'field_sources': sources,
            'unresolved': list(dict.fromkeys([str(x)[:300] for x in unresolved] + missing))}


def install(product, job, root, result):
    from skill_jobs import artifact
    if result.get('status') != 'completed':
        raise ValueError('属性方案尚未完成：' + str(result.get('reason', '缺少候选资料'))[:180])
    manifest = json.loads(artifact(root, result.get('manifest_file', '')).read_text(encoding='utf-8-sig'))
    if isinstance(manifest, list):
        if len(manifest) != 1 or not isinstance(manifest[0], dict):
            raise ValueError('属性方案manifest数组必须仅包含一个产品对象')
        manifest = manifest[0]
    if not isinstance(manifest, dict):
        raise ValueError('属性方案manifest必须为产品对象或单项产品对象数组')
    if job.get('workflowContinuation'):
        SKILLS = skill_root('alibaba-attribute-filler').parent
        import listing_adapter
        manifest['product_id'] = product['id']
        (root / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        manifest, problems = listing_adapter.prepare_content(root, SKILLS)
        result['unresolved'] = list(result.get('unresolved') or []) + problems
        sources = result.setdefault('field_sources', {})
        for key, value in manifest.get('fields', {}).items():
            if value not in ('', None, []):
                sources.setdefault('fields.' + key, {'kind': 'DESIGN', 'source': '原Skill规范化建议，待确认，非实测'})
    proposal = normalize(manifest, result.get('field_sources'), result.get('unresolved'))
    proposal.update(job=job['id'], revision=job['revision'], proposed=True, created=store.now())
    SKILLS = skill_root('alibaba-attribute-filler').parent
    import listing_adapter
    proposal['skillContract']=listing_adapter.skill_contract(SKILLS)
    proposal['fingerprint'] = fingerprint(proposal)
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        p = json.loads(c.execute('SELECT data FROM products WHERE id=?', (product['id'],)).fetchone()['data'])
        if p['revision'] != job['revision']:
            raise ValueError('产品资料已变化，属性方案保留但不能交接')
        p.update(attributePlan=proposal, approvedAttributes=None)
        p['events'].append({'time': store.now(), 'message': '新品属性方案已准备，参考值与拟采用值待审核'})
        c.execute('UPDATE products SET data=? WHERE id=?', (json.dumps(p, ensure_ascii=False), p['id']))
    return p


def edit(product_id, revision, manifest, sources, unresolved, expected_fingerprint):
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        p = json.loads(c.execute('SELECT data FROM products WHERE id=?', (product_id,)).fetchone()['data'])
        if (p['revision'] != revision or not p.get('attributePlan')
                or p['attributePlan'].get('fingerprint')!=expected_fingerprint):
            raise ValueError('属性方案或产品资料已变化，请刷新')
        if not isinstance(sources,dict) or not isinstance(manifest,dict):raise ValueError('属性方案格式无效')
        sources=json.loads(json.dumps(sources))
        for key,value in manifest.get('fields',{}).items():
            if value!=p['attributePlan']['manifest']['fields'].get(key):
                sources['fields.'+key]={'kind':'DESIGN','source':'用户修改拟采用的新品参数；原参考不证明修改后的值'}
        proposed = normalize(manifest, sources, unresolved)
        old_plan = p['attributePlan']
        next_plan = dict(old_plan, **proposed)
        next_fingerprint = fingerprint(next_plan)
        if next_fingerprint != old_plan.get('fingerprint'):
            # Serialize with enqueue/claim/commit so an executor cannot race an edit.
            for row in c.execute("SELECT data FROM jobs WHERE status IN ('QUEUED','RUNNING')"):
                if json.loads(row['data']).get('product') == product_id:
                    raise ValueError('该产品存在活动执行任务，请等待执行结束并核对产物后修改属性方案')
            old_manifest = old_plan.get('manifest') or {}
            changed = {key for key in set(old_manifest) | set(manifest)
                       if old_manifest.get(key) != manifest.get(key)}
            commerce_only = bool(changed) and changed <= {'pricing', 'lead_time', 'logistics'}
            invalidated = False
            for asset_key, approval_key in (('packaging', 'approvedPackaging'), ('visual', 'approvedVisual'),
                                            ('visualPartial', 'approvedVisual'), ('visualPending', 'approvedVisual')):
                asset = p.get(asset_key)
                if not asset:
                    continue
                dependencies = asset.get('attributeDependencies')
                independent = (commerce_only and isinstance(dependencies, list)
                               and all(isinstance(key, str) and key.split('.')[0] in set(old_manifest) | set(manifest)
                                       for key in dependencies)
                               and not any(key == path or key.startswith(path + '.')
                                           for key in dependencies for path in changed))
                if independent and artifact_matches(p, asset):
                    # Rebind only when the artifact explicitly excludes the changed inputs.
                    asset['attributePlanFingerprint'] = next_fingerprint
                else:
                    asset['needsRegeneration'] = True
                    p[approval_key] = None
                    invalidated = True
            if invalidated:
                if p.get('workflow') and p['workflow'].get('status') != 'STOPPED':
                    p['workflow'].update(status='STALE', message='新品属性变化影响包装或套图，需重新预检并明确继续；未自动再次生图')
                p['events'].append({'time':store.now(),'message':'属性方案变化，相关包装及套图审核已失效，需重新预检'})
            if (p.get('workflow') or {}).get('approvalPolicy') == 'single-hero-v1':
                p['heroApproval'] = None
                if p.get('hero'): p['hero']['needsRegeneration'] = True
                if p['workflow'].get('status') != 'STOPPED':
                    p['workflow'].update(status='STALE', message='属性方案变化，首图确认已失效，需重新预检并确认正式m1')
        p['attributePlan'].update(proposed, updated=store.now())
        p['attributePlan']['fingerprint'] = next_fingerprint
        p['approvedAttributes'] = None
        c.execute('UPDATE products SET data=? WHERE id=?', (json.dumps(p, ensure_ascii=False), product_id))
    return p


def blockers(product):
    plan = product.get('attributePlan') or {}
    if plan.get('revision') != product['revision']:
        return ['当前版本的新品属性方案']
    gaps = list(plan.get('unresolved') or [])
    if product.get('approvedAttributes') != plan.get('fingerprint'):
        gaps.insert(0, '新品属性方案审核')
    if not product['facts'].get('store'):
        gaps.append('草稿目标店铺')
    return list(dict.fromkeys(gaps))


def approve(product_id, revision, job, expected_fingerprint, acknowledge):
    if acknowledge is not True:
        raise ValueError('请确认本次拟采用的新品参数及资料来源；参考不是已验证产品事实')
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        p = json.loads(c.execute('SELECT data FROM products WHERE id=?', (product_id,)).fetchone()['data'])
        plan = p.get('attributePlan') or {}
        if (p['revision'] != revision or plan.get('revision') != revision or plan.get('job') != job
                or fingerprint(plan) != expected_fingerprint or plan.get('fingerprint') != expected_fingerprint):
            raise ValueError('属性方案已变化，请重新查看后审核')
        if plan.get('unresolved'):
            raise ValueError('请先处理属性方案未解决项：' + '、'.join(plan['unresolved'])[:200])
        SKILLS = skill_root('alibaba-attribute-filler').parent
        import listing_adapter
        if plan.get('skillContract')!=listing_adapter.skill_contract(SKILLS):
            raise ValueError('原Skill或类目配置已变化，请重新准备方案后审核')
        import weekly_update
        if p['facts'].get('store') not in weekly_update.STORES:
            raise ValueError('请先选择已绑定的草稿目标店铺')
        p.update(approvedAttributes=expected_fingerprint)
        plan.update(approvedAt=store.now(), proposed=False)
        p['events'].append({'time': store.now(), 'message': '人工确认新品属性方案；未将参考值改写为实测事实'})
        c.execute('UPDATE products SET data=? WHERE id=?', (json.dumps(p, ensure_ascii=False), product_id))
    return p
