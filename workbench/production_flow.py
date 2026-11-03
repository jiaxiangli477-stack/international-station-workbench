"""One draft-only workflow for direct, selection and recruitment new products."""
import json
import os
import task_store as store
import attribute_plan
import single_approval_flow

TERMINAL = {'STOPPED', 'STALE', 'NEEDS_ATTENTION', 'DRAFT_SAVED', 'VISUALS_READY'}
FRESH_VISUAL_CONTRACT = 'six-main-twelve-detail-v1'
REFERENCE_SAMPLE_VISUAL_CONTRACT = 'six-main-twelve-detail-reference-sample-v1'
FRESH_VISUAL_SLOTS = {f'm{i}' for i in range(1,7)} | {'d1','d2','d3','d4','df','d5','d6','dfac','d7','dc','drev','d9'}
LEGACY_VISUAL_SLOTS = {f'm{i}' for i in range(1,8)} | {'d1','d2','d3','d4','df','d5','d6','dfac','d7','dc','drev','d9'}
WAITING = {'packaging_review': 'WAITING_PACKAGING_REVIEW', 'visual_review': 'WAITING_VISUAL_REVIEW',
           'hero_review': 'WAITING_HERO_REVIEW',
           'attributes_review': 'WAITING_ATTRIBUTES_REVIEW', 'input': 'NEEDS_INPUT'}


def source(product):
    return 'selection' if product['source'].startswith('selection:') else 'recruitment' if product.get('recruitment') or product['source'].startswith('topic:') else 'new'


def plan(product, target=None):
    import skill_jobs
    target = target or (product.get('workflow') or {}).get('target') or 'DRAFT'
    revision = product['revision']
    draft = product.get('draft') or {}
    if draft.get('readback_verified'):
        return {'next': 'done', 'gaps': [], 'status': 'DRAFT_SAVED', 'message': '草稿已保存并回读，不重复创建'}
    if draft or any(j.get('product') == product['id'] and j.get('recoveryRequired')
                    for j in store.records('jobs')):
        return {'next': 'input', 'gaps': ['先核对已有产物或后台草稿，解除恢复待办'],
                'status': 'NEEDS_ATTENTION', 'message': '不确定的执行结果不能直接重跑'}
    if target == 'DRAFT':
        if not product['facts'].get('store'):
            return {'next': 'input', 'gaps': ['草稿目标店铺'],
                    'message': '请先选择并保存目标店铺，再开始本次草稿制作'}
        if product.get('draftHistory'):
            return {'next': 'input', 'gaps': ['已有历史草稿，请核对后在后台更新；不重复新建'],
                    'message': '保留原草稿线索，先核对已有产物'}
    proposed = product.get('attributePlan') or {}
    if proposed.get('revision') != revision:
        gaps=skill_jobs.missing(product,'attributes')
        return {'next': 'input' if gaps else 'attributes', 'gaps': gaps, 'message': '先按参考准备同源新品参数，供包装与固定模板使用；未知事实保留待确认'}
    package, visual = product.get('packaging') or {}, product.get('visual') or {}
    image_total=visual.get('templateCount') or (19 if any(row.get('slot')=='m7' for row in (visual.get('images') or [])) else 18)
    if product.get('recruitment'):
        import concept_direction
        conflict=concept_direction.conflict(product)
        if conflict:
            return {'next':'input','gaps':[conflict],'message':'请先明确新品设计方向与原征品要求的冲突'}
    if single_approval_flow.enabled(product):
        return single_approval_flow.plan(product, target or (product.get('workflow') or {}).get('target', 'DRAFT'))
    if product['facts'].get('mode') != 'real':
        if package.get('revision') != revision or not attribute_plan.artifact_matches(product, package):
            gaps = skill_jobs.missing(product, 'packaging')
            return {'next': 'packaging' if not gaps else 'input', 'gaps': gaps,
                    'message': '按原Skill新品流程生成包装方向'}
        if package.get('job') != product.get('approvedPackaging'):
            return {'next': 'packaging_review', 'gaps': ['当前包装产物审核'], 'message': '请查看并审核当前包装图'}
    if visual.get('revision') != revision or visual.get('needsRegeneration') or not attribute_plan.artifact_matches(product, visual):
        gaps = skill_jobs.missing(product, 'visual')
        return {'next': 'visual' if not gaps else 'input', 'gaps': gaps,
                'message': '沿用当前Skill固定'+str(image_total-12)+'主图与12详情，复用已完成模块'}
    if visual.get('job') != product.get('approvedVisual'):
        return {'next': 'visual_review', 'gaps': ['当前套图产物审核'], 'message': '请查看并审核当前版本套图'}
    if (target or (product.get('workflow') or {}).get('target')) == 'VISUALS':
        return {'next': 'done', 'gaps': [], 'status': 'VISUALS_READY', 'message': '本次仅图片任务已完成审核，未进入上品或保存草稿'}
    gaps = attribute_plan.blockers(product)
    if gaps:
        return {'next': 'attributes_review', 'gaps': gaps, 'message': '确认拟采用属性，缺项可修改后继续'}
    return {'next': 'listing', 'gaps': [], 'message': '调用原类目引擎填写、上传、保存草稿并回读'}


