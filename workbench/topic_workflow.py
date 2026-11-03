"""Evidence-backed local rectification. Topic conditions are never seller facts."""
import hashlib
import json
import re
import sqlite3
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlsplit
import task_store as store

BUSINESSES = ('HOT_PRODUCT', 'CUSTOMIZATION_PRODUCT')


def fingerprint(topic):
    # Presentation labels/order can differ between native and cached pages.
    content={k:topic.get(k) for k in ('id','businessType','title','categoryIds','ruleSummary','requirements','image','pictureMatch','capabilities','priceFrom','priceTo','minOrderFrom','minOrderTo')}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def cached_topic(key, topic_id, business):
    import recruitment
    import weekly_update
    if key not in weekly_update.STORES or not str(topic_id).isdigit() or business not in BUSINESSES:
        raise ValueError('请选择有效店铺、征品类型与主题')
    base = recruitment.STATE / key
    try:
        snapshot = json.loads((base/'snapshot.json').read_text(encoding='utf-8'))
        path = (base/snapshot['database']).resolve()
        if not path.is_relative_to(base.resolve()):
            raise ValueError('征品缓存路径无效')
        with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as conn:
            row = conn.execute('SELECT payload FROM topics WHERE business=? AND id=?', (business, str(topic_id))).fetchone()
        if not row:
            raise ValueError('当前店铺该类型下未找到此主题，请重新选择')
        return json.loads(row[0]), snapshot.get('collectedAt') or snapshot.get('completed')
    except (OSError, sqlite3.Error, KeyError):
        raise ValueError('征品快照不可用，请先刷新完整征品列表') from None


def requirements(topic):
    rule = topic.get('ruleSummary') or {}
    leaf = str(rule.get('categoryId') or (topic.get('categoryIds') or [''])[-1])
    rows = [{'key':'category', 'kind':'category', 'name':'后台叶子类目', 'expected':[leaf] if leaf else [],
             'description':' → '.join(topic.get('categories') or []) or topic.get('categoryLeaf',''),
             'fix':'选择与主题一致的后台叶子类目；上级类目不能替代叶子类目。'}]
    for index, attr in enumerate(rule.get('attrDTOList') or []):
        field_id = str(attr.get('productPropertyId') or attr.get('attrId') or '')
        options = [{'name':str(v.get('attrValueName') or ''),
                    'id':str(v.get('productValueId') or v.get('attrValueId') or '')}
                   for v in attr.get('attrValueDTOList') or [] if isinstance(v,dict)]
        rows.append({'key':'attr:'+(field_id or 'unknown-'+str(index)), 'kind':'attribute',
                     'name':str(attr.get('attrName') or '未命名属性'), 'fieldId':field_id,
                     'categoryId':str(attr.get('categoryId') or leaf), 'options':options,
                     'expected':[v['name'] for v in options], 'description':'后台商品属性',
                     'fix':'核对真实产品资料，并匹配平台字段和选项；不能只写入标题或描述。'})
    # Older snapshots may have readable names only. They cannot yield a native assignment.
    if not rule.get('attrDTOList'):
        for index, attr in enumerate(topic.get('requirements') or []):
            rows.append({'key':'attr:unknown-'+str(index),'kind':'attribute','name':attr['name'],
                         'expected':attr.get('values',[]),'options':[], 'fieldId':'',
                         'fix':'主题未返回字段ID，需重新采集或在后台核对，不能自动猜选项。'})
    if (rule.get('needPicMatch') or topic.get('pictureMatch')) == 'Y':
        rows.append({'key':'image','kind':'image','name':'首图商品主体', 'expected':['主体相似'],
                     'description':'主题参考图仅用于主体、剂型与包装形式判断，不能照搬品牌。',
                     'fix':'核对我方首图与主题商品主体、剂型和包装形式；图片审核记录须说明依据。'})
    for key, name, low, high in [('price','价格要求',rule.get('priceFrom'),rule.get('priceTo')),
                                 ('moq','起订量要求',rule.get('minOrdQtyFrom'),rule.get('minOrdQtyTo'))]:
        if low is not None or high is not None:
            rows.append({'key':key,'kind':'range','name':name,'minimum':low,'maximum':high,
                         'expected':[('≥ '+str(low)) if low is not None else '',('≤ '+str(high)) if high is not None else ''],
                         'description':'平台数值范围；币种、计价单位及起订量单位需人工核对。',
                         'fix':'核对真实报价/起订量及单位口径，不能为满足主题而虚填。'})
    capacities = rule.get('capacityDtoList') or []
    for index, cap in enumerate(capacities):
        if cap.get('field')=='cert_tag' or '证书' in str(cap.get('name','')):
            continue
        rows.append({'key':'capacity:'+str(cap.get('field') or index),'kind':'capacity',
                     'name':'服务能力：'+str(cap.get('name') or cap.get('field')),
                     'expected':[str(cap.get('name') or cap.get('field'))],
                     'fix':'核对后台实际服务能力；本地填写不代表平台标签已开通。'})
    if (rule.get('certificateList') or any(c.get('field')=='cert_tag' or '证书' in str(c.get('name','')) for c in capacities)
            or any('证书' in c for c in topic.get('capabilities',[]))):
        rows.append({'key':'certificate','kind':'manual','name':'证书关联','expected':['按主题要求在后台绑定真实适用证书'],
                     'fix':'由你后续在后台绑定；当前不阻断内部整改和草稿准备，发布前仍需平台核验。'})
    return rows


