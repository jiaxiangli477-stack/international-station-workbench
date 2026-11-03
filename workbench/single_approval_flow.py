"""Opt-in policy: one real m1 confirmation authorizes the same draft scope."""
import hashlib
import json
import re
from PIL import Image
import attribute_plan
import task_store as store

POLICY = 'single-hero-v1'
SLOTS = {f'm{i}' for i in range(1, 7)} | {'d1','d2','d3','d4','df','d5','d6','dfac','d7','dc','drev','d9'}
PAUSED = {'STOPPED', 'STALE', 'NEEDS_ATTENTION', 'DRAFT_SAVED', 'VISUALS_READY'}
CONTENT_BLOCKS = ('selling_points', 'faqs', 'company_intro', 'pricing', 'lead_time', 'logistics')
EVIDENCE_CLAIMS = re.compile(
    r'\b(?:nsf|gmp|fssc|haccp|iso\s*\d+|fda|coa|certif\w*|accredit\w*|clinically|clinical|tested|verified|proven|patent\w*)\b'
    r'|认证|证书|检测|实测|临床|专利|销量|配方库', re.I)
QUANTIFIED_BUSINESS = re.compile(
    r'\d[\d.,+\-–—]*\s*(?:business\s*)?(?:days?\b|hours?\b|formulations?\b|formulas?\b|天|小时|配方)'
    r'|\b(?:moq|lead[- ]?time|delivery|samples?|bulk|capacity|turnaround)\b[^.;\n]{0,100}\d', re.I)
UNVERIFIED_SOURCE = re.compile(
    r'原\s*(?:上品)?\s*skill.{0,24}(?:默认|常量|生成|建议)|(?:AI|模型|模板)(?:自动)?生成'
    r'|\b(?:default|hardcoded|generated)\s+(?:profile|template|skill|copy)\b', re.I)


def content_source_gaps(manifest, sources):
    """Block-level provenance may cover descendants; one leaf never covers siblings."""
    gaps = []
    defaults = manifest.get('_adapter_effective_defaults') or {}
    if not isinstance(defaults, dict):
        gaps.append('原Skill默认覆盖来源元数据格式无效')
        defaults = {}
    for key, value in defaults.items():
        if not isinstance(value, dict) or value.get('status') != 'RESOLVED':
            gaps.append('原Skill默认覆盖值需核验来源：' + key)

    def visit(value, path, block):
        if isinstance(value, dict):
            for key, item in value.items(): visit(item, path + '.' + str(key), block)
            return
        if isinstance(value, list):
            for index, item in enumerate(value): visit(item, path + '.' + str(index), block)
            return
        if value is None or value == '' or (isinstance(value, str) and not value.strip()):
            return
        source = None
        parts = path.split('.')
        for count in range(len(parts), 0, -1):
            key = '.'.join(parts[:count])
            if key in sources:
                source = sources[key]
                break
        if (not isinstance(source, dict) or source.get('kind') not in ('REFERENCE','DESIGN','CONFIRMED')
                or not isinstance(source.get('source'), str) or not source['source'].strip()):
            gaps.append('非属性内容缺来源：' + path)
            return
        if UNVERIFIED_SOURCE.search(source['source']):
            gaps.append('生成器或模板默认内容不是本品事实证据：' + path)
            return
        text = str(value)
        # A question is not a certificate/measurement assertion. Its answer still is.
        factual_claim = (not path.endswith('.question') and
            (EVIDENCE_CLAIMS.search(text) or QUANTIFIED_BUSINESS.search(text)
             or (block in ('pricing','lead_time','logistics') and not path.endswith(('.source','_source'))
                 and re.search(r'\d', text))))
        if factual_claim and source.get('kind') != 'CONFIRMED':
            gaps.append('证书、实测或定量商务承诺需本品CONFIRMED来源：' + path)
    for block in CONTENT_BLOCKS:
        visit(manifest.get(block), block, block)
    return list(dict.fromkeys(gaps))


def enabled(product):
    return (product.get('workflow') or {}).get('approvalPolicy') == POLICY


def image_path(asset, row):
    runs = (store.STATE / 'runs').resolve()
    root = (runs / str(asset.get('job', ''))).resolve()
    path = (root / str(row.get('file', ''))).resolve()
    if not asset.get('job') or not root.is_relative_to(runs) or root == runs or not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise ValueError('首图真实产物缺失或路径无效')
    return path


