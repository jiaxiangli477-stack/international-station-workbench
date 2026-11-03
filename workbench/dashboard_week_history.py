"""Collect independently verifiable natural-week product snapshots, without changing source DBs."""
from __future__ import annotations
from datetime import date, datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit,parse_qs

FIELDS={'impressions':'sumProdShowNum','clicks':'sumProdClickNum','ctr':'sumProdClickRate',
        'total_imps':'totalImpsCnt','total_clk':'totalClkCnt','inquiries':'sumProdFbNum',
        'tm':'atmFbUv','orders':'crtOrd','gmv':'rtsOnlineAmt','ad_imps':'adImpsCnt','ad_clk':'adClkCnt'}

def read(path):return json.loads(Path(path).read_text('utf-8-sig'))
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');temp.replace(path)
def num(value):
    if value is None or value=='':return None
    try:
        value=float(value)
        import math
        return value if math.isfinite(value) else None
    except (ValueError,TypeError):return None
def check_week(start,end):
    a,b=date.fromisoformat(start),date.fromisoformat(end)
    if a.weekday()!=0 or (b-a).days!=6:raise ValueError('必须为完整自然周')
def period_dir(workspace,start,end):
    check_week(start,end)
    return Path(workspace)/'raw/weekly_products'/start

def checked_response(response,day):
    data=response.get('data') if isinstance(response,dict) else None
    if not isinstance(response,dict) or response.get('success') is not True or not isinstance(data,dict):raise ValueError('日产品接口未成功')
    returned=parse_qs(urlsplit(data.get('downloadUrl','')).query)
    if returned.get('statDate')!=[day] or returned.get('statisticsType')!=['day']:raise ValueError('返回统计日期与请求不一致')
    if type(data.get('recordCount')) is not int or data['recordCount']<0 or not isinstance(data.get('data'),list):raise ValueError('日分页数据格式无效')
    return data

