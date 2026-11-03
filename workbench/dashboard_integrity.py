"""Offline corrections for copied dashboards. Never change source engines or databases."""
from __future__ import annotations
import argparse
import copy
import json
import math
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
import re

ROOT = Path(__file__).resolve().parent
MARKER = '/* WORKBENCH_DASHBOARD_INTEGRITY_V1 */'

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def number(v):
    if v is None or v == '': return None
    try:
        n = float(v)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError): return None

def summary_rows(workspace):
    """Only allowlisted aggregate fields leave private raw storage."""
    rows = {}
    for path in sorted((workspace / 'raw').glob('shop_summary_*.json')):
        payload = read_json(path)
        if payload.get('success') is not True: continue
        for row in payload.get('data', []):
            if isinstance(row, dict) and row.get('statDate'):
                rows[(row.get('statisticsType'), row['statDate'])] = row
    return rows

def product_lists(rows):
    by = lambda field: lambda p: -(p.get(field) or 0)
    states={}
    names={'deal_ok':'有成交·客单价≥500 USD','deal_low_aov':'有成交·客单价<500 USD','nat_opp_no_ad':'有商机·无广告点击','has_opp':'有商机·有广告点击','ad_no_opp':'有广告点击·无商机','clk_no_opp':'点击≥4·无商机','imp_no_clk':'有曝光·点击不足4','zero_exp':'零曝光·零点击'}
    for p in rows:
        if any(p.get(k) is None for k in ('opp','orders','gmv','total_imps','total_clk','ad_clk')):continue
        state=('deal_ok' if p['gmv']/p['orders']>=500 else 'deal_low_aov') if p['orders']>0 else ('nat_opp_no_ad' if p['ad_clk']==0 else 'has_opp') if p['opp']>0 else 'ad_no_opp' if p['ad_clk']>0 else 'clk_no_opp' if p['total_clk']>=4 else 'imp_no_clk' if p['total_imps']>0 else 'zero_exp'
        states.setdefault(state,[]).append(p)
    grid=[{'state':key,'name':label,'count':len(states[key]),'items':sorted(states[key],key=by('opp')),'top':sorted(states[key],key=by('opp'))[:3],
           'action':'按本期状态定位问题，结合价格/MOQ、详情及接待证据复核；客单价500 USD为原模板内部阈值。'} for key,label in names.items() if key in states]
    return {
        'inquiry': sorted([p for p in rows if (p['inquiries'] or 0)>0], key=by('inquiries')),
        'opp': sorted([p for p in rows if (p['opp'] or 0)>0],key=by('opp')),
        'tm': sorted([p for p in rows if (p['tm'] or 0)>0 and p['inquiries']==0],key=by('tm')),
        'ctr': sorted([p for p in rows if (p['total_clk'] or 0)>=4],key=by('total_ctr')),
        'zero_cost': sorted([p for p in rows if p['ad_clk']==0 and ((p['opp'] or 0)>0 or (p['total_clk'] or 0)>=4)],key=by('opp')),
        'high_eff_low_cost': sorted([p for p in rows if (p['ad_clk'] or 0)>0 and (p['opp'] or 0)>0],key=by('opp')),
        'state_grid': grid, 'new_product': []}