def pixel_hash(asset, row):
    with Image.open(image_path(asset, row)) as image:
        image.load()
        if image.size != (1000, 1000):
            raise ValueError('正式首图必须为1000×1000')
        return hashlib.sha256(str(image.size).encode() + image.convert('RGBA').tobytes()).hexdigest()


def packaging_gaps(product):
    if product['facts'].get('mode') == 'real':
        return []
    asset = product.get('packaging') or {}
    rows = asset.get('images') or []
    if len(rows) != 1 or rows[0].get('slot') != 'A0':
        return ['内部包装A0真实素材清单待核对']
    try:
        with Image.open(image_path(asset, rows[0])) as image:
            if min(image.size) < 800:
                return ['内部包装A0素材尺寸不足']
            image.verify()
    except (ValueError, OSError):
        return ['内部包装A0真实文件缺失或损坏']
    return []


def hero_scope(product):
    hero = product.get('hero') or {}
    rows = hero.get('images') or []
    if (not enabled(product) or packaging_gaps(product) or hero.get('revision') != product['revision']
            or not attribute_plan.artifact_matches(product, hero)
            or hero.get('templateVerified') is not True or len(rows) != 1 or rows[0].get('slot') != 'm1'
            or hero.get('packagingJob') != (product.get('packaging') or {}).get('job')):
        raise ValueError('缺少绑定当前资料与原模板的正式m1首图，A0包装不能替代')
    if (rows[0].get('specCheck') == 'bad' or (rows[0].get('quality') or {}).get('failed')
            or (hero.get('quality') or {}).get('failed')):
        raise ValueError('首图质检失败，不能批准')
    actual = pixel_hash(hero, rows[0])
    if hero.get('pixelHash') != actual:
        raise ValueError('首图像素已变化，请重新查看并确认')
    return {'policy': POLICY, 'product': product['id'], 'revision': product['revision'],
            'attributePlanFingerprint': (product.get('attributePlan') or {}).get('fingerprint'),
            'heroJob': hero['job'], 'packagingJob': hero.get('packagingJob'), 'pixelHash': actual}


