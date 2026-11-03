"""Candidate checkbox handoff: concept packaging can precede commercial facts."""
import hashlib
import json
import re
from urllib.request import urlopen
from urllib.parse import urlsplit
import task_store as store
import skill_jobs


def source():
    import selection_service
    return selection_service.bootstrap().get('candidates',[])


def fingerprint(item):
    content={k:item.get(k) for k in ('id','title','form','markets','differentiation','product_references','screening')}
    return hashlib.sha256(json.dumps(content,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def facts(item):
    return {'mode':'concept','market':' / '.join(str(m.get('country','')) for m in item.get('markets',[]) if m.get('country')),
            'form':str(item.get('form') or ''),'design':str(item.get('differentiation') or '根据候选类目与剂型设计原创包装，参考不复制品牌；缺失产品事实保留待确认。'),
            'formula':'','price':'','spec':'','moq':'','store':'','own_image':''}


def references(item):
    return [{'name':r.get('name'),'url':r.get('url'),'image_url':r.get('image_url'),'scope':'外部选品参考，非我方产品事实'} for r in item.get('product_references',[])]


def image_plan(p):
    package=p.get('packaging') or {};visual=p.get('visual') or {}
    kind='visual' if p['facts'].get('mode')=='real' or (package.get('revision')==p['revision'] and package.get('job')==p.get('approvedPackaging')) else 'packaging'
    gaps=skill_jobs.missing(p,kind)
    if visual.get('revision')==p['revision'] and visual.get('job'):gaps.append('当前版本已有整套图片，请打开产品任务审核；重新生成可在产品任务发起')
    elif package.get('revision')==p['revision'] and package.get('job')!=p.get('approvedPackaging'):gaps.append('已有包装方向待审核，审核后再生成整套图片')
    return kind,gaps


def choices():
    rows=[]
    for c in source():
        if c.get('screening',{}).get('status')=='EXCLUDED':continue
        refs=c.get('product_references') or []
        image=next((r.get('image_url') for r in refs if urlsplit(str(r.get('image_url') or '')).scheme in ('http','https')),'')
        rows.append({'id':c['id'],'title':c['title'],'form':c.get('form',''),'gate':c.get('gate','待核验'),
                     'markets':[str(m.get('country','')) for m in c.get('markets',[]) if m.get('country')],
                     'design':str(c.get('differentiation') or '')[:1500],'image':image,'referenceCount':len(refs)})
    return {'candidates':rows}


def preview(ids):
    if not isinstance(ids,list) or not 1<=len(ids)<=10 or any(not isinstance(i,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',i) for i in ids):
        raise ValueError('请选择1至10个有效候选')
    by_id={c['id']:c for c in source()};products={p['source']:p for p in store.records('products')}
    items=[]
    for identity in dict.fromkeys(ids):
        item=by_id.get(identity)
        if not item:raise ValueError('候选已变化或不存在，请刷新列表')
        product=products.get('selection:'+identity)
        p=product or {'facts':facts(item),'revision':1}
        package=p.get('packaging') or {};visual=p.get('visual') or {}
        kind='visual' if p['facts'].get('mode')=='real' or (package.get('revision')==p['revision'] and package.get('job')==p.get('approvedPackaging')) else 'packaging'
        gaps=skill_jobs.missing(p,kind)
        if item.get('screening',{}).get('status')=='EXCLUDED':gaps.insert(0,'该候选已被经营范围规则排除')
        if visual.get('revision')==p['revision'] and visual.get('job'):gaps.append('当前版本已有整套图片，请打开产品任务审核；重新生成可在产品任务发起')
        elif package.get('revision')==p['revision'] and package.get('job')!=p.get('approvedPackaging'):
            gaps.append('已有包装方向待审核，审核后再生成整套图片')
        items.append({'candidate':identity,'fingerprint':fingerprint(item),'title':item['title'],'kind':kind,
                      'product':product['id'] if product else None,'revision':product['revision'] if product else None,
                      'eligible':not gaps,'gaps':gaps,'mode':p['facts'].get('mode')})
    return {'items':items,'eligible':sum(x['eligible'] for x in items),'boundary':'概念包装/生图任务，不自动上品或发布；配方、证书、价格仍待确认。'}


def start(items, acknowledge):
    if acknowledge is not True:raise ValueError('请确认本批次使用已有生图服务额度')
    if not isinstance(items,list) or not items or len(items)>10 or any(not isinstance(x,dict) for x in items):raise ValueError('执行预览无效')
    plan=preview([x.get('candidate') for x in items]);old={x.get('candidate'):x for x in items}
    for item in plan['items']:
        original=old[item['candidate']]
        same_request=any(j.get('product')==item['product'] and j.get('revision')==item['revision'] and j.get('candidateFingerprint')==item['fingerprint'] and j['status'] in store.ACTIVE for j in store.records('jobs'))
        changed=any(item.get(k)!=original.get(k) for k in ('fingerprint','kind')) or (any(item.get(k)!=original.get(k) for k in ('product','revision')) and not (not original.get('product') and same_request))
        if changed:
            raise ValueError('预览后候选或产品资料已变化，请重新预览')
    if not skill_jobs.capability()['available']:raise ValueError('本机生图执行器暂不可用，未提交任务')
    live={c['id']:c for c in source()};started=[];blocked=[]
    for item in plan['items']:
        if not item['eligible']:
            blocked.append(item);continue
        current=live.get(item['candidate'])
        if not current or fingerprint(current)!=item['fingerprint']:
            blocked.append(dict(item,gaps=['候选资料已变化，请重新预览']));continue
        p=store.create_product('selection:'+current['id'],current['title'],references=references(current),facts=facts(current))
        if item['product'] and p['revision']!=item['revision']:
            blocked.append(dict(item,gaps=['产品资料版本变化，请重新预览']));continue
        gaps=skill_jobs.missing(p,item['kind'])
        if gaps:
            blocked.append(dict(item,gaps=gaps));continue
        job=store.enqueue(item['kind'],'product:'+p['id'],{'product':p['id'],'revision':p['revision'],'store':p['facts'].get('store'),'selectionCandidate':current['id'],'candidateFingerprint':item['fingerprint'],'imageProvider':'codex-native'})
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT data FROM products WHERE id=?',(p['id'],)).fetchone();latest=json.loads(row['data'])
            if latest['revision']==p['revision']:
                latest['selectionFlow']={'revision':p['revision'],'status':'ACTIVE','target':'VISUALS','authorizedAt':store.now(),'message':'先生成包装方向，审核后继续整套图片；不自动上品'}
                c.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(latest,ensure_ascii=False),p['id']))
        started.append({'product':p['id'],'job':job['id'],'kind':job['kind'],'status':job['status']})
    return {'started':started,'blocked':blocked}


def advance(product_id):
    p=store.product(product_id);flow=p.get('selectionFlow') or {}
    if not flow or flow.get('status') in ('NEEDS_ATTENTION','STALE','VISUAL_REVIEW','STOPPED'):return
    if flow.get('revision')!=p['revision']:
        state,message='STALE','资料已变化，旧生图授权失效，请重新预览'
    elif any(j.get('product')==product_id and j['status'] in store.ACTIVE for j in store.records('jobs')):return
    elif (p.get('visual') or {}).get('revision')==p['revision']:
        state,message='VISUAL_REVIEW','整套图片已生成，等待人工审核；未上品'
    elif (p.get('packaging') or {}).get('revision')==p['revision'] and p.get('approvedPackaging')==p['packaging']['job']:
        gaps=skill_jobs.missing(p,'visual')
        if gaps:state,message='NEEDS_ATTENTION','请补齐：'+'、'.join(gaps)
        else:
            store.enqueue('visual','product:'+p['id'],{'product':p['id'],'revision':p['revision'],'store':p['facts'].get('store'),'selectionContinuation':True,'imageProvider':flow.get('imageProvider','codex-native')})
            state,message='ACTIVE','包装已审核，继续生成7张主图和12个详情模块'
    else:state,message='PACKAGING_REVIEW','包装方向已生成，等待你审核后继续整套生图'
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT data FROM products WHERE id=?',(product_id,)).fetchone();current=json.loads(row['data'])
        if current['revision']!=p['revision']:return
        current['selectionFlow']=dict(current.get('selectionFlow') or {},status=state,message=message)
        c.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(current,ensure_ascii=False),product_id))


def failure(product_id,revision,message):
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT data FROM products WHERE id=?',(product_id,)).fetchone()
        if not row:return
        p=json.loads(row['data'])
        if (p.get('selectionFlow') or {}).get('revision')!=revision:return
        p['selectionFlow'].update(status='NEEDS_ATTENTION',message=message)
        c.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(p,ensure_ascii=False),product_id))
