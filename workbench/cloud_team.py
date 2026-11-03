"""Outbound-only public request inbox. Public submissions never execute a Skill."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import threading
from urllib.request import Request, build_opener, HTTPRedirectHandler

import task_store

ROOT=Path(__file__).resolve().parent
STATE=ROOT/'.state/cloud-team'
SITE='https://jiaxiang-product-tasks-20261027.rodericksmolyar10941.chatgpt.site'
UUID=re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}',re.I)
_lock=threading.Lock()
_started=False

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def now():return datetime.now(timezone.utc).isoformat()

def connection():
    STATE.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(STATE/'inbox.sqlite3',timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, data TEXT NOT NULL)')
    return db

def rows():
    with closing(connection()) as db:
        return [json.loads(r[0]) for r in db.execute("SELECT data FROM requests ORDER BY json_extract(data,'$.status')='RECEIVED_LOCAL' DESC, rowid DESC LIMIT 100")]

def find(identity):
    with closing(connection()) as db:
        row=db.execute('SELECT data FROM requests WHERE id=?',(identity,)).fetchone()
        return json.loads(row[0]) if row else None

def save(item):
    with closing(connection()) as db,db:
        db.execute('INSERT INTO requests VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(item['id'],json.dumps(item,ensure_ascii=False)))

def request(path,payload=None):
    config=json.loads((STATE/'config.json').read_text(encoding='utf-8'))
    if config.get('url')!=SITE or len(config.get('token',''))<32:raise ValueError('云端连接配置无效')
    body=json.dumps(payload).encode() if payload is not None else None
    req=Request(SITE+path,data=body,headers={'Authorization':'Bearer '+config['token'],'Content-Type':'application/json',
                                           'User-Agent':'JiaxiangWorkbenchConnector/1.0','Accept':'application/json'})
    with build_opener(NoRedirect()).open(req,timeout=12) as response:
        if int(response.headers.get('Content-Length','0'))>300000:raise ValueError('云端响应过大')
        data=response.read(300001)
        if len(data)>300000:raise ValueError('云端响应过大')
        return json.loads(data)

def validate(item):
    if not isinstance(item,dict) or not UUID.fullmatch(item.get('id','')):raise ValueError('申请编号无效')
    if item.get('store') not in ('youhealth','lifeworthcn') or item.get('taskType') not in ('images','research'):raise ValueError('任务范围无效')
    ids=item.get('selected')
    if not isinstance(ids,list) or not 1<=len(ids)<=10 or any(not isinstance(x,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',x) for x in ids):raise ValueError('候选列表无效')
    if not isinstance(item.get('note'),str) or len(item['note'])>500:raise ValueError('备注无效')
    return {k:item[k] for k in ('id','store','taskType','selected','note','createdAt')}

def sync_once():
    if not (STATE/'config.json').is_file():return {'status':'NOT_CONFIGURED'}
    if not _lock.acquire(blocking=False):return {'status':'BUSY'}
    try:
        data=request('/api/agent/requests');incoming=data.get('requests')
        if not isinstance(incoming,list) or len(incoming)>100:raise ValueError('申请列表无效')
        added=0
        for value in incoming:
            item=validate(value);prior=find(item['id'])
            if prior:
                if any(prior.get(k)!=item[k] for k in ('store','taskType','selected','note')):raise ValueError('同编号申请发生变化')
                status=prior['status']
            else:
                item.update(status='RECEIVED_LOCAL',receivedAt=now());save(item);added+=1;status='RECEIVED_LOCAL'
            request('/api/agent/status',{'id':item['id'],'status':status})
        with closing(connection()) as db:
            pending=db.execute("SELECT COUNT(*) FROM requests WHERE json_extract(data,'$.status')='RECEIVED_LOCAL'").fetchone()[0]
        health={'status':'SUCCESS','updatedAt':now(),'added':added,'pending':pending}
    except Exception as error:
        health={'status':'FAILED','updatedAt':now(),'errorType':type(error).__name__,'message':'云端申请尚未同步；原记录保留，不启动Skill'}
    finally:_lock.release()
    from shared_scan import atomic_json
    atomic_json(STATE/'health.json',health)
    return health

def review(identity,approve):
    if not isinstance(identity,str) or not UUID.fullmatch(identity):raise ValueError('申请编号无效')
    with _lock:
        item=find(identity)
        if not item:raise ValueError('申请不存在，请先同步')
        if item['status']=='ADOPTED_LOCAL' and approve:return {'items':item['items'],'store':item['store'],'taskType':item['taskType']}
        if item['status']!='RECEIVED_LOCAL':raise ValueError('此申请已处理')
        if approve:
            import operations_api
            adopted=operations_api.command({'action':'workflow.adopt','source':'selection','ids':item['selected'],'store':item['store']})
            item.update(status='ADOPTED_LOCAL',items=adopted['items'],reviewedAt=now())
        else:item.update(status='REJECTED',reviewedAt=now())
        save(item)
        try:request('/api/agent/status',{'id':identity,'status':item['status']})
        except Exception:pass  # The next outbound sync retries only this status acknowledgement.
        return {'items':item.get('items',[]),'store':item['store'],'taskType':item['taskType']}

def start():
    global _started
    if _started or not (STATE/'config.json').is_file():return
    _started=True
    def loop():
        import time
        while True:
            sync_once();time.sleep(60)
    threading.Thread(target=loop,name='public-request-inbox',daemon=True).start()