def signature(scope):
    return hashlib.sha256(json.dumps(scope, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def require_hero(product):
    scope = hero_scope(product)
    approval = product.get('heroApproval') or {}
    if approval.get('signature') != signature(scope) or any(approval.get(k) != v for k, v in scope.items()):
        raise ValueError('请先确认当前正式m1首图；资料变化后须重新确认')
    return scope


def install_hero(product_id, revision, asset):
    """Caller has verified the real single-module template receipt, never A0."""
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        p = json.loads(c.execute('SELECT data FROM products WHERE id=?', (product_id,)).fetchone()['data'])
        if not enabled(p) or p['revision'] != revision or asset.get('revision') != revision:
            raise ValueError('首图策略或产品版本已变化')
        hero = json.loads(json.dumps(asset))
        if len(hero.get('images') or []) != 1 or hero['images'][0].get('slot') != 'm1':
            raise ValueError('首图任务只能交回正式m1，不能使用A0')
        hero['packagingJob'] = (p.get('packaging') or {}).get('job')
        hero['pixelHash'] = pixel_hash(hero, hero['images'][0])
        p['hero'] = hero
        hero_scope(p)
        p.update(heroApproval=None, approvedVisual=None, approvedAttributes=None, stage='HERO_REVIEW')
        p['events'].append({'time':store.now(),'message':'正式m1首图已生成，等待唯一一次首图确认；尚未生成其余模块'})
        c.execute('UPDATE products SET data=? WHERE id=?', (json.dumps(p, ensure_ascii=False), product_id))
    return p


def approve(product_id, revision, job, fingerprint, expected_pixel_hash, acknowledge):
    if acknowledge is not True:
        raise ValueError('请确认当前首图并授权同范围套图及仅保存草稿')
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        p = json.loads(c.execute('SELECT data FROM products WHERE id=?', (product_id,)).fetchone()['data'])
        if (p.get('workflow') or {}).get('status') in {'STOPPED','STALE','NEEDS_ATTENTION'}:
            raise ValueError('主任务已暂停或资料变化，请先明确重新预检')
        scope = hero_scope(p)
        if (revision != scope['revision'] or job != scope['heroJob']
                or fingerprint != scope['attributePlanFingerprint'] or expected_pixel_hash != scope['pixelHash']):
            raise ValueError('首图或属性版本已变化，请重新查看后确认')
        p['heroApproval'] = dict(scope, signature=signature(scope), approvedAt=store.now())
        p['workflow'].update(status='ACTIVE', next='visual', message='首图已确认，同范围自动完成套图及草稿，仍保留事实与质检闸门')
        p['events'].append({'time':store.now(),'message':'用户确认正式m1首图；授权同版本后续套图与草稿，不授权发布'})
        c.execute('UPDATE products SET data=? WHERE id=?', (json.dumps(p, ensure_ascii=False), product_id))
    return apply_automatic(product_id)


def draft_unresolved(product):
    rows=list((product.get('attributePlan') or {}).get('unresolved') or [])
    if enabled(product) and product.get('recruitment') and (product.get('workflow') or {}).get('recruitmentMatchPolicy','visual-reference')=='visual-reference':
        # Theme eligibility and old stage notes remain archived, but are not
        # current-product facts or prerequisites for an ordinary draft.
        advisory={'category_conflict','dosage_form_conflict','theme_function_mapping','m7_dependency','proposal_only'}
        return [row for row in rows if str(row).split(':',1)[0] not in advisory]
    return rows


def fact_gaps(product):
    plan = product.get('attributePlan') or {}
    if plan.get('revision') != product['revision'] or plan.get('fingerprint') != attribute_plan.fingerprint(plan):
        return ['当前版本属性方案及来源指纹']
    gaps = draft_unresolved(product)
    normalized = attribute_plan.normalize(plan.get('manifest'), plan.get('field_sources') or {}, gaps)
    gaps = normalized['unresolved']
    gaps += content_source_gaps(plan.get('manifest') or {}, plan.get('field_sources') or {})
    def unknown(value):
        if isinstance(value, dict): return any(unknown(v) for v in value.values())
        if isinstance(value, list): return any(unknown(v) for v in value)
        return isinstance(value, str) and 'TO_CONFIRM' in value
    if unknown(plan.get('manifest')):
        gaps.append('属性仍含TO_CONFIRM，不能作为已确认草稿事实')
    return list(dict.fromkeys(gaps))


def visual_gaps(product):
    asset = product.get('visual') or {}
    rows = asset.get('images') or []
    gaps = []
    if asset.get('templateCount') != 18 or len(rows) != 18 or {row.get('slot') for row in rows} != SLOTS:
        gaps.append('新版固定6张主图与12项详情（18项）')
    for row in rows:
        if row.get('slot') == 'm1':
            try:
                if pixel_hash(asset, row) != require_hero(product)['pixelHash']:
                    gaps.append('完整套图m1与已确认首图像素不一致')
            except (ValueError, OSError):
                gaps.append('已确认首图及套图m1真实文件待核对')
        elif (row.get('specCheck') not in ('ok','not_applicable') or (row.get('quality') or {}).get('reviewRequired')
              or 'specification' in (row.get('reviewRequirements') or [])):
            gaps.append('模块质检或规格待核：' + str(row.get('slot')))
        if row.get('specCheck') == 'bad' or (row.get('quality') or {}).get('failed'):
            gaps.append('模块质检失败：' + str(row.get('slot')))
    if (asset.get('quality') or {}).get('reviewRequired'):
        gaps.append('套图质检仍需处理')
    if (asset.get('quality') or {}).get('failed'):
        gaps.append('套图整体质检失败')
    return list(dict.fromkeys(gaps))


def apply_automatic(product_id):
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        p = json.loads(c.execute('SELECT data FROM products WHERE id=?', (product_id,)).fetchone()['data'])
        if not enabled(p) or (p.get('workflow') or {}).get('status') in PAUSED:
            return p
        # Old approval tokens never substitute for this policy's current checks.
        p['approvedPackaging'] = None
        p['approvedVisual'] = None
        p['approvedAttributes'] = None
        package = p.get('packaging') or {}
        design = p.get('designReview') or {}
        text = design.get('text') if design.get('revision') == p['revision'] else None
        text = text or p.get('facts', {}).get('design')
        if text and p['facts'].get('mode') != 'real':
            p['designReview'] = dict(design, revision=p['revision'], text=text,
                fingerprint=hashlib.sha256(text.encode()).hexdigest(), status='APPROVED', approvalSource=POLICY)
        if package.get('revision') == p['revision'] and attribute_plan.artifact_matches(p, package) and not packaging_gaps(p):
            if not (package.get('quality') or {}).get('failed') and not any(row.get('specCheck')=='bad' for row in package.get('images', [])):
                p['approvedPackaging'] = package.get('job')
                p['packagingApprovalSource'] = POLICY + ':internal-material'
        try:
            require_hero(p)
        except (ValueError, OSError):
            pass
        else:
            if not fact_gaps(p):
                p['approvedAttributes'] = p['attributePlan']['fingerprint']
                p['attributePlan']['approvalSource'] = POLICY
            visual = p.get('visual') or {}
            if (visual.get('revision') == p['revision'] and attribute_plan.artifact_matches(p, visual)
                    and not visual_gaps(p)):
                p['approvedVisual'] = visual.get('job')
                p['visualApprovalSource'] = POLICY
        c.execute('UPDATE products SET data=? WHERE id=?', (json.dumps(p, ensure_ascii=False), product_id))
    return p


def require_listing(product, original_skill=False):
    require_hero(product)
    visual = product.get('visual') or {}
    if visual.get('revision') != product['revision'] or not attribute_plan.artifact_matches(product, visual):
        raise ValueError('完整套图尚未绑定当前首图确认范围')
    gaps = visual_gaps(product) + ([] if original_skill else fact_gaps(product))
    if (product.get('workflow') or {}).get('target') == 'VISUALS':
        gaps.append('仅图片目标不能保存草稿')
    if gaps:
        raise ValueError('草稿前需处理：' + '、'.join(gaps)[:300])


def plan(product, target):
    import skill_jobs
    package = product.get('packaging') or {}
    if (package.get('quality') or {}).get('failed') or any(row.get('specCheck')=='bad' for row in package.get('images', [])):
        return {'next':'input','gaps':['内部包装素材质检失败'],'message':'先处理包装质检缺口，不能用首图策略跳过失败'}
    if product['facts'].get('mode') != 'real' and (package.get('revision') != product['revision']
            or not attribute_plan.artifact_matches(product, package)):
        gaps = skill_jobs.missing(product, 'packaging')
        return {'next':'input' if gaps else 'packaging','gaps':gaps,'message':'按原Skill生成内部包装素材，无需重复包装签字'}
    gaps = packaging_gaps(product)
    if gaps:
        return {'next':'input','gaps':gaps,'message':'缺少真实内部包装素材，先核对原任务，未自动重新花费'}
    try:
        hero_scope(product)
    except (ValueError, OSError):
        return {'next':'hero','gaps':[],'message':'仅生成原Skill正式m1首图，确认前不制作其余模块'}
    try:
        require_hero(product)
    except ValueError:
        return {'next':'hero_review','gaps':['确认当前正式m1首图'],'message':'查看真实首图后确认一次，再自动制作套图并保存草稿'}
    visual = product.get('visual') or {}
    if visual.get('revision') != product['revision'] or not attribute_plan.artifact_matches(product, visual):
        gaps = skill_jobs.missing(product, 'visual')
        return {'next':'input' if gaps else 'visual','gaps':gaps,'message':'复用已确认m1，按原Skill完成其余17项模块（共18项）'}
    gaps = visual_gaps(product)
    if gaps:
        return {'next':'input','gaps':gaps,'message':'处理真实质检缺口，首图确认不能替代模块质检'}
    if target == 'VISUALS':
        return {'next':'done','gaps':[],'status':'VISUALS_READY','message':'图片已按首图确认范围完成，仅图片目标不保存草稿'}
    if (product.get('workflow') or {}).get('listingMechanism')=='original-skill-v1':
        prepared=product.get('listingSkill') or {}
        if (prepared.get('revision')==product['revision']
                and prepared.get('attributePlanFingerprint')==(product.get('attributePlan') or {}).get('fingerprint')
                and prepared.get('visualJob')==visual.get('job')
                and prepared.get('status')=='BLOCKED'):
            issues=list((prepared.get('content_preflight') or {}).get('blockingDiagnostics') or [])
            issues += ['征品字段待原Skill核对：'+str(row.get('name') or row.get('field') or row.get('code')) for row in prepared.get('pending_requirements',[])]
            return {'next':'input','gaps':issues,'message':'原Skill预检未通过，具体异常已列出；不需要独立CDN流程'}
        return {'next':'listing','gaps':[],'message':'按原Skill自动预检、替换征品属性、处理本地图片并保存草稿'}
    gaps = fact_gaps(product)
    if not product['facts'].get('store'): gaps.append('草稿目标店铺')
    if product.get('draftHistory'): gaps.append('已有历史草稿，请先核对并更新，不能重复新建')
    return {'next':'input' if gaps else 'listing','gaps':gaps,
            'advisories':[row for row in (product.get('attributePlan') or {}).get('unresolved',[]) if row not in draft_unresolved(product)],
            'message':'待补真实资料或处理已有草稿' if gaps else '首图确认范围内自动填写、仅保存草稿并回读，最后等待用户检查'}
