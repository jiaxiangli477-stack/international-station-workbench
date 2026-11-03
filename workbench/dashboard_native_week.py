"""Platform-native weekly products. Never reconstruct weekly UV from daily records."""
from pathlib import Path
from datetime import date,datetime,timezone,timedelta
from urllib.parse import urlsplit,parse_qs
import json,hashlib,re,uuid

FIELDS={'impressions':'sumProdShowNum','clicks':'sumProdClickNum','ctr':'sumProdClickRate','total_imps':'totalImpsCnt','total_clk':'totalClkCnt','inquiries':'sumProdFbNum','tm':'atmFbUv','orders':'crtOrd','gmv':'rtsOnlineAmt','ad_imps':'adImpsCnt','ad_clk':'adClkCnt'}
def read(p):return json.loads(Path(p).read_text('utf-8-sig'))
def write(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(v,ensure_ascii=False),encoding='utf-8');tmp.replace(p)
def number(v):
    if v is None or v=='':return None
    try:
        import math
        n=float(v);return n if math.isfinite(n) else None
    except (TypeError,ValueError):return None
def checked(response):
    if not isinstance(response,dict) or response.get('success') is not True:raise ValueError('平台自然周接口未成功')
    d=response if isinstance(response.get('data'),list) else response.get('data')
    if not isinstance(d,dict) or not isinstance(d.get('data'),list) or type(d.get('recordCount')) is not int or d['recordCount']<0:raise ValueError('平台自然周分页格式无效')
    q=parse_qs(urlsplit(d.get('downloadUrl','')).query)
    if q.get('statisticsType')!=['week'] or len(q.get('statDate',[]))!=1:raise ValueError('返回数据不是平台自然周，停止生成')
    date.fromisoformat(q['statDate'][0]);return d,q['statDate'][0]
def confirmation(workspace,start,end):
    if (date.fromisoformat(end)-date.fromisoformat(start)).days!=6:raise ValueError('平台自然周必须有连续7日，边界以平台显示为准')
    p=Path(workspace)/'raw/platform_native_week_windows.json'
    for w in read(p).get('windows',[]) if p.exists() else []:
        if (w.get('start'),w.get('end'))==(start,end) and w.get('source')=='platform-date-picker' and w.get('confirmed') is True and w.get('evidence'):
            date.fromisoformat(w['statDate']);return w
    raise ValueError('平台自然周起止日期尚未与页面选择器核对；不逐日汇总、不把接口日期标记猜成周起止')
