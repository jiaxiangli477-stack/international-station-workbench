"""Bounded, explicit draft-only chains; manual image review remains a stage gate."""
import json
import task_store as store
import topic_workflow as topic
import skill_jobs

FACT_NAMES={'market':'目标市场','form':'产品剂型','spec':'规格','formula':'真实配方','price':'价格','moq':'起订量','store':'店铺','own_image':'真实产品图','design':'设计要求'}


def plan(product):
    facts=product['facts'];r=topic.report(product)
    if not r:raise ValueError('只能编排已关联征品的产品任务')
    if product.get('draft',{} ) and product['draft'].get('readback_verified'):
        return {'eligible':False,'next':'done','gaps':['已保存草稿，等待平台检测，不重复制作']}
    gaps=[FACT_NAMES[k] for k in ('market','form','spec','formula','price','moq','store','design') if not facts.get(k) or facts[k]=='TO_CONFIRM']
    if facts.get('mode')!='real':gaps.append('真实产品资料模式')
    if not facts.get('own_image') or facts['own_image'].strip().upper()=='TO_CONFIRM':gaps.append('真实产品图')
    gaps.extend(row['name'] for row in r['rows'] if row['kind']!='image' and row['status'] not in ('MATCHED','MANUAL'))
    if facts.get('store')!=r['store']:gaps.append('目标店铺与主题来源不一致')
    visual=product.get('visual') or {}
    if visual.get('revision')==product['revision']:
        if product.get('approvedVisual')!=visual.get('job'):
            return {'eligible':not gaps,'next':'review','gaps':gaps}
        gaps.extend(FACT_NAMES.get(x,x) for x in skill_jobs.missing(product,'listing'))
        return {'eligible':not gaps,'next':'listing','gaps':list(dict.fromkeys(gaps))}
    gaps.extend(FACT_NAMES.get(x,x) for x in skill_jobs.missing(product,'visual'))
    return {'eligible':not gaps,'next':'visual','gaps':list(dict.fromkeys(gaps))}


def preview(items, key):
    if not isinstance(items,list) or not items or len(items)>10:
        raise ValueError('每次请选择1至10个明确的产品任务')
    seen=set();results=[]
    for item in items:
        p=store.product(item.get('id'))
        if p['id'] in seen:continue
        seen.add(p['id'])
        if not p.get('recruitment') or p['recruitment']['store']!=key or p['facts'].get('store')!=key:
            raise ValueError('不能跨店铺提交征品制作')
        if p['revision']!=item.get('revision'):raise ValueError('产品资料已变化，请刷新后重新预览')
        results.append(dict(plan(p),id=p['id'],title=p['title'],revision=p['revision']))
    return {'store':key,'items':results,'eligible':sum(x['eligible'] for x in results),
            'target':'DRAFT','reviewRequired':True,'message':'图片生成后需审核，审核后继续草稿；草稿保存后停止，不发布。'}


def update(product_id, changes):
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT data FROM products WHERE id=?',(product_id,)).fetchone()
        if not row:raise ValueError('产品任务不存在')
        p=json.loads(row['data']);p['productionFlow']=dict(p.get('productionFlow') or {},**changes,updated=store.now())
        c.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(p,ensure_ascii=False),product_id))
    return p


def advance(product_id):
    p=store.product(product_id);flow=p.get('productionFlow') or {}
    if not flow or flow.get('status') in ('STOPPED','NEEDS_ATTENTION','DRAFT_SAVED','STALE'):return
    if flow.get('revision')!=p['revision']:
        update(product_id,{'status':'STALE','message':'资料版本变化，旧的连续制作授权已失效'});return
    if p.get('draft') and p['draft'].get('readback_verified'):
        update(product_id,{'status':'DRAFT_SAVED','message':'草稿已保存并回读；等待证书绑定及平台征品检测'});return
    if any(j.get('product')==product_id and j['status'] in store.ACTIVE for j in store.records('jobs')):return
    step=plan(p)
    if not step['eligible']:
        update(product_id,{'status':'NEEDS_ATTENTION','message':'、'.join(step['gaps'])[:500]});return
    if step['next']=='review':
        update(product_id,{'status':'WAITING_VISUAL_REVIEW','message':'图片已生成，待审核后继续保存草稿'});return
    store.enqueue(step['next'],'product:'+p['id'],{'product':p['id'],'revision':p['revision'],'store':p['facts']['store'],'recruitmentChain':True})
    update(product_id,{'status':'ACTIVE','message':'等待生成图片' if step['next']=='visual' else '等待填写并保存后台草稿'})


def start(items, key, acknowledge):
    if acknowledge is not True:raise ValueError('请确认本批次使用已有服务额度，并仅保存草稿')
    previewed=preview(items,key)
    if not skill_jobs.capability()['available']:raise ValueError('本机 Skill 执行器不可用，未提交生图任务')
    started=[];blocked=[p for p in previewed['items'] if not p['eligible']]
    eligible=[p for p in previewed['items'] if p['eligible']]
    with store.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        for item in eligible:
            p=json.loads(conn.execute('SELECT data FROM products WHERE id=?',(item['id'],)).fetchone()['data'])
            if p['revision']!=item['revision']:raise ValueError('预览后产品资料已变化，请重新预览')
            flow=p.get('productionFlow') or {}
            if flow.get('revision')!=p['revision'] or flow.get('status') not in ('ACTIVE','WAITING_VISUAL_REVIEW'):
                p['productionFlow']={'revision':p['revision'],'status':'ACTIVE','target':'DRAFT','authorizedAt':store.now(),'updated':store.now()}
                conn.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(p,ensure_ascii=False),p['id']))
    for item in eligible:
        advance(item['id']);started.append(item['id'])
    return {'started':started,'blocked':blocked,'target':'DRAFT'}


def stop(product_id):
    p=store.product(product_id)
    if not p.get('recruitment'):raise ValueError('不是征品任务')
    return update(product_id,{'status':'STOPPED','message':'已停止后续阶段；正在执行的任务会完成当前阶段，不再自动交接'})
