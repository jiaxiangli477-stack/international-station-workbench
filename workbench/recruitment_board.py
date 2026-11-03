"""Cross-page local matching against seller evidence; never assume a platform pass."""
import copy
import json
import uuid
import task_store as store
import topic_workflow as topic


def transfer_entries(source, target):
    rec=source.get('recruitment') or {}
    original={r['key']:r for r in topic.requirements(rec.get('snapshot') or {})}
    values=rec.get('entries',{})
    entries={}
    direct=(rec.get('topicId')==str(target['id']) and rec.get('businessType')==target['businessType']
            and topic.fingerprint(rec.get('snapshot') or {})==topic.fingerprint(target))
    for row in topic.requirements(target):
        old=original.get(row['key']);entry=values.get(row['key'])
        if not old or not entry or not entry.get('evidence') or row['kind']=='manual':continue
        if row['kind']=='image' and not direct:continue
        if row['kind']=='attribute' and str(old.get('categoryId'))!=str(row.get('categoryId')):continue
        entries[row['key']]=copy.deepcopy(entry)
    return entries


def evaluate(target, key, products):
    candidates=[p for p in products if p.get('facts',{}).get('store')==key and
                (p['facts'].get('mode')=='real' or
                 (p.get('recruitment',{}).get('topicId')==str(target['id']) and p.get('recruitment',{}).get('businessType')==target['businessType']))]
    possibilities=[]
    for source in candidates or [None]:
        facts=copy.deepcopy(source['facts']) if source else {'store':key,'mode':'concept'}
        p={'facts':facts,'recruitment':{'store':key,'topicId':str(target['id']),'businessType':target['businessType'],
           'captured':store.now(),'snapshot':target,'fingerprint':topic.fingerprint(target),
           'entries':transfer_entries(source,target) if source else {}}}
        report=topic.report(p)
        pending=[r for r in report['rows'] if r['kind']!='image' and r['status'] not in ('MATCHED','MANUAL')]
        image=any(r['kind']=='image' and r['status']!='MATCHED' for r in report['rows'])
        real=facts.get('mode')=='real'
        names={'market':'目标市场','form':'剂型','spec':'规格','formula':'配方','price':'价格','moq':'起订量','design':'设计要求','own_image':'真实产品图'}
        missing_facts=[name for field,name in names.items() if not str(facts.get(field,'')).strip() or str(facts.get(field,'')).strip().upper()=='TO_CONFIRM']
        can_prepare=not pending and real and not missing_facts
        item={'topicId':str(target['id']),'businessType':target['businessType'],'title':target['title'],'image':target.get('image',''),
              'fingerprint':topic.fingerprint(target),'sourceProduct':source['id'] if source else None,
              'sourceTitle':source['title'] if source else '', 'sourceRevision':source['revision'] if source else None,
              'matchedCount':report['matchedCount'],'totalRules':len(report['rows']),
              'pendingCount':sum(r['status']=='TO_CONFIRM' for r in report['rows']),
              'mismatchCount':sum(r['status']=='MISMATCH' for r in report['rows']), 'manualCount':report['manualCount'],
              'canPrepare':can_prepare,'platformStatus':'NOT_RUN',
              'status':'READY' if can_prepare and not image else 'IMAGE_REVIEW' if can_prepare else 'MISMATCH' if any(r['status']=='MISMATCH' for r in pending) else 'NEEDS_DATA',
              'issues':[{'key':r['key'],'name':r['name'],'status':r['status'],'reason':r['message'],'fix':r['fix']} for r in report['rows'] if r['status']!='MATCHED']}
        if not real:item['issues'].insert(0,{'name':'真实产品资料','reason':'当前没有可复用的已确认真实产品资料','status':'TO_CONFIRM'})
        elif missing_facts:item['issues'].insert(0,{'name':'上品资料','reason':'缺少：'+'、'.join(missing_facts),'status':'TO_CONFIRM'})
        direct=bool(source and source.get('recruitment',{}).get('topicId')==str(target['id']) and source.get('recruitment',{}).get('businessType')==target['businessType'])
        possibilities.append(((int(can_prepare),int(real),report['matchedCount'],-len(pending),int(direct)),item))
    return max(possibilities,key=lambda pair:pair[0])[1]


def latest(summary=False):
    with store.db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS recruitment_runs(scope TEXT PRIMARY KEY,data TEXT)')
        runs=[json.loads(r['data']) for r in c.execute('SELECT data FROM recruitment_runs')]
        return [{k:v for k,v in run.items() if k!='items'} for run in runs] if summary else runs