def attach(product, key, topic):
    if topic.get('businessType') not in BUSINESSES:
        raise ValueError('征品类型无效')
    if product.get('recruitment'):
        return product
    product['recruitment'] = {'store':key,'topicId':str(topic['id']), 'businessType':topic['businessType'],
                              'snapshot':json.loads(json.dumps(topic)), 'fingerprint':fingerprint(topic),'captured':store.now(), 'entries':{}}
    product['facts']['store'] = key
    product['events'].append({'time':store.now(),'message':'已关联征品要求快照；要求值未作为我方产品事实填写，证书由用户后续绑定'})
    return store.save_product(product)


def normalized(value):
    return re.sub(r'\s+', ' ', str(value).strip()).casefold()


def draft_values(product, rec):
    """Read accepted draft observations separately from supply facts and targets."""
    from recruitment_listing_overlay import _key
    draft = product.get('draft') or {}
    key = (product.get('facts') or {}).get('store')
    try:
        url = urlsplit(str(draft.get('draft_url') or ''))
    except ValueError:
        return {}
    if (draft.get('readback_verified') is not True or draft.get('revision') != product.get('revision')
            or not key or draft.get('store') != key or rec.get('store') != key
            or draft.get('expected_store', key) != key or not draft.get('draft_id')
            or url.scheme != 'https' or url.hostname != 'post.alibaba.com'
            or parse_qs(url.query).get('itemId') != [str(draft['draft_id'])]
            or draft.get('uncertain') or draft.get('reconciliationRequired')):
        return {}
    values = {}
    if draft.get('category_id'):
        values['category'] = str(draft['category_id'])
    fields = draft.get('fields') or {}
    for row in requirements(rec['snapshot']):
        field = fields.get(_key(row['name'])) if row['kind'] == 'attribute' else None
        if isinstance(field, dict) and field.get('matched') is True and field.get('actual'):
            values[row['key']] = str(field['actual'])
    # Only post-save structured observations contain actual transaction values.
    job = str(draft.get('job') or '')
    filename = {'readback.json': 'reports/run-all-report.json',
                'readback-refresh.json': 'readback-refresh-report.json'}.get(draft.get('evidence_file'))
    if not filename or not re.fullmatch(r'[A-Za-z0-9_-]+', job):
        return values
    try:
        observed = json.loads((store.STATE/'runs'/job/filename).read_text(encoding='utf-8'))
        verified = observed.get('post_save_verification') or {}
        if (observed.get('product_id') != product.get('id') or observed.get('status') != 'completed'
                or verified.get('status') != 'verified' or verified.get('missing_required')
                or verified.get('structure_mismatches')
                or verified.get('resolved_draft_url') != draft.get('draft_url')):
            return values
        pricing = (verified.get('structured_validation') or {}).get('pricing') or {}
        tiers = pricing.get('actual_tiers') or []
        if pricing.get('matched') is True and tiers and pricing.get('actual_unit'):
            tier = min(tiers, key=lambda item: Decimal(str(item['qty'])))
            qty, price = str(tier['qty']), str(tier['price'])
            if (Decimal(qty).is_finite() and Decimal(qty) > 0
                    and Decimal(price).is_finite() and Decimal(price) >= 0):
                values['price'] = price + ' ' + str(pricing['actual_unit'])
                values['moq'] = qty + ' ' + str(pricing['actual_unit'])
    except (OSError, ValueError, TypeError, AttributeError, KeyError, InvalidOperation):
        pass
    return values


