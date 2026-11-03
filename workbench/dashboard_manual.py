"""Durable, versioned manual dashboard inputs; independent of generated snapshots."""
from __future__ import annotations
from contextlib import closing
from calendar import monthrange
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import re
import sqlite3
import uuid

DB=Path(__file__).resolve().parent/'.state/dashboard-manual.sqlite3'
COUNTS={'acquisition','quality_customers','sample_orders','new_count'}
MONEY={'cac','annual_fee','wendin','topshow','brand_ad','ad_spend_override'}
TEXT={'sample_products','order_products'}
FIELDS=COUNTS|MONEY|TEXT|{'new_selection'}
FORMAT='workbench-dashboard-manual/v1'

class Conflict(ValueError):
    def __init__(self,current):
        super().__init__('录入记录已被另一页面更新，请重新载入后核对；本次未覆盖。')
        self.current=current

def validate_key(store,kind,start,end):
    if not isinstance(store,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',store):raise ValueError('店铺编号无效')
    if kind not in ('week','month'):raise ValueError('周期类型无效')
    try:a,b=date.fromisoformat(start),date.fromisoformat(end)
    except (ValueError,TypeError):raise ValueError('统计日期无效') from None
    if start!=a.isoformat() or end!=b.isoformat():raise ValueError('统计日期须为ISO日期')
    if kind=='week' and (a.weekday()!=0 or (b-a).days!=6):raise ValueError('录入周期须为完整自然周')
    if kind=='month' and (a.day!=1 or a.month!=b.month or a.year!=b.year or b.day!=monthrange(a.year,a.month)[1]):raise ValueError('录入周期须为完整自然月')
    return store,kind,start,end

def validate_fields(fields):
    if not isinstance(fields,dict) or set(fields)-FIELDS:raise ValueError('包含未支持的录入字段')
    out={}
    for key,value in fields.items():
        if key in COUNTS|MONEY:
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<0 or value>1e12 or key in COUNTS and value!=int(value)):
                raise ValueError('录入数量/金额须为有效非负数，数量须为整数')
        elif key in TEXT:
            if not isinstance(value,str) or len(value)>8000:raise ValueError('产品备注过长或格式无效')
        elif key=='new_selection':
            if not isinstance(value,list) or len(value)>3000 or any(not isinstance(v,str) or not re.fullmatch(r'\d{1,32}',v) for v in value):raise ValueError('新品编号须为原始数字字符串')
            value=list(dict.fromkeys(value))
        out[key]=value
    return out

def connection(db):
    p=Path(db);p.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(p,timeout=10);c.row_factory=sqlite3.Row
    c.execute('''CREATE TABLE IF NOT EXISTS manual_history(
        id TEXT PRIMARY KEY, store TEXT NOT NULL, kind TEXT NOT NULL,
        start TEXT NOT NULL, end TEXT NOT NULL, revision INTEGER NOT NULL,
        fields_json TEXT NOT NULL, updated_at TEXT NOT NULL, source TEXT NOT NULL,
        UNIQUE(store,kind,start,end,revision))''')
    c.commit();return c

def empty(key):
    return dict(zip(('store','kind','start','end'),key),revision=0,fields={},updatedAt=None)

def from_row(row):
    if row is None:return None
    return {k:row[k] for k in ('id','store','kind','start','end','revision','source')} | {'fields':json.loads(row['fields_json']),'updatedAt':row['updated_at']}

def latest(c,key):
    row=c.execute('SELECT * FROM manual_history WHERE store=? AND kind=? AND start=? AND end=? ORDER BY revision DESC LIMIT 1',key).fetchone()
    return from_row(row) if row else empty(key)