def update(identity, **changes):
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT data FROM products WHERE id=?', (identity,)).fetchone()
        if not row:
            raise ValueError('产品任务不存在')
        p = json.loads(row['data'])
        if (p.get('workflow') or {}).get('status')=='STOPPED' and changes.get('status')!='STOPPED':
            return p
        p['workflow'] = dict(p.get('workflow') or {}, **changes, updated=store.now())
        c.execute('UPDATE products SET data=? WHERE id=?', (json.dumps(p, ensure_ascii=False), identity))
    return p


def preview(items, key=None, target='DRAFT', approval_policy=None):
    import weekly_update
    if target not in ('DRAFT', 'VISUALS'):
        raise ValueError('无效制作目标')
    if approval_policy not in (None, single_approval_flow.POLICY):
        raise ValueError('无效首图确认策略')
    if key and key not in weekly_update.STORES:
        raise ValueError('目标店铺未绑定')
    if not isinstance(items, list) or not 1 <= len(items) <= 10:
        raise ValueError('每次请选择1至10个产品任务')
    results, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('产品预览格式无效')
        p = store.product(item.get('id'))
        if p['id'] in seen:
            continue
        seen.add(p['id'])
        if p['revision'] != item.get('revision'):
            raise ValueError('产品资料已变化，请刷新预检')
        if target == 'DRAFT' and p['facts'].get('store') not in weekly_update.STORES:
            raise ValueError('请先选择并保存已绑定的草稿目标店铺，再开始制作')
        if key and p['facts'].get('store') not in ('', None, key):
            raise ValueError('不能跨店铺提交制作')
        if key and (p.get('recruitment') or {}).get('store') not in (None, key):
            raise ValueError('目标店铺与征品来源不一致')
        if (target == 'DRAFT' and (p.get('recruitment') or {}).get('store')
                not in (None, p['facts']['store'])):
            raise ValueError('目标店铺与征品来源不一致')
        if approval_policy:
            p = dict(p, workflow=dict(p.get('workflow') or {}, approvalPolicy=approval_policy,
                                    listingMechanism='original-skill-v1'))
        step = plan(p, target)
        results.append(dict(step, id=p['id'], title=p['title'], revision=p['revision'], source=source(p),
                            eligible=step['next'] != 'done', target=target))
    return {'items': results, 'eligible': sum(x['eligible'] for x in results), 'target': target,
            'reviewRequired': True, 'message': '同一任务连续制作，待审核时保留进度；终点为' + ('图片审核，不进入上品' if target == 'VISUALS' else '后台草稿')}