def products(c, kind, start, end):
    period = 'week' if kind=='week' else 'month'
    # Inner join excludes catalogue-only products whose missing stats used to become zeroes.
    query = f'''SELECT p.*, s.impressions, s.clicks, s.ctr, s.inquiries, s.orders, s.gmv,
        e.total_imps, e.total_clk, e.ad_imps, e.ad_clk, e.atm_fb_uv
        FROM product_{period}ly_stats s JOIN products p USING(product_id)
        LEFT JOIN product_{period}ly_stats_ext e ON e.product_id=s.product_id AND e.{period}_start=s.{period}_start
        WHERE s.{period}_start=? AND s.{period}_end=?'''
    result=[]
    for item in c.execute(query,(start,end)):
        p=dict(item)
        p['product_id']=str(p['product_id'])
        p['category']=p.get('category_name') or p.get('category') or ''
        p['tm']=p['atm_fb_uv']
        p['opp']=p['inquiries']+p['tm'] if p['inquiries'] is not None and p['tm'] is not None else None
        p['total_ctr']=round(100*p['total_clk']/p['total_imps'],2) if p['total_imps'] and p['total_clk'] is not None else (0 if p['total_imps']==0 and p['total_clk']==0 else None)
        p['ctr']=round(100*p['ctr'],2) if p['ctr'] is not None else None
        p['label']='有商机' if (p['opp'] or 0)>0 else '高点击0商机' if (p['total_clk'] or 0)>=4 else '有曝光未起量' if (p['total_clk'] or 0)>0 else '冷启动'
        p['label_typ']='good' if (p['opp'] or 0)>0 else 'danger' if (p['total_clk'] or 0)>=4 else 'muted'
        p['ad_label']='有广告点击' if (p['ad_clk'] or 0)>0 else '无广告点击' if p['ad_clk']==0 else '广告数据缺失'
        p['ad_typ']='neutral'; p['sug']='结合本期指标核对产品与买家需求；广告归因及单品花费未提供。'
        # Strip raw product JSON and any owner/contact fields.
        fields=('product_id','title','prod_level','category','main_image','detail_url','first_seen_at','crt_time','moq','price_range','impressions','clicks','ctr','total_imps','total_clk','total_ctr','inquiries','tm','opp','orders','gmv','ad_imps','ad_clk','label','label_typ','ad_label','ad_typ','sug')
        result.append({k:p.get(k) for k in fields})
    return result

def validate_product_pages(workspace, kind, start, end, rows):
    if kind=='week' and (Path(workspace)/'raw/platform-native-week-policy.json').exists():
        from dashboard_native_week import verify_rows
        return verify_rows(workspace,start,end,rows)
    if kind=='week':
        from dashboard_week_history import verify_rows
        verified=verify_rows(workspace,start,end,rows)
        if verified is not None:return verified
    if not rows: return {'status':'NOT_COLLECTED'}
    prefix='w1' if kind=='week' else 'm1'
    if kind=='week':
        window=read_json(workspace/'raw/_window.json')['weeks'][0]
        expected_period=(window['week_start'],window['week_end'])
    else:
        window=read_json(workspace/'raw/_month_product_window.json')
        expected_period=(window['statDate'],window['month_end'])
    if (start,end)!=expected_period:
        # Old database periods without matching raw provenance are unavailable, not silently trusted.
        raise ValueError('产品数据库期间缺少匹配的原始分页证据')
    seen={};total=None;pages=sorted((workspace/'raw').glob('shop_product_'+prefix+'_p*.json'))
    for index,path in enumerate(pages,1):
        match=re.fullmatch('shop_product_'+prefix+r'_p(\d+)\.json',path.name)
        if not match or int(match[1])!=index: raise ValueError('产品分页不连续')
        payload=read_json(path);data=payload.get('data',{})
        if payload.get('success') is not True or not isinstance(data,dict):raise ValueError('产品分页接口未成功')
        count=data.get('recordCount')
        if type(count) is not int or count<0 or (total is not None and total!=count):raise ValueError('产品分页总数不一致')
        total=count
        for row in data.get('data',[]):
            pid=str(row.get('id') or '')
            if not pid.isdigit() or pid in seen:raise ValueError('产品分页ID缺失或重复')
            seen[pid]=row
    if total!=len(seen) or set(seen)!={p['product_id'] for p in rows}:raise ValueError('产品分页/数据库不完整或ID不匹配')
    mapping={'total_imps':'totalImpsCnt','total_clk':'totalClkCnt','inquiries':'sumProdFbNum','tm':'atmFbUv','orders':'crtOrd','gmv':'rtsOnlineAmt','ad_imps':'adImpsCnt','ad_clk':'adClkCnt'}
    for p in rows:
        for field,source in mapping.items():
            raw_value=number(seen[p['product_id']].get(source))
            # Restore nulls that upstream loaders converted to zero. Non-null disagreement fails closed.
            if raw_value is None:p[field]=None
            elif p[field]!=raw_value:raise ValueError('产品指标与原始分页不一致：'+field)
        p['opp']=p['inquiries']+p['tm'] if p['inquiries'] is not None and p['tm'] is not None else None
        p['total_ctr']=round(100*p['total_clk']/p['total_imps'],2) if p['total_imps'] and p['total_clk'] is not None else (0 if p['total_imps']==0 and p['total_clk']==0 else None)
    return {'status':'VERIFIED','pages':len(pages),'records':len(seen),'sourceWindow':[start,end]}