def report(product):
    rec = product.get('recruitment')
    if not rec:
        return None
    rows = []
    saved_values = draft_values(product, rec)
    for requirement in requirements(rec['snapshot']):
        row = dict(requirement)
        entry = rec.get('entries',{}).get(row['key'],{})
        row.update(actual=entry.get('actual',''), evidence=entry.get('evidence',''), note=entry.get('note',''), draftActual=saved_values.get(row['key'], '未回读'))
        if row['kind']=='manual':
            row.update(status='MANUAL',message='待你在后台绑定；未自动关联证书')
        elif not row['actual']:
            row.update(status='TO_CONFIRM',message='尚未填写我方实际值')
        else:
            matches = normalized(row['actual']) in [normalized(v) for v in row['expected'] if v]
            if row['kind']=='range':
                try:
                    val=Decimal(row['actual'])
                    matches=val.is_finite() and val>=0 and (row['minimum'] is None or val>=Decimal(str(row['minimum']))) and (row['maximum'] is None or val<=Decimal(str(row['maximum'])))
                except InvalidOperation:
                    matches=False
            if not matches:
                row.update(status='MISMATCH',message='实际值不符合主题条件，请整改或改选产品/主题')
            elif not row['evidence']:
                row.update(status='TO_CONFIRM',message='数值相符，但缺少真实产品资料依据')
            elif row['kind']=='attribute' and (not row.get('fieldId') or not row.get('options')):
                row.update(status='TO_CONFIRM',message='缺少平台字段/选项ID，不能进入自动填写')
            else:
                row.update(status='MATCHED',message='本地资料对照一致；待后台回读及平台检测')
                if row['kind']=='attribute':
                    ids=[o['id'] for o in row['options'] if normalized(o['name'])==normalized(row['actual'])]
                    if len(ids)!=1 or any(not v for v in ids):
                        row.update(status='TO_CONFIRM',message='平台选项ID缺失或存在歧义，需核对后填写')
                    else:
                        row['assignment']={'fieldId':row['fieldId'],'categoryId':row['categoryId'],'valueIds':ids,'value':row['actual'],'evidence':row['evidence']}
        rows.append(row)
    blockers = [r['name'] for r in rows if r['status'] not in ('MATCHED','MANUAL')]
    if product['facts'].get('store')!=rec['store']:
        blockers.append('目标店铺与征品来源店铺不一致')
    return {'topicId':rec['topicId'],'store':rec['store'],'businessType':rec['businessType'],
            'captured':rec['captured'],'fingerprint':rec['fingerprint'],'topicTitle':rec['snapshot']['title'],
            'referenceImage':rec['snapshot'].get('image',''),'rows':rows,'blockers':blockers,
            'readyForDraft':not blockers,'readyToPublish':False,
            'manualCount':sum(r['status']=='MANUAL' for r in rows),'matchedCount':sum(r['status']=='MATCHED' for r in rows),
            'platform':{'status':'NOT_RUN','message':'平台征品检测尚未执行。本地对照通过不能作为征品成功证明。'}}


def save(product_id, revision, entries):
    if not isinstance(entries,dict):
        raise ValueError('整改内容无效')
    with store.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT data FROM products WHERE id=?',(product_id,)).fetchone()
        if not row:
            raise ValueError('产品任务不存在')
        product=json.loads(row['data'])
        if product['revision']!=revision:
            raise ValueError('资料版本已变化，请刷新后重新填写')
        rec=product.get('recruitment')
        if not rec:
            raise ValueError('此产品尚未关联征品主题')
        allowed={r['key'] for r in requirements(rec['snapshot']) if r['kind']!='manual'}
        updated=dict(rec.get('entries',{}))
        for key, entry in entries.items():
            if key not in allowed or not isinstance(entry,dict):
                raise ValueError('整改字段不属于当前主题，或证书需在后台手动绑定')
            clean={k:str(entry.get(k,'')).strip()[:2000] for k in ('actual','evidence','note')}
            if any(clean.values()): updated[key]=clean
            else: updated.pop(key,None)
        if updated!=rec.get('entries',{}):
            rec['entries']=updated
            store.archive_draft(product, 'topic_rectification_changed')
            product.update(revision=product['revision']+1,stage='FACTS',approvedVisual=None,draft=None)
            product['events'].append({'time':store.now(),'message':'征品整改资料已保存；图片审核、草稿验收与旧检测结论失效'})
        conn.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(product,ensure_ascii=False),product_id))
    return product


def handoff(product):
    result=report(product)
    if not result:
        return None
    return {'topicId':result['topicId'],'store':result['store'],'businessType':result['businessType'],
            'sourceFingerprint':result['fingerprint'],'referenceImage':result['referenceImage'],
            'requirements':result['rows'],'attributeAssignments':[r['assignment'] for r in result['rows'] if 'assignment' in r],
            'certificatePolicy':'用户后续在后台手动绑定；不得捏造证书、检测通过或征品成功',
            'platformCheck':'NOT_RUN'}