def directory(workspace,start):return Path(workspace)/'raw/native_week_products'/start
def collect_week(workspace,store,start,end,call,guard=lambda:None):
    write(Path(workspace)/'raw/platform-native-week-policy.json',{'mode':'platform_native_week','dailyFallback':False})
    binding=confirmation(workspace,start,end);folder=directory(workspace,start);run=folder/uuid.uuid4().hex
    seen={};pages=[];total=None
    for page in range(1,10001):
        guard();params={'statisticsType':'week','orderBy':'inquiries','orderModel':'DESC','pageNo':page,'pageSize':20}
        response=call('data_advisor_shop_product',{'shopProductQueryParam':params});data,token=checked(response);guard()
        if token!=binding['statDate']:raise ValueError('平台返回的是另一个自然周；接口不支持此历史周选择，不改日期标签、不回退日汇总')
        if total is not None and total!=data['recordCount']:raise ValueError('平台分页总数变化，停止')
        total=data['recordCount'];rows=data['data']
        f=run/('page_%04d.json'%page);write(f,response)
        pages.append({'file':f.relative_to(folder).as_posix(),'sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
        for row in rows:
            pid=str(row.get('id') or '')
            if not re.fullmatch(r'\d{1,32}',pid) or pid in seen:raise ValueError('平台自然周产品ID缺失或分页重复')
            seen[pid]=row
        if len(seen)>total or not rows and len(seen)<total:raise ValueError('平台自然周分页数量不一致')
        if len(seen)==total:break
    else:raise ValueError('平台自然周分页尚未完成')
    guard();m={'format':'dashboard-platform-native-week/v1','store':str(store),'start':start,'end':end,'statDate':binding['statDate'],'binding':binding,'records':len(seen),'pages':pages,'mode':'platform_native_week','tmPolicy':'platform_week_original','completed':True,'collectedAt':datetime.now(timezone.utc).isoformat()}
    write(folder/'manifest.json',m);return m
def snapshot(workspace,start,end,store=None):
    folder=directory(workspace,start);f=folder/'manifest.json'
    if not f.exists():return None
    m=read(f)
    if m.get('format')!='dashboard-platform-native-week/v1' or m.get('completed') is not True or (m.get('start'),m.get('end'))!=(start,end) or store is not None and str(m.get('store'))!=str(store):raise ValueError('平台自然周快照店铺/期间无效')
    binding=m.get('binding',{})
    if binding.get('source')!='platform-date-picker' or binding.get('confirmed') is not True or not binding.get('evidence') or (binding.get('start'),binding.get('end'),binding.get('statDate'))!=(start,end,m.get('statDate')):raise ValueError('平台自然周缺少页面日期核对证据')
    seen={}
    for i,item in enumerate(m.get('pages',[]),1):
        p=(folder/item['file']).resolve()
        if not p.is_relative_to(folder.resolve()) or p.name!='page_%04d.json'%i or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('平台自然周分页路径或哈希无效')
        d,token=checked(read(p))
        if token!=m['statDate'] or d['recordCount']!=m['records']:raise ValueError('平台自然周返回日期或总数变化')
        for row in d['data']:
            pid=str(row.get('id') or '')
            if not re.fullmatch(r'\d{1,32}',pid) or pid in seen:raise ValueError('平台自然周ID不完整')
            seen[pid]=row
    if not m.get('pages') or len(seen)!=m['records']:raise ValueError('平台自然周分页未完成')
    return m,seen
def product_rows(workspace,start,end,store):
    result=snapshot(workspace,start,end,store)
    if result is None:return []
    out=[]
    for pid,row in result[1].items():
        p={k:number(row.get(v)) for k,v in FIELDS.items()}
        p.update(product_id=pid,title=row.get('prodName') or row.get('subject') or '',category=row.get('cateName') or '',prod_level=row.get('prodLevel3'),main_image=row.get('prodImage') or '',detail_url=row.get('detailUrl') or row.get('productDetailUrl'),first_seen_at=None,crt_time=(row.get('crtTime') or '')[:10],moq=row.get('minOrderQuantity'),price_range=row.get('priceRange') or row.get('price'),tm_daily_sum=None,observation_days=None)
        p['opp']=p['inquiries']+p['tm'] if p['inquiries'] is not None and p['tm'] is not None else None
        p['total_ctr']=round(100*p['total_clk']/p['total_imps'],2) if p['total_imps'] and p['total_clk'] is not None else 0 if p['total_imps']==0 and p['total_clk']==0 else None
        p['ctr']=100*p['ctr'] if p['ctr'] is not None else None
        p.update(label='有商机' if p['opp'] and p['opp']>0 else '待复核',label_typ='neutral',ad_label='广告数据缺失' if p['ad_clk'] is None else '有广告点击' if p['ad_clk']>0 else '无广告点击',ad_typ='neutral',sug='平台自然周原始指标；按询盘、点击、曝光排序。')
        out.append(p)
    return out
def verify_rows(workspace,start,end,rows,store=None):
    result=snapshot(workspace,start,end,store)
    if result is None:
        if rows:raise ValueError('缺少平台自然周原始分页，不接收日汇总或旧数据库冒充周数据')
        return {'status':'NOT_COLLECTED','mode':'platform_native_week','sourceWindow':[start,end]}
    m,items=result
    if {p['product_id'] for p in rows}!=set(items) or len(rows)!=len(items):raise ValueError('面板与平台自然周产品集合不符')
    for p in rows:
        for k,source in FIELDS.items():
            if k=='ctr':continue
            if p.get(k)!=number(items[p['product_id']].get(source)):raise ValueError('平台自然周指标不一致：'+k)
    return {'status':'VERIFIED','mode':'platform_native_week','tmPolicy':'platform_week_original','records':m['records'],'pages':len(m['pages']),'sourceWindow':[start,end],'statDate':m['statDate'],'collectedAt':m['collectedAt']}
def collect_all(workspace,store,call,guard=lambda:None,publish_latest_alias=True):
    workspace=Path(workspace);w=read(workspace/'raw/_window.json');windows=w['weeks'];out=[]
    write(workspace/'raw/platform-native-week-policy.json',{'mode':'platform_native_week','dailyFallback':False,'availabilityDelayDays':2,'delaySource':'user-stated T+2; actual readiness must be checked on platform'})
    as_of=date.fromisoformat(w['as_of'])
    for p in windows:
        if date.fromisoformat(p['week_end'])>as_of-timedelta(days=2):raise ValueError('按T+2等待完整平台自然周出数，不取未出齐的周数据')
    # Validate every requested period before any collection; never silently fall back to daily sums.
    for w in windows:confirmation(workspace,w['week_start'],w['week_end'])
    for w in sorted(windows,key=lambda x:x['week_start']):
        prior=snapshot(workspace,w['week_start'],w['week_end'],store)
        m=prior[0] if prior else collect_week(workspace,store,w['week_start'],w['week_end'],call,guard)
        out.append(m)
    return out