def period_spend(workspace, kind, start, end):
    for path in sorted((workspace/'raw').glob('ads_report_*.json')):
        a=read_json(path); v=a if kind=='week' else a.get('month',{})
        win=v.get('window',v)
        if win.get('begin')!=start or win.get('end')!=end: continue
        if v.get('coverage') and any(status!='OK' for status in v['coverage'].values()):continue
        lines=v.get('account',{})
        records=[r for name in ('company_whole_site','company_search') for r in lines.get(name,[]) if isinstance(r,dict)]
        if not records: continue
        def total(key):
            values=[number(r.get(key)) for r in records]
            return sum(values) if all(n is not None for n in values) else None
        spend=total('花费'); clicks=total('点击量'); opp=total('全站商机量')
        return {'ad_spend':spend,'ad_spend_auto':spend is not None,'ad_clicks':clicks,'ad_imps':total('曝光量'),'ad_opp':opp,
                'ad_cpc':round(spend/clicks,2) if spend is not None and clicks else None,
                'ad_cpl':round(spend/opp,2) if spend is not None and opp else None}
    return dict.fromkeys(('ad_spend','ad_cpc','ad_cpl','ad_clicks','ad_imps','ad_opp')) | {'ad_spend_auto':False}

def enrich(data,workspace):
    d=copy.deepcopy(data); sources=summary_rows(workspace)
    c=sqlite3.connect((workspace/'database/alibaba_growth.db').resolve().as_uri()+'?mode=ro',uri=True); c.row_factory=sqlite3.Row
    bundles={}; evidence=[]
    for kind, periods in [('week',d.get('weeks',[])),('month',d.get('months',[]))]:
        for period in periods:
            start,end=period[kind+'_start'],period[kind+'_end']
            raw=sources.get(('7d' if kind=='week' else 'month',end),{})
            if kind=='month' and not raw:raw=sources.get(('30d',end),{})
            # monthly_full carries all six month snapshots; one summary file covers only the latest.
            if kind=='month':
                raw_month=read_json(workspace/'raw/monthly_full.json').get(start[:7],{})
                for name in ('uv_payord_ra','uv_payord_rg'):
                    period[name]=100*number(raw_month[name]) if number(raw_month.get(name)) is not None else None
            else: raw_month={}
            prev_opp=period.get('opp')
            period['platform_ab_cnt']=raw.get('abCnt',raw_month.get('ab_cnt',prev_opp))
            period['opp']=period['fb_cnt']+period['fb_tm_uv'] if period.get('fb_cnt') is not None and period.get('fb_tm_uv') is not None else None
            # Never derive total clicks from PV or sum of overlapping channel counts.
            period['total_clk']=number(raw.get('totalClkCnt',raw_month.get('total_clk')))
            period['pv_cnt']=number(raw.get('pvCnt',raw_month.get('pv_cnt',period.get('pv_cnt'))))
            period['created_orders']=number(raw.get('crtOrdCnt'))
            if (Path(workspace)/'raw/platform-native-week-policy.json').exists():
                from dashboard_native_week import product_rows
            else:
                from dashboard_week_history import product_rows
            rows=product_rows(workspace,start,end,d['meta']['store_id']) if kind=='week' else None
            if rows is None:rows=products(c,kind,start,end)
            provenance=validate_product_pages(workspace,kind,start,end,rows)
            lists=product_lists(rows)
            pool=[dict(p,level=p['prod_level'],imps=p['total_imps'],clicks=p['total_clk']) for p in rows]
            b=copy.deepcopy(d.get('boss',{}))
            k={name:period.get(key) for name,key in {'total_imps':'total_imps','total_clk':'total_clk','se_clk':'se_clk','camp_clk':'camp_clk','uv_cnt':'uv_cnt','inquiries':'fb_cnt','tm_inquiries':'fb_tm_uv','orders':'suc_ord_cnt','gmv':'suc_ord_amt'}.items()}
            b.update(kpi=k,kpi_month=k,week_label=start+' ~ '+end,month_label=start+' ~ '+end,
                     spend=period_spend(workspace,kind,start,end),product_pool=pool,product_pool_month=pool,
                     manual={**dict.fromkeys(('acquisition','quality_customers','cac','sample_orders','annual_fee','wendin','topshow','brand_ad','ad_spend_override','new_count')), 'sample_products':'','order_products':'','new_selection':[]})
            b['spend_month']=b['spend']
            for key,level in [('hot','爆品'),('premium','优品'),('potential','潜力优品')]:
                b[key+'_products']=[p for p in pool if p['level']==level]; b[key+'_count']=len(b[key+'_products'])
            collected=provenance.get('status')=='VERIFIED'
            health={'levels':[{'label':lv,'count':sum(p['prod_level']==lv for p in rows) if collected else None} for lv in ['爆品','优品','潜力优品','普通品','低质品']],
                    'valid_cnt':len(rows) if collected else None,'inquiry_products':len(lists['inquiry']) if collected else None,'zero_inquiry':sum(p['inquiries']==0 for p in rows) if collected else None,'star':None,'star_note':'分级为采集时快照；产品明细数与店铺有效商品数分别统计。'}
            adp=[dict(p,imps=p['ad_imps'],clk=p['ad_clk'],ctr=round(100*p['ad_clk']/p['ad_imps'],2) if p['ad_imps'] and p['ad_clk'] is not None else None,opp_rate=None,l1_rate=None) for p in rows if (p['ad_imps'] or 0)>0 or (p['ad_clk'] or 0)>0]
            bundles[kind+':'+start]={'boss':b,'lists':lists,'products':rows,'health':health,'ad_products':sorted(adp,key=lambda p:-(p['clk'] or 0)), 'period':period,'provenance':provenance}
            period['valid_prod_cnt']=number(raw.get('validProdCnt',raw_month.get('valid_prod_cnt')))
            evidence.append({'kind':kind,'start':start,'end':end,'products':len(rows),'provenance':provenance,'rankCounts':{k:len(v) for k,v in lists.items()},'store':{key:period.get(key) for key in ('total_imps','total_clk','pv_cnt','fb_cnt','fb_tm_uv','opp','platform_ab_cnt','suc_ord_cnt','suc_ord_amt','valid_prod_cnt')},'adSpend':b['spend']['ad_spend'],
                'productSums':{k:sum(p.get(k) or 0 for p in rows) for k in ('total_imps','total_clk','inquiries','tm','orders','gmv')},'coverage':'本期产品明细' if rows else '未采集该期间产品明细，禁止沿用最新榜单'})
    c.close()
    d['audit_periods']=bundles;d['audit_version']=1;d['audit_evidence']=evidence
    d['meta']['generated_at']=datetime.now(timezone.utc).isoformat()
    for key,periods in [('week','weeks'),('month','months')]:
        if d.get(periods):
            latest=d[periods][-1]
            if key=='month':d['monthly']=latest
    # Match initial visible period even in consumers that do not execute the runtime adapter.
    latest=bundles.get('week:'+d['meta']['week_start'])
    if latest:
        d['boss']=latest['boss'];d['lists']=latest['lists'];d['health']=latest['health']
    return d