def count_audit(run,day,items,pages,total,call,guard):
    """A short final page may expose a stale recordCount. Never silently change it."""
    def request(page,order):
        return call('data_advisor_shop_product',{'shopProductQueryParam':{'statisticsType':'day','statDate':day,'orderBy':order,'orderModel':'DESC','pageNo':page,'pageSize':20}})
    terminal=request(len(pages)+1,'crtTime');data=checked_response(terminal,day)
    if data.get('recordCount')!=total or data.get('data')!=[]:raise ValueError('数量异常且没有空尾页，停止')
    endfile=run/day/'terminal.json';write(endfile,terminal)
    secondary={};alternate=[];folder=run/day/'alternate';folder.mkdir()
    for page in range(1,len(pages)+2):
        guard();response=request(page,'inquiries');data=checked_response(response,day)
        if data.get('recordCount')!=total:raise ValueError('交叉枚举时源总数改变')
        f=folder/('page_%04d.json'%page);write(f,response)
        alternate.append({'file':f.relative_to(run.parent).as_posix(),'sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
        if not data.get('data'):break
        for r in data['data']:
            pid=str(r.get('id') or '')
            if not pid.isdigit() or pid in secondary:raise ValueError('交叉枚举编号重复')
            secondary[pid]=r
    else:raise ValueError('交叉枚举未到空尾页')
    if set(secondary)!=set(items) or any(any(num(items[pid].get(f))!=num(secondary[pid].get(f)) for f in FIELDS.values()) for pid in items):raise ValueError('两种排序枚举不一致，拒绝数量异常')
    guard()
    return {'day':day,'declaredRecords':total,'enumeratedRecords':len(items),'terminal':endfile.relative_to(run.parent).as_posix(),
            'terminalSha256':hashlib.sha256(endfile.read_bytes()).hexdigest(),'alternatePages':alternate,'method':'two_orders_same_ids_and_metrics_with_empty_tail'}

def collect_day(run,day,call,guard):
    guard();folder=run/day;folder.mkdir()
    seen={};total=None;pages=[]
    for page in range(1,10001):
        response=call('data_advisor_shop_product',{'shopProductQueryParam':{
            'statisticsType':'day','statDate':day,'pageNo':page,
            'pageSize':20,'orderBy':'crtTime','orderModel':'DESC'}})
        data=response.get('data') if isinstance(response,dict) else None
        if response.get('success') is not True or not isinstance(data,dict):raise ValueError('周产品接口未成功；未发布完整快照')
        returned=parse_qs(urlsplit(data.get('downloadUrl','')).query)
        if returned.get('statDate')!=[day] or returned.get('statisticsType')!=['day']:raise ValueError('返回统计日期与请求不一致；拒绝把最新周充当历史周')
        count=data.get('recordCount');rows=data.get('data')
        if type(count) is not int or count<0 or not isinstance(rows,list):raise ValueError('周产品分页格式无效')
        if total is not None and total!=count:raise ValueError('分页总数变化，停止生成')
        total=count
        for row in rows:
            pid=str(row.get('id') or '')
            if not re.fullmatch(r'\d{1,32}',pid) or pid in seen:raise ValueError('产品编号缺失或分页重复')
            seen[pid]=row
        if not rows and len(seen)<total:raise ValueError('产品分页不完整')
        path=folder/('page_%04d.json'%page);write(path,response)
        pages.append({'file':path.relative_to(run.parent).as_posix(),'day':day,'page':page,'records':total,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        if len(seen)>total:
            if len(rows)>=20:raise ValueError('超过源总数且不是短尾页')
            warning=count_audit(run,day,seen,pages,total,call,guard)
            return {'day':day,'items':seen,'pages':pages,'countWarning':warning}
        if len(seen)==total:break
    else:raise ValueError('超出分页上限，未完成')
    guard();print('自然日 %s：%d 产品 / %d 页'%(day,len(seen),len(pages)),flush=True)
    return {'day':day,'items':seen,'pages':pages}

def aggregate_days(days):
    ids=set().union(*(set(d['items']) for d in days));out={}
    additive=set(FIELDS.values())-{'sumProdClickRate','atmFbUv'}
    for pid in sorted(ids):
        found=[(d['day'],d['items'][pid]) for d in days if pid in d['items']]
        row=dict(found[-1][1]);created=(row.get('crtTime') or '')[:10]
        covered=all(pid in d['items'] or bool(created and d['day']<created) for d in days)
        for key in additive:
            vals=[num(r.get(key)) for _,r in found]
            row[key]=sum(vals) if covered and all(v is not None for v in vals) else None
        tm=[num(r.get('atmFbUv')) for _,r in found]
        row['tmDailySum']=sum(tm) if covered and all(v is not None for v in tm) else None
        row['atmFbUv']=None  # Daily unique visitors cannot be summed into weekly uniques.
        imp,clk=row.get('sumProdShowNum'),row.get('sumProdClickNum')
        row['sumProdClickRate']=clk/imp if imp and clk is not None else 0 if imp==0 and clk==0 else None
        row['observationDays']=len(found);out[pid]=row
    return out

def collect_week(workspace,store,start,end,call,guard=lambda:None):
    """The week API ignores dates; seven verified day queries form a natural week."""
    check_week(start,end);folder=period_dir(workspace,start,end)
    run=folder/uuid.uuid4().hex;run.mkdir(parents=True)
    dates=[(date.fromisoformat(start)+timedelta(days=i)).isoformat() for i in range(7)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        days=list(pool.map(lambda day:collect_day(run,day,call,guard),dates))
    guard();items=aggregate_days(days);pages=[p for d in days for p in d['pages']]
    aggregate=run/'aggregated.json';write(aggregate,items)
    manifest={'format':'dashboard-week-daily-rollup/v2','store':str(store),'start':start,'end':end,
              'records':len(items),'pages':pages,'days':dates,'mode':'daily_rollup','tmPolicy':'weekly_unique_unavailable',
              'aggregate':aggregate.relative_to(folder).as_posix(),'aggregateSha256':hashlib.sha256(aggregate.read_bytes()).hexdigest(),
              'countWarnings':[d['countWarning'] for d in days if d.get('countWarning')],
              'completed':True,'collectedAt':datetime.now(timezone.utc).isoformat()}
    write(folder/'manifest.json',manifest)
    return manifest

def snapshot(workspace,start,end,store=None):
    folder=period_dir(workspace,start,end);path=folder/'manifest.json'
    if not path.is_file():return None
    m=read(path)
    if m.get('format')!='dashboard-week-daily-rollup/v2' or m.get('completed') is not True or (m.get('start'),m.get('end'))!=(start,end) or store is not None and str(m.get('store'))!=str(store):raise ValueError('周产品快照店铺或期间不匹配')
    days={day:{} for day in m.get('days',[])};pages=m.get('pages');numbers={}
    expected=[(date.fromisoformat(start)+timedelta(days=i)).isoformat() for i in range(7)]
    if sorted(days)!=expected:raise ValueError('自然周缺少完整7日')
    if not isinstance(pages,list) or not pages:raise ValueError('周快照缺分页')
    for i,item in enumerate(pages,1):
        p=(folder/item['file']).resolve()
        day=item.get('day');index=numbers.get(day,0)+1;numbers[day]=index
        if day not in days or not p.is_relative_to(folder.resolve()) or p.name!='page_%04d.json'%index:raise ValueError('分页路径或序号无效')
        if hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('周快照哈希不一致')
        response=read(p);data=response.get('data',{})
        query=parse_qs(urlsplit(data.get('downloadUrl','')).query)
        if response.get('success') is not True or data.get('recordCount')!=item['records'] or query.get('statDate')!=[day] or query.get('statisticsType')!=['day']:raise ValueError('日快照日期或总数无效')
        for row in data.get('data',[]):
            pid=str(row.get('id') or '')
            if not pid.isdigit() or pid in days[day]:raise ValueError('周快照产品编号重复或缺失')
            days[day][pid]=row
    warnings={w['day']:w for w in m.get('countWarnings',[])}
    for day,items in days.items():
        declared=next(p['records'] for p in pages if p['day']==day)
        if len(items)==declared:continue
        warning=warnings.get(day)
        if not warning or warning.get('declaredRecords')!=declared or warning.get('enumeratedRecords')!=len(items):raise ValueError('自然日分页不完整')
        def checked_file(item):
            f=(folder/item['file']).resolve()
            if not f.is_relative_to(folder.resolve()) or hashlib.sha256(f.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('数量核对证据不匹配')
            data=checked_response(read(f),day)
            if data.get('recordCount')!=declared:raise ValueError('核对来源总数不匹配')
            return data
        terminal=checked_file({'file':warning['terminal'],'sha256':warning['terminalSha256']})
        if terminal.get('data')!=[]:raise ValueError('数量异常缺少空尾页')
        secondary={};ended=False
        for i,item in enumerate(warning.get('alternatePages',[]),1):
            if Path(item['file']).name!='page_%04d.json'%i:raise ValueError('交叉枚举页码不连续')
            data=checked_file(item)
            if not data.get('data'):
                ended=True
                if i!=len(warning['alternatePages']):raise ValueError('空尾页后仍有数据')
                break
            for row in data['data']:
                pid=str(row.get('id') or '')
                if not pid.isdigit() or pid in secondary:raise ValueError('交叉枚举ID重复')
                secondary[pid]=row
        if not ended or set(secondary)!=set(items) or any(any(num(items[pid].get(f))!=num(secondary[pid].get(f)) for f in FIELDS.values()) for pid in items):raise ValueError('数量异常未获双枚举确认')
    aggregate=(folder/m['aggregate']).resolve()
    if not aggregate.is_relative_to(folder.resolve()) or hashlib.sha256(aggregate.read_bytes()).hexdigest()!=m['aggregateSha256']:raise ValueError('汇总文件不匹配')
    items=aggregate_days([{'day':day,'items':days[day]} for day in expected])
    if read(aggregate)!=items or len(items)!=m['records']:raise ValueError('按日重算与汇总不一致')
    return m,items

def product_rows(workspace,start,end,store):
    result=snapshot(workspace,start,end,store)
    if result is None:return None
    _,items=result;out=[]
    for pid,row in items.items():
        p={k:num(row.get(source)) for k,source in FIELDS.items()}
        p.update(product_id=pid,title=row.get('prodName') or row.get('subject') or '',
                 category=row.get('cateName') or '',prod_level=row.get('prodLevel3'),
                 main_image=row.get('prodImage') or '',detail_url=row.get('detailUrl') or row.get('productDetailUrl'),
                 first_seen_at=None,crt_time=(row.get('crtTime') or '')[:10],moq=row.get('minOrderQuantity'),price_range=row.get('priceRange') or row.get('price'))
        p['tm_daily_sum']=row.get('tmDailySum');p['observation_days']=row.get('observationDays')
        p['opp']=p['inquiries']+p['tm'] if p['inquiries'] is not None and p['tm'] is not None else None
        p['total_ctr']=round(100*p['total_clk']/p['total_imps'],2) if p['total_imps'] and p['total_clk'] is not None else 0 if p['total_imps']==0 and p['total_clk']==0 else None
        p['ctr']=100*p['ctr'] if p['ctr'] is not None else None
        p.update(label='有商机' if (p['opp'] or 0)>0 else '待复核',label_typ='neutral',
                 ad_label='广告数据缺失' if p['ad_clk'] is None else '有广告点击' if p['ad_clk']>0 else '无广告点击',ad_typ='neutral',
                 sug='按本期产品指标核对实际需求、规格和报价；不推断广告归因。')
        out.append(p)
    return out

def verify_rows(workspace,start,end,rows,store=None):
    result=snapshot(workspace,start,end,store)
    if result is None:return None
    m,items=result
    if len(rows)!=len(items) or {p['product_id'] for p in rows}!=set(items):raise ValueError('周快照与面板产品集合不一致')
    for p in rows:
        for key,source in FIELDS.items():
            if key in ('ctr',):continue
            if p.get(key)!=num(items[p['product_id']].get(source)):raise ValueError('周快照与面板指标不一致')
    return {'status':'VERIFIED','mode':'daily_rollup','tmPolicy':m['tmPolicy'],'days':7,'pages':len(m['pages']),'records':m['records'],
            'completeMetricProducts':sum(r.get('totalClkCnt') is not None for r in items.values()),
            'sourceCountWarnings':[{'day':w['day'],'declared':w['declaredRecords'],'enumerated':w['enumeratedRecords']} for w in m.get('countWarnings',[])],
            'sourceWindow':[start,end],'collectedAt':m['collectedAt']}

def collect_all(workspace,store,call,guard=lambda:None,publish_latest_alias=True):
    workspace=Path(workspace);win=read(workspace/'raw/_window.json');out=[]
    weeks=sorted(win['weeks'],key=lambda w:w['week_start'])
    for week in weeks:
        m=collect_week(workspace,store,week['week_start'],week['week_end'],call,guard)
        out.append(m);print('完整自然周 %s ~ %s：%d 产品 / %d 页'%(m['start'],m['end'],m['records'],len(m['pages'])),flush=True)
    if publish_latest_alias and out:
        import shutil
        m=out[-1];folder=period_dir(workspace,m['start'],m['end']);raw=workspace/'raw';items=list(snapshot(workspace,m['start'],m['end'],store)[1].values())
        for old in raw.glob('shop_product_w1_p*.json'):
            if re.fullmatch(r'shop_product_w1_p\d+\.json',old.name):old.unlink()
        for i in range(max(1,(len(items)+19)//20)):
            write(raw/('shop_product_w1_p%02d.json'%(i+1)),{'success':True,'source':'verified-daily-rollup','data':{'recordCount':len(items),'data':items[i*20:(i+1)*20]}})
    return out

def collect_ad_weeks(workspace,call,guard=lambda:None):
    """Reuse the existing workctl report/table SQL contract; unknown stays unknown."""
    workspace=Path(workspace);win=read(workspace/'raw/_window.json');out=[]
    sources={'company_whole_site':('campaign_whole_site',['花费','曝光量','点击量','全站商机量']),
             'company_search':('campaign_search',['花费','曝光量','点击量','searchAtmSessionCnt','searchMcCnt','searchOrderCnt'])}
    for w in sorted(win['weeks'],key=lambda w:w['week_start']):
        account={};coverage={}
        for key,(source,fields) in sources.items():
            guard()
            report=call({'entityType':'report','filters':{'datasource':source,'beginDateTime':w['week_start']+' 00:00:00','endDateTime':w['week_end']+' 23:59:59'},'include':'data'})
            entries=report.get('data') if isinstance(report,dict) else None
            table=next((r for r in entries or [] if isinstance(r,dict) and r.get('tableName') and r.get('sessionId')),None)
            if report.get('success') is not True or not table:
                account[key]=[];coverage[key]='UNAVAILABLE';continue
            sql='SELECT '+', '.join('SUM("%s") AS "%s"'%(f,f) for f in fields)+' FROM '+table['tableName']
            response=call({'entityType':'report_sql','filters':{'sessionId':table['sessionId'],'tableName':table['tableName'],'sql1':sql},'include':'data'})
            guard();data=response.get('data') or []
            tsv=next((x.get('tsvData') for x in data if isinstance(x,dict) and x.get('tsvData')),None)
            if response.get('success') is not True or not tsv:
                account[key]=[];coverage[key]='UNAVAILABLE';continue
            lines=tsv.strip('\n').splitlines();headers=lines[0].split('\t')
            if len(lines)<2:account[key]=[];coverage[key]='EMPTY_OR_UNAVAILABLE';continue
            raw=dict(zip(headers,lines[1].split('\t')));r={name:num(raw.get(name)) for name in fields}
            r['全站商机量']=r.get('全站商机量') if key=='company_whole_site' else None
            account[key]=[r];coverage[key]='OK' if r.get('花费') is not None else 'UNAVAILABLE'
        payload={'window':{'begin':w['week_start'],'end':w['week_end']},'account':account,'coverage':coverage,'collectedAt':datetime.now(timezone.utc).isoformat()}
        write(workspace/('raw/ads_report_week_'+w['week_start']+'.json'),payload)
        out.append(payload);print('广告自然周 %s：%s'%(w['week_start'],coverage),flush=True)
    return out

def install(package):
    """Install hooks only in a copied engine, keeping the upstream package untouched."""
    package=Path(package);pipeline=package/'engine/pipeline'
    f=pipeline/'fetch_new_store.py'
    if f.is_file():
        s=f.read_text('utf-8-sig')
        old='        fetch_products(WEEKS[-1][0], WEEKS[-1][1])'
        hook="""        from pathlib import Path
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
        from dashboard_native_week import collect_all
        cfg=json.load(open(os.path.join(ROOT,'stores.json'),encoding='utf-8'))
        store=cfg['stores'][cfg['active']]['store_id']
        collect_all(Path(ROOT),store,mcp_call)  # MULTI_WEEK_PRODUCTS_V1"""
        s=s.replace('from dashboard_week_history import collect_all','from dashboard_native_week import collect_all')
        if old in s:s=s.replace(old,hook)
        elif '# MULTI_WEEK_PRODUCTS_V1' not in s and '# PLATFORM_NATIVE_WEEK_V1' not in s:raise ValueError('产品采集入口已变化')
        f.write_text(s,encoding='utf-8')
    f=pipeline/'v4_fetch_ads_report.py'
    if f.is_file():
        s=f.read_text('utf-8-sig')
        start=s.index('try:\n    W = _gos_ctx.window()');end=s.index('TAG = WB.replace',start)
        s=s[:start]+"W = _gos_ctx.window()\nlatest_week=max(W['weeks'],key=lambda w:w['week_end'])\nlatest_month=max(W['months'],key=lambda m:m['month_end'])\nWB, WE = latest_week['week_start'],latest_week['week_end']\nMB, ME = latest_month['month_start'],latest_month['month_end']\n"+s[end:]
        # Keep a stable anchor so installing twice remains safe.
        s=s.replace("W = _gos_ctx.window()\nlatest_week", "try:\n    W = _gos_ctx.window()\nexcept (KeyError, FileNotFoundError):\n    raise ValueError('缺少已确认自然周/月窗口，停止广告采集')\nlatest_week",1)
        if '# MULTI_WEEK_ADS_V1' not in s:
            s+="\nfrom pathlib import Path\nsys.path.insert(0,str(Path(__file__).resolve().parents[2]))\nfrom dashboard_week_history import collect_ad_weeks\ncollect_ad_weeks(Path.cwd(),wc)  # MULTI_WEEK_ADS_V1\n"
        f.write_text(s,encoding='utf-8')