def read(key, business, page=1, state='', title=''):
    run=next((r for r in latest() if r['store']==key and r['businessType']==business),None)
    if not run:return {'status':'NOT_RUN','items':[],'page':1,'pages':1,'count':0}
    rows=run['items']
    if state=='preparable':rows=[r for r in rows if r['canPrepare']]
    elif state:rows=[r for r in rows if r['status']==state]
    if title:rows=[r for r in rows if str(title).casefold() in (r['title']+' '+r['sourceTitle']).casefold()]
    pages=max(1,(len(rows)+19)//20)
    try:page=max(1,min(pages,int(page)))
    except (TypeError,ValueError):page=1
    return dict({k:v for k,v in run.items() if k!='items'},status='SUCCESS',items=rows[(page-1)*20:page*20],page=page,pages=pages,count=len(rows))


def scan(key, query):
    import recruitment
    import weekly_update
    if key not in weekly_update.STORES or query.get('businessType') not in topic.BUSINESSES:
        raise ValueError('请选择已绑定店铺和征品类型')
    clean={k:str(query.get(k,''))[:180] for k in ('businessType','tag','category','country','title','recent','sort')}
    clean.update(page=1,_unique=True)
    first=recruitment.read_page(key,clean)
    if first.get('status')!='SUCCESS':raise ValueError('征品快照不可用，请先刷新完整列表')
    products=store.records('products');results=[]
    for page in range(1,first['pagination']['totalPages']+1):
        part=first if page==1 else recruitment.read_page(key,dict(clean,page=page))
        if part.get('status')!='SUCCESS':raise ValueError('本地跨页读取未完成，未覆盖上次匹配结果')
        results.extend(evaluate(t,key,products) for t in part['records'])
    run={'id':uuid.uuid4().hex,'store':key,'businessType':clean['businessType'],'created':store.now(),
         'filters':{k:v for k,v in clean.items() if not k.startswith('_') and k!='page'},
         'snapshotTime':first.get('collectedAt'),'sourceProducts':len([p for p in products if p.get('facts',{}).get('store')==key and p['facts'].get('mode')=='real']),
         'total':len(results),'ready':sum(r['canPrepare'] for r in results),'items':results,
         'boundary':'本地真实资料对照，图片另行审核；平台征品检测未执行'}
    latest()
    with store.db() as c:
        c.execute('INSERT OR REPLACE INTO recruitment_runs VALUES(?,?)',(key+':'+clean['businessType'],json.dumps(run,ensure_ascii=False)))
    return run


def adopt(run_id, topic_id):
    run=next((r for r in latest() if r['id']==run_id),None)
    if not run:raise ValueError('匹配批次已更新，请重新筛选匹配')
    item=next((x for x in run['items'] if x['topicId']==str(topic_id)),None)
    if not item or not item['sourceProduct'] or not item['canPrepare']:
        raise ValueError('该主题尚无可用于制作的匹配产品，请先补齐实际资料')
    source=store.product(item['sourceProduct'])
    if source['revision']!=item['sourceRevision']:raise ValueError('产品资料已更新，请重新匹配')
    target,_=topic.cached_topic(run['store'],topic_id,run['businessType'])
    if topic.fingerprint(target)!=item['fingerprint']:raise ValueError('主题要求已变化，请重新匹配')
    current=evaluate(target,run['store'],[source])
    if not current['canPrepare']:raise ValueError('当前资料不再符合制作条件，请重新匹配')
    identity='topic:'+run['store']+':'+run['businessType']+':'+str(topic_id)
    p=store.create_product(identity,source['title'],facts={'store':run['store'],'mode':'concept'})
    if p['id']==source['id']:return p
    if p.get('recruitment',{}).get('entries') or any(p['facts'].get(k) for k in ('formula','spec','market','own_image')):
        raise ValueError('目标征品档案已有资料，请打开原档案核对，未自动覆盖')
    p=topic.attach(p,run['store'],target)
    p['facts']=copy.deepcopy(source['facts']);p['revision']+=1
    p['recruitment']['entries']=transfer_entries(source,target)
    p['events'].append({'time':store.now(),'message':'从同店铺产品 '+source['id']+' V'+str(source['revision'])+' 复用有依据的真实资料；图片仍需独立审核'})
    return store.save_product(p)