def start(items, key, acknowledge, provider='codex-native', target='DRAFT', approval_policy=None,
          fresh_visual_contract=False):
    if acknowledge is not True:
        raise ValueError('请确认本次制作使用已有服务额度，并仅保存草稿')
    if provider not in ('codex-native', 'configured', 'tokenstation'):
        raise ValueError('无效生图执行方式')
    import skill_jobs
    checked = preview(items, key, target, approval_policy)
    if not skill_jobs.capability()['available']:
        raise ValueError('本机Skill执行器不可用')
    if fresh_visual_contract is True:
        if (len(checked['items']) != 1 or approval_policy != single_approval_flow.POLICY
                or target != 'DRAFT' or provider != 'codex-native'):
            raise ValueError('新18项合同仅支持当前首图策略的单产品草稿任务与原生执行器')
        import native_skill_jobs
        contract = native_skill_jobs.contract(skill_jobs.SKILLS)
        templates = contract.get('templates')
        if not isinstance(templates, dict) or len(templates) != 18 or set(templates) != FRESH_VISUAL_SLOTS or 'm7' in templates:
            raise ValueError('当前已安装Skill不是精确18项新合同')
        contract_version = (REFERENCE_SAMPLE_VISUAL_CONTRACT
                            if 'reference_sample.py' in (contract.get('scriptHashes') or {})
                            else FRESH_VISUAL_CONTRACT)
        item = checked['items'][0]
        if not item.get('eligible'):
            raise ValueError('当前工作流已完成，无需切换视觉合同')
        identity = item['id']
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT data FROM products WHERE id=?', (identity,)).fetchone()
            if not row:
                raise ValueError('产品任务不存在')
            p = json.loads(row['data'])
            workflow = p.get('workflow') or {}
            partial = p.get('visualPartial') or {}
            if (p['revision'] != item['revision'] or workflow.get('revision') != p['revision']
                    or workflow.get('approvalPolicy') != single_approval_flow.POLICY
                    or workflow.get('target') != 'DRAFT' or workflow.get('imageProvider') != 'codex-native'
                    or workflow.get('status') != 'NEEDS_ATTENTION'):
                raise ValueError('产品版本或原任务范围已变化，需重新预检')
            if p.get('visualPending'):
                raise ValueError('存在待核验图片任务，先核对原任务')
            if (partial.get('revision') != p['revision'] or not partial.get('job')
                    or not isinstance(partial.get('images'), list) or not partial['images']):
                raise ValueError('当前产品没有可迁移的部分套图产物')
            old_row = c.execute('SELECT data,status,scope FROM jobs WHERE id=?', (partial['job'],)).fetchone()
            if not old_row:
                raise ValueError('旧视觉任务记录不存在')
            old_job = json.loads(old_row['data'])
            if old_job.get('recoveryRequired') or old_job.get('executorStillRunning'):
                raise ValueError('旧任务执行器仍在运行或恢复未完成，不能迁移合同')
            if (old_row['status'] != 'NEEDS_ATTENTION' or old_job.get('status') != 'NEEDS_ATTENTION'
                    or old_job.get('kind') != 'visual' or old_job.get('product') != identity
                    or old_job.get('revision') != p['revision'] or old_job.get('imageProvider') != 'codex-native'
                    or old_row['scope'] != 'product:' + identity
                    or workflow.get('job') != partial['job']):
                raise ValueError('旧任务状态、版本或产品绑定不符合迁移条件')
            old_root = (store.STATE / 'runs' / partial['job']).resolve()
            runs_root = (store.STATE / 'runs').resolve()
            if not old_root.is_relative_to(runs_root) or old_root == runs_root:
                raise ValueError('旧任务目录绑定无效')
            try:
                old_input = json.loads((old_root / 'input.json').read_text(encoding='utf-8-sig'))
                old_templates = (old_input.get('nativeTemplateContract') or {}).get('templates')
            except (OSError, ValueError, TypeError):
                old_templates = None
            if not isinstance(old_templates, dict):
                raise ValueError('旧任务没有明确绑定的视觉模板合同')
            if len(old_templates) == 19 and set(old_templates) == LEGACY_VISUAL_SLOTS and 'm7' in old_templates:
                old_contract_slots=LEGACY_VISUAL_SLOTS
            elif len(old_templates) == 18 and set(old_templates) == FRESH_VISUAL_SLOTS and 'm7' not in old_templates:
                old_contract_slots=FRESH_VISUAL_SLOTS
            else:
                raise ValueError('旧任务模板槽位不符合可迁移的18项或19项合同')
            old_contract_count=len(old_templates)
            if partial.get('templateCount') not in (None,old_contract_count):
                raise ValueError('部分产物数量与旧任务模板合同不一致')
            modules = [image.get('slot') for image in partial['images'] if isinstance(image, dict)]
            if (len(modules) != len(partial['images']) or len(set(modules)) != len(modules)
                    or not set(modules).issubset(old_contract_slots)):
                raise ValueError('旧部分产物模块清单不符合其绑定合同')
            old_contract=old_input.get('nativeTemplateContract') or {}
            reference_migration = {}
            if contract_version == REFERENCE_SAMPLE_VISUAL_CONTRACT:
                import visual_reference
                reference_migration = visual_reference.migrate(p, old_job, old_root, contract)
            same_contract=(old_templates==templates
                           and old_contract.get('scriptHashes')==contract.get('scriptHashes')
                           and old_contract.get('brandCssHash')==contract.get('brandCssHash')
                           and old_contract.get('detailCssHash')==contract.get('detailCssHash')
                           and (contract_version != REFERENCE_SAMPLE_VISUAL_CONTRACT
                                or (old_input.get('referenceSamples')==reference_migration.get('referenceSamples')
                                    and old_input.get('referenceNutrition')==reference_migration.get('referenceNutrition'))))
            if same_contract:
                raise ValueError('旧任务已绑定当前Skill合同，无需切换或重复生成')
            product_scope = 'product:' + identity
            active = c.execute("SELECT data,scope FROM jobs WHERE status IN ('QUEUED','RUNNING')").fetchall()
            if any(active_row['scope'] == product_scope or json.loads(active_row['data']).get('product') == identity
                   for active_row in active):
                raise ValueError('该产品仍有活动任务，不能切换视觉合同')
            try:
                single_approval_flow.require_hero(p)
            except (ValueError, OSError) as error:
                raise ValueError('缺少当前版本且有效的首图确认：' + str(error)) from error
            snapshot = json.loads(json.dumps(partial, ensure_ascii=False))
            new_job = store.enqueue_in(c, 'visual', 'product:' + identity, {
                'product': identity, 'revision': p['revision'], 'store': p['facts'].get('store', ''),
                'imageProvider': 'codex-native', 'workflowContinuation': True,
                'freshVisualContract': contract_version, **reference_migration})
            history = list(p.get('visualHistory') or [])
            history.append({'job': partial['job'], 'revision': partial['revision'], 'modules': modules,
                            'templateCount':old_contract_count,'archivedAt': store.now(), 'asset': snapshot})
            p.update(visualHistory=history, visualPartial=None, approvedVisual=None)
            p['workflow'] = dict(workflow, revision=p['revision'], source=source(p), store=p['facts'].get('store', ''),
                target='DRAFT', imageProvider='codex-native', status='ACTIVE', authorizedAt=store.now(),
                migrationHold=False, job=new_job['id'], next='visual', gaps=[],
                freshVisualContract=contract_version,
                message=f'已归档旧{old_contract_count}项部分产物；新任务按当前18项Skill合同执行')
            c.execute('UPDATE products SET data=? WHERE id=?', (json.dumps(p, ensure_ascii=False), identity))
        return {'started': [identity], 'blocked': [], 'target': target}
    started, blocked = [], []
    for item in checked['items']:
        if not item['eligible']:
            blocked.append(item)
            continue
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            p = json.loads(c.execute('SELECT data FROM products WHERE id=?', (item['id'],)).fetchone()['data'])
            if p['revision'] != item['revision']:
                raise ValueError('预检后产品已变化')
            prior = p.get('workflow') or {}
            if (prior.get('status') == 'ACTIVE' and approval_policy
                    and prior.get('approvalPolicy') != approval_policy):
                raise ValueError('活动任务审批策略不同，请先停止并重新预检')
            if prior.get('revision') == p['revision'] and prior.get('status') == 'ACTIVE' and prior.get('target', 'DRAFT') != target:
                raise ValueError('当前主任务目标不同，请先停止并核对')
            if prior.get('revision') == p['revision'] and prior.get('status') == 'ACTIVE' and prior.get('imageProvider') != provider:
                raise ValueError('当前主任务已有不同执行方式，请先停止并核对')
            p['workflow'] = dict(prior, revision=p['revision'], source=source(p), store=p['facts'].get('store', ''),
                                 target=target, imageProvider=provider, status='ACTIVE', authorizedAt=store.now(), migrationHold=False)
            if approval_policy:
                p['workflow']['approvalPolicy'] = approval_policy
            if approval_policy==single_approval_flow.POLICY:
                p['workflow']['listingMechanism']='original-skill-v1'
            for legacy in ('selectionFlow', 'productionFlow'):
                if p.get(legacy):
                    p[legacy]['status'] = 'STOPPED'
            c.execute('UPDATE products SET data=? WHERE id=?', (json.dumps(p, ensure_ascii=False), p['id']))
        advance(p['id'])
        started.append(p['id'])
    return {'started': started, 'blocked': blocked, 'target': target}