def load(store,kind,start,end,*,db=DB):
    key=validate_key(store,kind,start,end)
    if not Path(db).exists():return empty(key)
    with closing(sqlite3.connect(Path(db).resolve().as_uri()+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row;return latest(c,key)

def save(store,kind,start,end,changes,revision,*,db=DB,source='workbench'):
    key=validate_key(store,kind,start,end);changes=validate_fields(changes)
    if type(revision) is not int or revision<0:raise ValueError('记录版本无效')
    with closing(connection(db)) as c,c:
        c.execute('BEGIN IMMEDIATE');current=latest(c,key)
        if current['revision']!=revision:raise Conflict(current)
        fields=current['fields']|changes
        if not changes or fields==current['fields']:return current
        record=dict(zip(('store','kind','start','end'),key),id=uuid.uuid4().hex,revision=revision+1,fields=fields,updatedAt=datetime.now(timezone.utc).isoformat(),source=source)
        c.execute('INSERT INTO manual_history VALUES(?,?,?,?,?,?,?,?,?)',(record['id'],*key,record['revision'],json.dumps(fields,ensure_ascii=False),record['updatedAt'],source))
        return record

def export_store(store,*,db=DB):
    if not isinstance(store,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',store):raise ValueError('店铺编号无效')
    entries=[]
    if Path(db).exists():
        with closing(sqlite3.connect(Path(db).resolve().as_uri()+'?mode=ro',uri=True)) as c:
            c.row_factory=sqlite3.Row
            entries=[from_row(row) for row in c.execute('SELECT * FROM manual_history WHERE store=? ORDER BY kind,start,revision',(store,))]
    return {'format':FORMAT,'store':store,'entries':entries}

def import_backup(bundle,store,*,db=DB):
    if not isinstance(bundle,dict) or bundle.get('format')!=FORMAT or bundle.get('store')!=store or not isinstance(bundle.get('entries'),list) or len(bundle['entries'])>5000:raise ValueError('备份格式或店铺不匹配')
    records=[]
    for r in bundle['entries']:
        if not isinstance(r,dict) or r.get('store')!=store or not isinstance(r.get('id'),str) or not re.fullmatch(r'[a-f0-9]{32}',r['id']):raise ValueError('备份记录或店铺不匹配')
        key=validate_key(r['store'],r.get('kind'),r.get('start'),r.get('end'))
        fields=validate_fields(r.get('fields'))
        if not isinstance(r.get('updatedAt'),str) or len(r['updatedAt'])>50:raise ValueError('备份时间格式无效')
        records.append((r,key,fields))
    imported=0
    with closing(connection(db)) as c,c:
        c.execute('BEGIN IMMEDIATE');existing=set()
        for _,key,_ in records:
            if latest(c,key)['revision']:existing.add(key)
        for r,key,fields in records:
            found=c.execute('SELECT * FROM manual_history WHERE id=?',(r['id'],)).fetchone()
            if found:
                prior=from_row(found)
                if tuple(prior[k] for k in ('store','kind','start','end'))!=key or prior['fields']!=fields:raise ValueError('备份记录ID冲突')
                continue
            current=latest(c,key)
            if key in existing:raise Conflict(current)
            c.execute('INSERT INTO manual_history VALUES(?,?,?,?,?,?,?,?,?)',(r['id'],*key,current['revision']+1,json.dumps(fields,ensure_ascii=False),r['updatedAt'],'backup-import'))
            imported+=1
    return {'imported':imported,'backup':export_store(store,db=db)}

def merge_into_data(data,*,db=DB):
    store=str(data['meta']['store_id']);bundle=export_store(store,db=db)
    data['manual_history']=bundle
    latest_records={(r['kind'],r['start'],r['end']):r for r in bundle['entries']}
    for name,part in data.get('audit_periods',{}).items():
        kind=name.split(':',1)[0];p=part['period']
        record=latest_records.get((kind,p[kind+'_start'],p[kind+'_end']),empty((store,kind,p[kind+'_start'],p[kind+'_end'])))
        part['boss']['manual'].update(record['fields']);part['manual_record']=record
    return data

def scope(payload):
    from weekly_update import STORES
    from shared_scan import read_index
    if not isinstance(payload,dict):raise ValueError('请求必须为对象')
    key=validate_key(payload.get('store'),payload.get('kind'),payload.get('start'),payload.get('end'))
    alias=next((alias for alias,cfg in STORES.items() if str(cfg['expected_id'])==key[0]),None)
    if alias is None:raise ValueError('店铺尚未核验')
    snapshot=payload.get('snapshot')
    if snapshot:
        record=next((r for r in read_index().get('records',[]) if r['id']==snapshot),None)
        if not record or record.get('store')!=alias or record.get('kind')!='data' or not any(r['kind']==key[1] and r['start']==key[2] and r['end']==key[3] for r in record.get('rows',[])):raise ValueError('快照店铺或统计期间不匹配')
    return key

def command(payload,*,db=DB):
    key=scope(payload);action=payload.get('action','load')
    if action=='load':return {'record':load(*key,db=db),'backup':export_store(key[0],db=db)}
    if action=='save':return {'record':save(*key,payload.get('changes'),payload.get('revision'),db=db)}
    if action=='export':return {'backup':export_store(key[0],db=db)}
    if action=='import':return import_backup(payload.get('backup'),key[0],db=db)
    raise ValueError('未支持的录入操作')
