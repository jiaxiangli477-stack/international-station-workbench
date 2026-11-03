"""Theme checkbox images: constraints become a concept brief, never seller facts."""
import copy
import json
import uuid
import task_store as store
import topic_workflow as topic
import skill_jobs
import selection_jobs
import weekly_update


def identity(key,business,topic_id):return 'topic:'+key+':'+business+':'+str(topic_id)


def preview_products(items,key):
    if key not in weekly_update.STORES or not isinstance(items,list) or not 1<=len(items)<=10:
        raise ValueError('请选择同店铺1至10个产品')
    planned=[]
    for item in items:
        p=store.product(item.get('id'))
        if not p.get('recruitment') or p['recruitment']['store']!=key or p['facts'].get('store')!=key:
            raise ValueError('不能跨店铺提交')
        if p['revision']!=item.get('revision'):raise ValueError('产品版本已变化，请重新预览')
        kind,gaps=selection_jobs.image_plan(p)
        import concept_direction
        issue=concept_direction.conflict(p)
        if issue:gaps.append(issue)
        design=p.get('designReview') or {}
        if kind=='packaging' and (design.get('revision')!=p['revision'] or design.get('status')!='APPROVED'):
            gaps.append('请先打开“确认包装设计稿”完成设计确认')
        partial=p.get('visualPartial') or {};pending=p.get('visualPending') or {}
        planned.append({'id':p['id'],'title':p['title'],'revision':p['revision'],'kind':kind,'next':kind,'eligible':not gaps,'gaps':gaps,
                        'completedModules':len(partial.get('images',[])) if partial.get('revision')==p['revision'] else 0,
                        'pendingModules':len(pending.get('images',[])) if pending.get('revision')==p['revision'] else 0,
                        'blockedModules':len(partial.get('blockedModules',[])) if partial.get('revision')==p['revision'] else 0})
    return {'store':key,'target':'VISUALS','items':planned,'eligible':sum(x['eligible'] for x in planned)}


def start_products(items,key,acknowledge):
    if acknowledge is not True:raise ValueError('请确认使用GPT原生工具与固定模板制作图片')
    plan=preview_products(items,key);started=[];blocked=[]
    import operations_api
    for item in plan['items']:
        if not item['eligible']:blocked.append(item);continue
        job=operations_api.command({'action':'product.run','id':item['id'],'revision':item['revision'],
                                    'kind':item['kind'],'imageProvider':'codex-native','acknowledgeExecution':True})
        started.append({'product':item['id'],'job':job['id']})
    return {'started':started,'blocked':blocked,'target':'VISUALS'}


def prepare(target,key,existing=None):
    p=copy.deepcopy(existing) if existing else {
        'id':None,'source':identity(key,target['businessType'],target['id']),'title':target['title'],
        'facts':{'mode':'concept','market':'','form':'','spec':'','formula':'','price':'','moq':'','store':key,'own_image':'','design':''},
        'revision':1,'stage':'FACTS','visual':None,'draft':None,'events':[],'created':store.now(),
        'references':[{'name':'征品主题 '+str(target['id']),'image_url':target.get('image'),'scope':'征品视觉与属性要求，非我方产品事实'}]}
    if not p.get('recruitment'):
        p['recruitment']={'store':key,'businessType':target['businessType'],'topicId':str(target['id']),
                          'snapshot':copy.deepcopy(target),'fingerprint':topic.fingerprint(target),'captured':store.now(),'entries':{}}
    if p['facts'].get('mode')!='real':
        forms=set()
        for row in topic.requirements(target):
            if row['name'].strip().casefold() in ('dosage form','剂型'):forms.update(v for v in row['expected'] if v)
        brief='按征品主题“'+target['title']+'”设计原创内部概念包装。参考图用于商品主体与包装形式，不复制品牌。'
        brief+='主题要求：'+json.dumps(target.get('requirements') or [],ensure_ascii=False)
        brief+='。配方、规格、价格和证书尚未确认为我方事实，不声称已满足征品或市场准入。'
        design={'scope':'INTERNAL_B2B','form':next(iter(forms)) if len(forms)==1 else '',
                'brief':brief,'referenceImage':target.get('image',''),'sourceFingerprint':topic.fingerprint(target)}
        prior=p['recruitment'].get('conceptDesign') or {}
        selected=prior.get('directionSelection') or {}
        if selected.get('sourceFingerprint')==design['sourceFingerprint']:
            design=copy.deepcopy(prior)
        if p['recruitment'].get('conceptDesign')!=design:
            p['recruitment']['conceptDesign']=design
            if not p['facts'].get('design'):p['facts']['design']=brief
            if existing:
                store.archive_draft(p, 'recruitment_reference_changed')
                p.update(revision=p['revision']+1,stage='FACTS',approvedPackaging=None,approvedVisual=None,draft=None)
            p['events'].append({'time':store.now(),'message':'征品要求已作为概念设计任务书；未填入我方属性事实，未执行平台检测'})
    return p