def advance(identity):
    p = store.product(identity)
    flow = p.get('workflow') or {}
    if not flow or flow.get('status') in TERMINAL or flow.get('migrationHold'):
        return
    if flow.get('revision') != p['revision']:
        update(identity, status='STALE', message='资料变化，需重新预检并明确继续')
        return
    if single_approval_flow.enabled(p):
        p = single_approval_flow.apply_automatic(identity)
    active = next((j for j in store.records('jobs') if j.get('product') == identity and j['status'] in store.ACTIVE), None)
    if active:
        update(identity, status='ACTIVE', job=active['id'], next=active['kind'], message=active['progress'])
        return
    step = plan(p)
    kind = step['next']
    if kind == 'done':
        update(identity, status=step.get('status', 'DRAFT_SAVED'), next=kind, message=step['message'])
    elif kind in WAITING:
        update(identity, status=step.get('status', WAITING[kind]), next=kind, gaps=step['gaps'], message=step['message'])
    else:
        # Partial native output keeps the original job/context; never regenerate the batch.
        partial = p.get('visualPartial') or p.get('visualPending') or {}
        if kind == 'visual' and partial.get('revision') == p['revision']:
            if attribute_plan.artifact_matches(p, partial):
                update(identity, status='NEEDS_ATTENTION', next='resume_native',
                       message='已有部分或待核验图片，请从原任务恢复，复用模板与缓存', resumeJob=partial.get('job'))
            else:
                update(identity, status='NEEDS_ATTENTION', next='input',
                       message='部分图片未绑定当前属性方案，请先核对旧产物并重新预检；未自动重做')
            return
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            current=json.loads(c.execute('SELECT data FROM products WHERE id=?',(identity,)).fetchone()['data'])
            latest=current.get('workflow') or {}
            if latest.get('status') in TERMINAL or current['revision']!=p['revision']:
                return
            job=store.enqueue_in(c,kind,'product:'+identity,{
                'product':identity,'revision':p['revision'],'store':p['facts'].get('store',''),
                'imageProvider':latest['imageProvider'],'workflowContinuation':True})
            latest.update(status='ACTIVE',next=kind,job=job['id'],gaps=[],message=step['message'],updated=store.now())
            c.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(current,ensure_ascii=False),identity))


