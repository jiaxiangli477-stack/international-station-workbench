"""Store-isolated, verified native recruitment pagination and searchable snapshots."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import threading
import time

import shared_scan as common
import weekly_update
import bridge_catalog
from bridge_reads import image_url

ROOT = Path(__file__).resolve().parent
STATE = ROOT / '.state' / 'recruitment'
TYPES = {'HOT_PRODUCT': '交易品定招', 'CUSTOMIZATION_PRODUCT': '商机品定招'}
MAIN_SCOPE = '__main__'
# Company profile: supplements, sports nutrition, collagen, electrolytes,
# energy pouches and instant coffee. These are development leads, not passes.
MAIN_CATEGORIES = frozenset({
    '草本补充剂', '维生素', '运动营养补给', '胶原蛋白', '蛋白粉', '减肥茶',
    '抗氧化保健食品', '复合维生素及矿物质', '速溶咖啡', '鱼油', '其它保健食品',
    '其他保健食品', '菌/菇/酵素', '膳食纤维', '矿物质', '能量补充型饮料',
    '氨基酸', '能量饮料', '滋补营养品', '辅酶Q10',
    'Sports Nutrition', 'Herbal Supplements', 'Slimming Tea',
})
GENERAL_NUTRITION_CATEGORIES = frozenset({
    '其他食品与饮料', '其他保健用品', 'Other Healthcare Supply',
    '糖果', '植物基饮料', '绿茶', '研磨咖啡', '蜂产品', '蜂蜜',
})
NUTRITION_TITLE = re.compile(
    r'补充剂|保健品|蛋白|益生菌|电解质|胶原|维生素|肌酸|氨基酸|代餐|生酮|'
    r'瘦身|减肥|草本.*咖啡|菌菇咖啡|蘑菇咖啡|营养.*粉|'
    r'supplement|protein|probiotic|electrolyte|collagen|vitamin|creatine|MCT', re.I)
NON_NUTRITION_TITLE = re.compile(
    r'外用|身体贴|透皮|痔疮|鼻贴|鼻夹|膏药|按摩|兽用|宠物|除臭|止痒|尼古丁|'
    r'topical|transdermal|nicotine|\bpet\b', re.I)


def main_business_topic(leaf, title):
    """Conservative category screening; preserve oral sprays/gels/strips."""
    title = title or ''
    if re.search(r'贴片|贴剂', title) and not re.search(r'口腔|口溶|舌下', title):
        return False
    return not NON_NUTRITION_TITLE.search(title) and (
        leaf in MAIN_CATEGORIES or
        leaf in GENERAL_NUTRITION_CATEGORIES and bool(NUTRITION_TITLE.search(title)))


LOCKS = {key: threading.Lock() for key in weekly_update.STORES}


def unpack(data):
    if isinstance(data, dict) and isinstance(data.get('data'), dict) and 'value' in data['data']:
        data = data['data']
    if not isinstance(data, dict) or data.get('success') is not True or not isinstance(data.get('value'), dict):
        raise weekly_update.SyncError('平台未返回成功的征品数据')
    return data['value']


def verify_page(value, requested, business):
    if value.get('pageNo') != requested or value.get('pageSize') != 48:
        raise weekly_update.SyncError('平台没有执行请求页码，停止接收重复首屏')
    if not isinstance(value.get('datas'), list) or not isinstance(value.get('pageCount'), int):
        raise weekly_update.SyncError('平台分页结构不完整')
    if any(row.get('businessType') != business for row in value['datas']):
        raise weekly_update.SyncError('交易品与商机品类型混入，未发布新快照')
    return value


def call_page(bridge, folder, business, page):
    name = business.lower() + '-' + str(page)
    output = folder / (name + '.json')
    if output.exists():
        try:
            return verify_page(unpack(json.loads(output.read_text(encoding='utf-8-sig'))), page, business)
        except (ValueError,weekly_update.SyncError):
            output.unlink()
    params = folder / (name + '-input.json')
    common.atomic_json(params, {'scene': 'topicRecommendScene', 'topicSceneQuery': {
        'businessType': business, 'currentPage': page, 'pageSize': 48}})
    try:
        weekly_update.run([bridge / 'workctl.cmd', 'icbu', 'recruitment-topic', 'search',
                           '--json-file', str(params), '--format', 'json', '--compact-output', 'off', '--output', str(output)],
                          cwd=folder, timeout=120)
    except weekly_update.SyncError:
        raise weekly_update.SyncError('征品分页读取失败，保留旧快照，可恢复失败页') from None
    if not output.exists():
        raise weekly_update.SyncError('征品分页读取失败，保留旧快照，可恢复失败页')
    return verify_page(unpack(json.loads(output.read_text(encoding='utf-8-sig'))), page, business)


def tag_label(code):
    if code in ('OVERSEA_TREND_TOPIC','GLOBAL_HOT'): return '全网热卖'
    if code == 'ICBU_HOT': return '站内热卖'
    if code == 'ICBU_SHORT': return '站内稀缺'
    if code == 'SCENARIO_SPECIAL': return '场景特招'
    if code == 'WORLD_CUP': return '世界杯主题'
    if code == 'HOME_RENOVATION': return '家居翻新主题'
    if code == 'RECOMMEND_COUNTRY_STRATEGY': return '国家推荐主题'
    if code == 'NONE': return '未标注分类'
    if any(t in code.upper() for t in ('SCARCE', 'SCARCITY', 'SHORTAGE', 'LACK')): return '站内稀缺'
    return code or '未标注分类'


def normalize(row, categories, order):
    rule = row.get('ruleDTO') if isinstance(row.get('ruleDTO'), dict) else {}
    ids = [i for i in str(row.get('categoryIds') or rule.get('categoryIds') or '').split(',') if i]
    labels = [str((categories.get(i) or {}).get('name') or i) for i in ids]
    dto = row.get('strategyTagDTO') or {}
    tag = dto.get('tagCode') or row.get('strategyTag') or ''
    countries = row.get('recommendCountryList') or row.get('mdsRecommendCountryList') or []
    country_rows = []
    if isinstance(countries, list):
        for c in countries:
            if isinstance(c, str): country_rows.append(c)
            elif isinstance(c, dict):
                code = c.get('countryCode') or c.get('code')
                if code: country_rows.append(str(code))
    attrs = []
    for attr in rule.get('attrDTOList') or []:
        if isinstance(attr, dict):
            attrs.append({'name': str(attr.get('attrName') or ''), 'values': [str(v.get('attrValueName') or '') for v in attr.get('attrValueDTOList') or [] if isinstance(v, dict)]})
    raw_time = row.get('gmtCreate')
    try:
        created = float(raw_time)
        if created > 1e11: created /= 1000
    except (TypeError, ValueError): created = 0
    return {'id': str(row.get('id') or ''), 'title': str(row.get('title') or ''),
            'businessType': row.get('businessType'), 'categories': labels, 'categoryIds': ids,
            'categoryLeaf': str(rule.get('categoryTitle') or (labels[-1] if labels else '未标注类目')),
            'tag': tag, 'tagLabel': str(dto.get('tagName') or tag_label(tag)),
            'subTags': [str(s.get('tagCode') or '') for s in dto.get('subTags') or [] if isinstance(s, dict)],
            'countries': country_rows, 'created': created, 'sourceOrder': order,
            'image': image_url(row.get('sampleImgUrl')), 'reason': str(row.get('reason') or ''),
            'capabilities': [str(c.get('name') or '') for c in rule.get('capacityDtoList') or [] if isinstance(c, dict)],
            'requirements': attrs, 'priceFrom': rule.get('priceFrom'), 'priceTo': rule.get('priceTo'),
            'minOrderFrom': rule.get('minOrdQtyFrom'), 'minOrderTo': rule.get('minOrdQtyTo'),
            'pictureMatch': rule.get('needPicMatch'), 'ruleSummary': rule,
            'review': '平台主题要求，须核对我方产品事实'}


def status(store):
    try:
        return json.loads((STATE / store / 'status.json').read_text(encoding='utf-8'))
    except (OSError, ValueError): return {'status': 'NOT_COLLECTED'}


def collect(store):
    if store not in weekly_update.STORES:
        return {'status': 'FAILED', 'message': '店铺尚未绑定'}
    if not LOCKS[store].acquire(blocking=False): return {'status': 'RUNNING', 'message':'此店铺正在采集'}
    base = STATE / store; base.mkdir(parents=True, exist_ok=True)
    lockfile=base/'collection.lock'
    try:
        fd=os.open(lockfile,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    except FileExistsError:
        LOCKS[store].release();return {'status':'RUNNING','message':'此店铺已有采集进程，未重复抓取'}
    previous=status(store)
    stamp = datetime.now(common.SHANGHAI).strftime('%Y%m%d-%H%M%S')
    candidates=sorted((base/'runs').glob(stamp[:8]+'-*'),reverse=True)
    reusable=candidates[0] if candidates and previous.get('status')=='FAILED' and time.time()-candidates[0].stat().st_mtime<3600 else None
    folder = reusable or base / 'runs' / stamp; folder.mkdir(parents=True, exist_ok=True)
    progress = {'status':'RUNNING','store':store,'label':weekly_update.STORES[store]['label'],'started':common.now(),'business':{}}
    common.atomic_json(base/'status.json', progress)
    connection = None
    try:
        bridge = bridge_catalog.current_bridge()
        expected = weekly_update.STORES[store]['expected_id']
        weekly_update.require_identity(bridge, folder/'identity.json', expected)
        category_path = folder/'categories.json'
        weekly_update.run([bridge/'workctl.cmd','icbu','recruitment-topic','list-user-valid-category','--language','zh','--format','json','--compact-output','off','--output',category_path],cwd=folder,timeout=120)
        categories_data=json.loads(category_path.read_text(encoding='utf-8-sig'))
        if isinstance(categories_data.get('data'),dict): categories_data=categories_data['data']
        categories=categories_data.get('value') or {}
        database=folder/'topics.sqlite'
        if database.exists():database.unlink()
        connection=sqlite3.connect(database)
        connection.execute('CREATE TABLE topics(business TEXT,id TEXT,title TEXT,tag TEXT,leaf TEXT,category_ids TEXT,countries TEXT,created REAL,source_order INTEGER,payload TEXT,PRIMARY KEY(business,id))')
        fingerprints={}
        def save_page(business,number,value):
            rows=value['datas']; fingerprint=tuple(str(r.get('id')) for r in rows)
            if fingerprint and fingerprint in fingerprints.get(business,set()):
                progress['business'][business]['repeatedPages']+=1
            fingerprints.setdefault(business,set()).add(fingerprint)
            for i,row in enumerate(rows):
                item=normalize(row,categories,(number-1)*48+i)
                connection.execute('INSERT INTO topics VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(business,id) DO UPDATE SET source_order=min(topics.source_order,excluded.source_order)',(business,item['id'],item['title'],item['tag'],item['categoryLeaf'],','+','.join(item['categoryIds'])+',','|'+ '|'.join(item['countries'])+'|',item['created'],item['sourceOrder'],json.dumps(item,ensure_ascii=False)))
            connection.commit()
            meta=progress['business'][business];meta['pagesRead']+=1;meta['rowsReturned']+=len(rows)
            meta['latestDeclaredTotal']=value.get('recordCount')
            common.atomic_json(base/'status.json',progress)
        for business in TYPES:
            first=call_page(bridge,folder,business,1)
            total_pages=first['pageCount']
            if total_pages<0 or total_pages>3000: raise weekly_update.SyncError('平台页数异常，停止采集')
            progress['business'][business]={'label':TYPES[business],'totalPages':total_pages,'declaredTotal':first.get('recordCount'),'pagesRead':0,'rowsReturned':0,'repeatedPages':0}
            if total_pages:
                save_page(business,1,first)
            elif first['datas']:
                raise weekly_update.SyncError('平台声明零页但返回了明细，需重新核对')
            with ThreadPoolExecutor(max_workers=3) as pool:
                jobs={pool.submit(call_page,bridge,folder,business,n):n for n in range(2,total_pages+1)}
                for future in as_completed(jobs): save_page(business,jobs[future],future.result())
            progress['business'][business]['uniqueRecords']=connection.execute('SELECT count(*) FROM topics WHERE business=?',(business,)).fetchone()[0]
            weekly_update.require_identity(bridge,folder/'identity.json',expected)
        connection.close();connection=None
        progress.update(status='SUCCESS',collectedAt=common.now(),message='已遍历平台声明分页；重复主题按ID合并，平台声明数与独立明细数分别展示',database=str(database.relative_to(base)))
        common.atomic_json(base/'snapshot.json',progress)
        common.atomic_json(base/'status.json',progress)
        return {'status':'SUCCESS','store':store,'business':progress['business'],'message':progress['message']}
    except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired,weekly_update.SyncError) as error:
        progress.update(status='FAILED',message=str(error) if isinstance(error,weekly_update.SyncError) else '采集失败，未替换上次完整快照',finished=common.now())
        common.atomic_json(base/'status.json',progress)
        return {'status':'FAILED','message':progress['message']}
    finally:
        if connection: connection.close()
        lockfile.unlink(missing_ok=True)
        LOCKS[store].release()


def read_page(store,query=None):
    query=query or {}; business=query.get('businessType','HOT_PRODUCT')
    if store not in weekly_update.STORES or business not in TYPES:return {'status':'NOT_BOUND','store':store,'records':[]}
    job=status(store)
    try:
        base=STATE/store;snap=json.loads((base/'snapshot.json').read_text(encoding='utf-8'));path=base/snap['database']
        if not path.resolve().is_relative_to(base.resolve()):raise ValueError()
        connection=sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True)
    except (OSError,ValueError,KeyError,sqlite3.Error):
        return {'status':'NOT_COLLECTED','store':store,'records':[],'refreshStatus':job.get('status'),'refreshMessage':job.get('message'),'sync':job}
    try:
        where=['business=?'];args=[business]
        if query.get('tag'):where.append("(','||tag||',') LIKE ?");args.append('%,'+str(query['tag'])+',%')
        business_scope = None
        if query.get('category') == MAIN_SCOPE:
            connection.create_function('main_business_topic', 2, main_business_topic, deterministic=True)
            where.append('main_business_topic(leaf,title)=1')
            total = connection.execute('SELECT count(*) FROM topics WHERE business=?', (business,)).fetchone()[0]
            retained = connection.execute('SELECT count(*) FROM topics WHERE business=? AND main_business_topic(leaf,title)=1', (business,)).fetchone()[0]
            business_scope = {'label': '主营营养品', 'totalRecords': total,
                              'retainedRecords': retained, 'excludedRecords': total-retained}
        elif query.get('category'):where.append('leaf=?');args.append(str(query['category']))
        if query.get('country'):where.append('countries LIKE ?');args.append('%|'+str(query['country'])+'|%')
        if query.get('title'):where.append('title LIKE ?');args.append('%'+str(query['title'])[:150]+'%')
        if query.get('recent') in ('true',True,'1'):where.append('created>=?');args.append(time.time()-7*86400)
        clause=' AND '.join(where);count=connection.execute('SELECT count(*) FROM topics WHERE '+clause,args).fetchone()[0]
        size=48;pages=max(1,(count+size-1)//size)
        try:page=max(1,min(pages,int(query.get('page',1))))
        except (ValueError,TypeError):page=1
        order='created DESC,source_order' if query.get('sort')=='newest' else 'source_order'
        rows=connection.execute('SELECT payload FROM topics WHERE '+clause+' ORDER BY '+order+' LIMIT ? OFFSET ?',args+[size,(page-1)*size]).fetchall()
        facets={}
        for name,column in [('tags','tag'),('categories','leaf')]:
            facets[name]=[{'value':r[0],'count':r[1],'label':tag_label(r[0]) if name=='tags' else r[0]} for r in connection.execute('SELECT '+column+',count(*) FROM topics WHERE business=? GROUP BY '+column+' ORDER BY count(*) DESC',(business,)).fetchall()]
        tag_counts={}
        for row in facets['tags']:
            for code in row['value'].split(','):
                if code:tag_counts[code]=tag_counts.get(code,0)+row['count']
        facets['tags']=[{'value':code,'label':tag_label(code),'count':count} for code,count in sorted(tag_counts.items(),key=lambda item:-item[1])]
        country_values=set()
        for row in connection.execute('SELECT DISTINCT countries FROM topics WHERE business=?',(business,)):
            country_values.update(c for c in row[0].split('|') if c)
        facets['countries']=sorted(country_values)
        parsed=[json.loads(r[0]) for r in rows]
        for item in parsed:item['tagLabel']=' / '.join(tag_label(code) for code in item['tag'].split(',') if code)
        pagination={'page':page,'pageSize':size,'totalPages':pages,'totalRecords':count,'view':'filtered'}
        native_meta=snap.get('business',{}).get(business,{})
        filtered=query.get('_unique') is True or any(query.get(k) for k in ('tag','category','country','title')) or query.get('recent') in ('true',True,'1') or query.get('sort')=='newest'
        if not filtered and native_meta.get('totalPages',0)>0:
            native_pages=native_meta['totalPages']
            try:page=max(1,min(native_pages,int(query.get('page',1))))
            except (ValueError,TypeError):page=1
            raw_path=path.parent/(business.lower()+'-'+str(page)+'.json')
            try:
                value=verify_page(unpack(json.loads(raw_path.read_text(encoding='utf-8-sig'))),page,business)
                cats=json.loads((path.parent/'categories.json').read_text(encoding='utf-8-sig'))
                if isinstance(cats.get('data'),dict):cats=cats['data']
                parsed=[normalize(row,cats.get('value',{}),(page-1)*48+i) for i,row in enumerate(value['datas'])]
                for item in parsed:item['tagLabel']=' / '.join(tag_label(code) for code in item['tag'].split(',') if code)
                pagination={'page':page,'pageSize':48,'totalPages':native_pages,'totalRecords':native_meta.get('declaredTotal'),'view':'native','returnedRecords':len(parsed)}
            except (OSError,ValueError,weekly_update.SyncError):
                return {'status':'PAGE_UNAVAILABLE','store':store,'records':[],'message':'该原始页文件不可用，未用其他页冒充','facets':facets,'business':snap.get('business'),'sync':job}
        return {'status':'SUCCESS','store':store,'label':weekly_update.STORES[store]['label'],'records':parsed,
                'businessScope':business_scope,
                'collectedAt':snap.get('collectedAt'),'pagination':pagination,'facets':facets,'business':snap.get('business'),
                'coverage':'完整分页快照；平台声明总量与实际返回的独立明细数分别展示','refreshStatus':job.get('status'),'refreshMessage':job.get('message'),'sync':job}
    finally:connection.close()


if __name__=='__main__':
    import sys
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(collect(sys.argv[1] if len(sys.argv)>1 else 'youhealth'),ensure_ascii=False),flush=True)