def preview(key,business,ids):
    if key not in weekly_update.STORES or business not in topic.BUSINESSES:raise ValueError('请选择有效店铺和征品类型')
    if not isinstance(ids,list) or not 1<=len(ids)<=10 or any(not str(i).isdigit() for i in ids):raise ValueError('每批请选择1至10个征品主题')
    products={p['source']:p for p in store.records('products')};jobs=store.records('jobs');items=[]
    for topic_id in dict.fromkeys(str(i) for i in ids):
        target,_=topic.cached_topic(key,topic_id,business)
        original=products.get(identity(key,business,topic_id));p=prepare(target,key,original)
        kind,gaps=selection_jobs.image_plan(p)
        import concept_direction
        issue=concept_direction.conflict(p)
        if issue:gaps.append(issue)
        if p['facts'].get('store') not in ('',key):gaps.append('目标店铺与征品来源不一致，请先核对产品资料')
        if original and topic.fingerprint(original['recruitment']['snapshot'])!=topic.fingerprint(target):
            gaps.append('主题要求已变化，请先核对原产品档案')
        if original and any(j.get('product')==original['id'] and j['status'] in store.ACTIVE and j.get('revision')!=p['revision'] for j in jobs):
            gaps.append('旧版本任务仍在执行，完成后再提交')
        if original and any(j.get('product')==original['id'] and j['status'] in store.ACTIVE and
                            (j.get('kind')!=kind or j.get('recruitmentImageFingerprint')!=topic.fingerprint(target)) for j in jobs):
            gaps.append('该产品已有其他任务在执行，完成后再生图')
        items.append({'topic':topic_id,'title':target['title'],'fingerprint':topic.fingerprint(target),
                      'product':original['id'] if original else None,'revision':original['revision'] if original else None,
                      'preparedRevision':p['revision'],'kind':kind,'eligible':not gaps,'gaps':gaps,
                      'designForm':(p['recruitment'].get('conceptDesign') or {}).get('form') or p['facts'].get('form','') or ('参照主题样例（实际剂型待核）' if target.get('image') else ''),
                      'scope':'内部B2B概念；目标市场与实际产品资料另行确认' if p['facts'].get('mode')!='real' else '使用真实产品资料'})
    return {'store':key,'businessType':business,'items':items,'eligible':sum(x['eligible'] for x in items)}


def start(key,business,items,acknowledge):
    if acknowledge is not True:raise ValueError('请确认本批次使用已有生图服务额度')
    if not isinstance(items,list) or not items or len(items)>10 or any(not isinstance(i,dict) for i in items):raise ValueError('执行预览无效')
    plan=preview(key,business,[i.get('topic') for i in items]);old={str(i.get('topic')):i for i in items};jobs=store.records('jobs')
    for item in plan['items']:
        previous=old[item['topic']]
        retry=not previous.get('product') and any(j.get('product')==item['product'] and j.get('revision')==item['preparedRevision'] and j.get('recruitmentImageFingerprint')==item['fingerprint'] and j['status'] in store.ACTIVE for j in jobs)
        if any(item.get(k)!=previous.get(k) for k in ('fingerprint','kind')) or (not retry and any(item.get(k)!=previous.get(k) for k in ('product','revision','preparedRevision'))):
            raise ValueError('预览后主题或产品资料已变化，请重新预览')
    if not skill_jobs.capability()['available']:raise ValueError('本机生图执行器不可用，未提交任务')
    started=[];blocked=[]
    for item in plan['items']:
        if not item['eligible']:blocked.append(item);continue
        target,_=topic.cached_topic(key,item['topic'],business)
        if topic.fingerprint(target)!=item['fingerprint']:raise ValueError('征品要求已变化，请重新预览')
        with store.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT data FROM products WHERE source=?',(identity(key,business,item['topic']),)).fetchone()
            original=json.loads(row['data']) if row else None
            if original and original['revision']!=item['revision']:raise ValueError('产品资料已变化，请重新预览')
            p=prepare(target,key,original)
            if not p['id']:p['id']='P-'+uuid.uuid4().hex[:12]
            active=conn.execute("SELECT data FROM jobs WHERE scope=? AND status IN ('QUEUED','RUNNING')",('product:'+p['id'],)).fetchone()
            if active:
                prior=json.loads(active['data'])
                if prior.get('kind')!=item['kind'] or prior.get('revision')!=p['revision'] or prior.get('recruitmentImageFingerprint')!=item['fingerprint']:
                    raise ValueError('该产品已有其他活动任务，请完成后重新预览')
            if p.get('productionFlow'):p['productionFlow'].update(status='STOPPED',message='已切换为仅生图，本次不自动保存草稿')
            p['selectionFlow']={'revision':p['revision'],'status':'ACTIVE','target':'VISUALS','authorizedAt':store.now(),
                                'message':'征品概念包装先做，审核后继续整套图片；未保存草稿或发布'}
            conn.execute('INSERT INTO products VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(p['id'],p['source'],json.dumps(p,ensure_ascii=False)))
        job=store.enqueue(item['kind'],'product:'+p['id'],{'product':p['id'],'revision':p['revision'],'store':key,
                       'selectionContinuation':True,'recruitmentImageFingerprint':item['fingerprint'],'imageProvider':'codex-native'})
        started.append({'product':p['id'],'job':job['id'],'kind':job['kind']})
    return {'started':started,'blocked':blocked}


def stop(product_id):
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT data FROM products WHERE id=?',(product_id,)).fetchone()
        if not row:raise ValueError('任务不存在')
        p=json.loads(row['data'])
        if not p.get('recruitment') or not p.get('selectionFlow'):raise ValueError('不是征品生图任务')
        p['selectionFlow'].update(status='STOPPED',message='已停止后续阶段；当前阶段的产物保留待审核')
        c.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(p,ensure_ascii=False),product_id))
    return p