def stop(identity):
    p = store.product(identity)
    if not p.get('workflow'):
        raise ValueError('当前没有制作主任务')
    return update(identity, status='STOPPED', message='已停止后续交接；当前执行完成后保留产物，不自动继续')


def process_alive(pid):
    try:
        if not pid:
            return False
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x1000, False, int(pid))
            if not handle:
                return False
            code = wintypes.DWORD()
            try:
                return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
            finally:
                kernel.CloseHandle(handle)
        os.kill(int(pid), 0)
        return True
    except (ValueError, TypeError, OSError):
        return False


def reconcile(alive=process_alive):
    orphaned = 0
    for job in store.records('jobs'):
        if job['status'] == 'RUNNING' and not alive(job.get('workerPid')):
            store.job_update(job['id'], status='NEEDS_ATTENTION', recoveryRequired=True,
                             progress='服务执行者失联；先核对已有产物/草稿，不自动重新生图或保存', finished=store.now())
            if job.get('product') and store.product(job['product']).get('workflow'):
                update(job['product'], status='NEEDS_ATTENTION', message='需核对中断任务结果后恢复')
            orphaned += 1
    for p in store.records('products'):
        workflow = p.get('workflow')
        if isinstance(workflow, dict) and workflow.get('status') not in TERMINAL:
            advance(p['id'])
    return {'orphaned': orphaned}