def patch_app(source):
    source=source.split(MARKER)[0].rstrip()
    source=source.replace('return newProdDate(b).localeCompare(newProdDate(a));','return window.dashboardProductOrder.compare(a,b);')
    # Changes remain confined to the workbench-owned copy of the upstream template.
    source=source.replace('_m(k.gmv)','money(k.gmv)')
    source=source.replace("(raw==='')?0:Number(raw)","(raw==='')?null:Number(raw)")
    source=source.replace("(p.title||'').toLowerCase().indexOf(kw)<0", "((p.title||'')+' '+p.product_id).toLowerCase().indexOf(kw)<0")
    # All summary formats use the same selected period and null-aware expense arithmetic.
    source=source.replace('(sp.ad_spend||0)','sp.ad_spend')
    source=source.replace('Number(m.annual_fee||0) + Number(m.wendin||0) + Number(m.topshow||0) + Number(m.brand_ad||0)', 'auditOtherSpend(m)')
    source=source.replace('Number(m.annual_fee||0)+Number(m.wendin||0)+Number(m.topshow||0)+Number(m.brand_ad||0)', 'auditOtherSpend(m)')
    source=source.replace('(adSpend||0) + otherSpend','auditSum(adSpend,otherSpend)').replace('(adSpend||0)+otherSpend','auditSum(adSpend,otherSpend)')
    for name in ('acquisition','quality_customers','sample_orders'):
        source=source.replace('Number(m.'+name+'||0)','auditNumber(m.'+name+')')
    for name in ('sample_orders','new_count'):
        source=source.replace('m.'+name+'||0','m.'+name)
    for name in ('annual_fee','wendin','topshow','brand_ad'):
        source=source.replace('m.'+name+'||0','m.'+name)
    source=source.replace('acq>0 ? totalSpend/acq : null','acq>0 && totalSpend!=null ? totalSpend/acq : null').replace('acq>0?totalSpend/acq:null','acq>0&&totalSpend!=null?totalSpend/acq:null')
    source=source.replace('商机榜 Top50','商机榜（全量）').replace('点击率榜 Top20','点击率榜（全量）')
    source=source.replace('<th>订单</th>','<th>创建订单(crtOrd)</th>').replace('<th>GMV($)</th>','<th>RTS金额(USD)</th>')
    source=source.replace('单品逐期对比','单品期间明细').replace('选一个品，看它每期的点击/询盘/TM/花费','选一个品，查看当前所选期间的点击/询盘/TM；单品花费未提供')
    source=source.replace('较比上周','较比上一期间')
    source=source.replace('var tr0 = (sr.tracks||[])[0] || {};','var tr0 = auditStarTrack(sr);')
    source=source.replace('var tr1 = (sr.tracks||[])[1] || {};','var tr1 = (sr.tracks||[]).find(function(t){return t!==tr0;}) || {};')
    source=source.replace("(alert.down? '<span class=\"tag danger\">⚠ 预测降星</span>' : '<span class=\"tag good\">✓ 预测保星（'+esc(alert.title||'')+'）</span>')",'auditStarPredictionHTML(sr)')
    source=source.replace("产品分层（'+num(hh.valid_cnt)+' 在架）","产品分层（本期产品明细 '+num(hh.valid_cnt)+' 条）")
    source=source.replace('(hh.valid_cnt?hh.zero_inquiry*100/hh.valid_cnt:0)','(hh.valid_cnt>0&&hh.zero_inquiry!=null?hh.zero_inquiry*100/hh.valid_cnt:null)')
    source=source.replace("var s=D.staff_cs||[];\n","var s=D.staff_cs||[]; if(!s.length)return weeklyOnlyNote()+'<div class=\"section-title\">客服接待质量 · 按子账号</div><div class=\"card\"><p>该期间子账号报表未匹配；空表不表示0人接待。须核对原始日期与统计窗口，不能自动套用其他周的账号明细。</p>'+noteBox('staff')+'</div>';\n")
    source=source.replace('高效低耗榜','有广告点击且出商机').replace('上升趋势·零花费榜','无广告点击机会榜')
    source=source.replace('已投广告(有广告点击)且本周出商机 → 广告钱花得值、单商机成本低，加预算放大','同品存在广告点击与商机；未提供单品花费和广告归因，不能据此判定高效低耗')
    source=source.replace('没投广告但自然流量已出商机/高点击 → 零成本验证过，优先接广告预算','无广告点击且有商机或至少4次点击；不等于零花费或趋势上升')
    return source+'\n'+MARKER+'\n'+(ROOT/'dashboard_integrity_runtime.js').read_text(encoding='utf-8')+'\n'+(ROOT/'dashboard_manual_runtime.js').read_text(encoding='utf-8')+'\n'+(ROOT/'dashboard_advertising_runtime.js').read_text(encoding='utf-8')+'\n'+(ROOT/'dashboard_feature_restore.js').read_text(encoding='utf-8')+'\n'+(ROOT/'dashboard_product_order.js').read_text(encoding='utf-8')+'\n'+(ROOT/'dashboard_manual_html.js').read_text(encoding='utf-8')

def apply(workspace, output=None):
    workspace=Path(workspace);out=Path(output) if output else workspace/'dashboard'
    data=enrich(read_json(workspace/'v4_data.json'),workspace)
    from dashboard_manual import merge_into_data
    merge_into_data(data)
    out.mkdir(parents=True,exist_ok=True)
    (out/'dashboard_data.js').write_text('window.V4_DATA = '+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf-8')
    (out/'app.js').write_text(patch_app((out/'app.js').read_text(encoding='utf-8-sig')),encoding='utf-8')
    return data['audit_evidence']

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--workspace',required=True);p.add_argument('--output');args=p.parse_args()
    print(json.dumps(apply(args.workspace,args.output),ensure_ascii=False))
