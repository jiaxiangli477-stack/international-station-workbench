"""Persistent operations records. Private SQLite, shared by every UI session."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

ROOT = Path(__file__).resolve().parent
STATE = ROOT / '.state' / 'operations'
DB = STATE / 'operations.sqlite'
SHANGHAI = timezone(timedelta(hours=8))
ACTIVE = ('QUEUED', 'RUNNING')

def now():
    return datetime.now(SHANGHAI).isoformat()

@contextmanager
def db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, kind TEXT, scope TEXT, status TEXT, data TEXT, created TEXT, updated TEXT);
      CREATE UNIQUE INDEX IF NOT EXISTS one_active_job ON jobs(scope) WHERE status IN ('QUEUED','RUNNING');
      CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY, source TEXT UNIQUE, data TEXT);
      CREATE TABLE IF NOT EXISTS todos(id TEXT PRIMARY KEY, data TEXT);
    ''')
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

def period(mode, start=None, end=None, today=None):
    from calendar_periods import window
    return window(mode,start,end,today)

def enqueue(kind, scope, payload):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        return enqueue_in(c, kind, scope, payload)


def enqueue_in(c, kind, scope, payload):
    """Caller owns BEGIN IMMEDIATE when a workflow transition must be atomic."""
    old = c.execute("SELECT data FROM jobs WHERE scope=? AND status IN ('QUEUED','RUNNING')", (scope,)).fetchone()
    if old:
        existing = json.loads(old['data'])
        if existing['kind'] != kind or any(existing.get(k) != v for k, v in payload.items()):
            raise ValueError('该产品或范围已有不同的活动请求，请查看原任务，不重复提交')
        return existing
    item = dict(payload, id=uuid.uuid4().hex, kind=kind, status='QUEUED', progress='等待执行', created=now(), updated=now())
    c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)', (item['id'],kind,scope,item['status'],json.dumps(item,ensure_ascii=False),item['created'],item['updated']))
    return item

def record_completed(kind, source, payload):
    item=dict(payload,id=hashlib.sha256(source.encode()).hexdigest()[:32],kind=kind,status='SUCCESS',
              progress='定时更新产物已验证',created=now(),updated=now(),finished=now())
    with db() as c:
        c.execute('INSERT OR IGNORE INTO jobs VALUES(?,?,?,?,?,?,?)',
                  (item['id'],kind,source,'SUCCESS',json.dumps(item,ensure_ascii=False),item['created'],item['updated']))
    return item

def job_update(job_id, **changes):
    with db() as c:
        row = c.execute('SELECT data FROM jobs WHERE id=?',(job_id,)).fetchone()
        if not row:
            raise ValueError('任务不存在')
        item = dict(json.loads(row['data']), **changes, updated=now())
        c.execute('UPDATE jobs SET status=?,data=?,updated=? WHERE id=?',(item['status'],json.dumps(item,ensure_ascii=False),item['updated'],job_id))
        return item

def claim():
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT data FROM jobs WHERE status='QUEUED' ORDER BY created LIMIT 1").fetchone()
        if not row:
            return None
        item=dict(json.loads(row['data']),status='RUNNING',progress='开始执行',updated=now(),workerPid=os.getpid())
        c.execute('UPDATE jobs SET status=?,data=?,updated=? WHERE id=?',('RUNNING',json.dumps(item,ensure_ascii=False),item['updated'],item['id']))
        return item

def records(table):
    if table not in ('jobs','products','todos'):
        raise ValueError('Invalid record type')
    with db() as c:
        return [json.loads(r['data']) for r in c.execute('SELECT data FROM '+table+' ORDER BY rowid DESC')]

def product(product_id):
    with db() as c:
        row=c.execute('SELECT data FROM products WHERE id=?',(product_id,)).fetchone()
    if not row:
        raise ValueError('产品任务不存在')
    return json.loads(row['data'])

def save_product(item):
    with db() as c:
        c.execute('INSERT INTO products VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                  (item['id'],item['source'],json.dumps(item,ensure_ascii=False)))
    return item

def create_product(source, title, references=None, facts=None):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        existing=c.execute('SELECT data FROM products WHERE source=?',(source,)).fetchone()
        if existing:
            return json.loads(existing['data'])
        item={'id':'P-'+uuid.uuid4().hex[:12], 'source':source, 'title':str(title)[:200],
              'references':references or [], 'facts':facts or {}, 'revision':1,
              'stage':'FACTS', 'visual':None, 'draft':None, 'events':[], 'created':now()}
        c.execute('INSERT INTO products VALUES(?,?,?)',(item['id'],source,json.dumps(item,ensure_ascii=False)))
    return item

def archive_draft(product, reason):
    """Snapshot every draft clue before invalidation; caller clears it in its transaction."""
    draft = product.get('draft')
    if draft:
        archived = json.loads(json.dumps(draft, ensure_ascii=False))
        archived.update(invalidatedAt=now(), invalidationReason=reason)
        archived.setdefault('sourceRevision', product.get('revision'))
        if not archived.get('store'):
            archived['store'] = (product.get('facts') or {}).get('store', '')
        product.setdefault('draftHistory', []).append(archived)


def commit_output(product_id, revision, kind, result):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT data FROM products WHERE id=?',(product_id,)).fetchone()
        if not row:
            raise ValueError('产品不存在')
        current=json.loads(row['data'])
        if current['revision']!=revision:
            raise ValueError('执行期间产品资料变化，旧版本产物保留；需先检查产物或草稿后重新审核')
        if kind in ('packaging', 'visual'):
            if current.get('attributePlan'):
                import attribute_plan
                if not attribute_plan.artifact_matches(current, result):
                    raise ValueError('执行期间属性方案变化或产物未绑定当前属性方案，需重新预检并生成')
            archive_draft(current, kind + '_regenerated')
        if kind=='packaging':
            current.update(packaging=result,approvedPackaging=None,visual=None,visualPartial=None,visualPending=None,draft=None,approvedVisual=None,stage='PACKAGING_REVIEW')
        elif kind=='visual':
            current.update(visual=result,visualPartial=None,visualPending=None,draft=None,approvedVisual=None,stage='VISUAL_REVIEW')
        else:
            archive_draft(current, 'listing_readback_completed')
            current.update(draft=result,stage='DRAFT_REVIEW')
        current['events'].append({'time':now(),'message':{'packaging':'包装方向已生成，等待人工审核','visual':'图片产物已核验，等待人工审核','listing':'草稿保存及回读完成，等待人工验收'}[kind]})
        c.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(current,ensure_ascii=False),product_id))
        return current

def amend_product(product_id, facts, expected_revision=None):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT data FROM products WHERE id=?',(product_id,)).fetchone()
        if not row:
            raise ValueError('产品任务不存在')
        item=json.loads(row['data'])
        if expected_revision is not None and expected_revision!=item['revision']:
            raise ValueError('该产品已被其他页面更新，请刷新并核对后再保存')
        normalized={key:str(facts.get(key,'')).strip()[:4000] for key in ('market','form','spec','formula','price','moq','store','mode','design','own_image')}
        changed = {key for key in normalized if normalized[key] != str(item['facts'].get(key, '')).strip()}
        if changed:
            revision = item['revision'] + 1
            archive_draft(item, 'product_facts_changed')
            reused = []
            for asset_key, approval_key in (('packaging', 'approvedPackaging'), ('visual', 'approvedVisual')):
                asset = item.get(asset_key) or {}
                dependencies = set(asset.get('factDependencies', normalized.keys()))
                if asset.get('revision') == item['revision'] and not (dependencies & changed):
                    asset.update(sourceRevision=asset.get('sourceRevision', asset['revision']), revision=revision)
                    reused.append(asset_key)
                else:
                    item[approval_key] = None
            item.update(facts=normalized, revision=revision, stage='FACTS', draft=None, approvedAttributes=None)
            item['events'].append({'time':now(),'message':'资料更新：'+ '、'.join(sorted(changed)) +
                                  ('；复用不受影响的产物：'+ '、'.join(reused) if reused else '；相关审核需重新核对')})
        c.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(item,ensure_ascii=False),product_id))
    return item

def add_followups(store, conversations, job_id):
    added=0
    def instant(value):
        if isinstance(value,(int,float)) or isinstance(value,str) and value.isdigit():
            value=float(value)
            return datetime.fromtimestamp(value/1000 if value>1e11 else value,timezone.utc)
        stamp=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=SHANGHAI)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        for conv in conversations:
            msgs=sorted((m for m in conv.get('messages',[]) if m.get('sendTime')),key=lambda m:instant(m['sendTime']))
            if not msgs:
                continue
            identity=str(conv.get('conversationId') or '')
            if not identity:
                continue
            seller=str(conv.get('sellerAliId') or '')
            legacy_key=hashlib.sha256((store+'|'+identity+'|unanswered').encode()).hexdigest()[:24]
            if seller:
                key=hashlib.sha256((store+'|'+seller+'|'+identity+'|unanswered').encode()).hexdigest()[:24]
            else:
                key=legacy_key
            fingerprint=hashlib.sha256(json.dumps(msgs[-1],sort_keys=True).encode()).hexdigest()
            previous=c.execute('SELECT data FROM todos WHERE id=?',(key,)).fetchone()
            if not previous and seller:
                legacy=c.execute('SELECT data FROM todos WHERE id=?',(legacy_key,)).fetchone()
                # Preserve old deep links only when the old record proves the same account.
                if legacy and json.loads(legacy['data']).get('sellerAliId')==seller:
                    key,previous=legacy_key,legacy
            old=json.loads(previous['data']) if previous else {}
            if msgs[-1].get('senderRole')!='buyer':
                if old and instant(msgs[-1]['sendTime'])>instant(old['messageTime']):
                    old.update(title='已见卖家后续回复，请核对是否完整回答',responseObserved=True,updated=now(),job=job_id)
                    c.execute('UPDATE todos SET data=? WHERE id=?',(json.dumps(old,ensure_ascii=False),key))
                continue
            if '[Card]' in str(msgs[-1].get('content','')):
                continue
            if old and instant(msgs[-1]['sendTime'])<instant(old['messageTime']):
                continue  # Older overlapping periods cannot replace newer evidence or reopen a completed action.
            item=dict(old,id=key,store=store,conversation=identity,buyer=str(conv.get('contactName') or '未命名买家'),
                      owner=old.get('owner') or ' / '.join(conv.get('_owners') or []) or '待分配',
                      title='买家最后一条消息待人工确认是否回复', evidence=str(msgs[-1].get('content',''))[:1000],
                      responseObserved=False,
                      messageTime=msgs[-1]['sendTime'],fingerprint=fingerprint,job=job_id,
                      status=old.get('status','OPEN') if old.get('fingerprint')==fingerprint else 'OPEN',
                      note=old.get('note',''),product=old.get('product',''),updated=now())
            if seller:
                item['sellerAliId']=seller
            c.execute('INSERT OR REPLACE INTO todos VALUES(?,?)',(key,json.dumps(item,ensure_ascii=False)))
            added+=not bool(old)
    return added

def update_todo(todo_id, changes):
    with db() as c:
        row=c.execute('SELECT data FROM todos WHERE id=?',(todo_id,)).fetchone()
        if not row:
            raise ValueError('跟进事项不存在')
        item=json.loads(row['data'])
        for key in ('owner','note','status','product'):
            if key in changes:
                item[key]=str(changes[key]).strip()[:2000]
        if item['status'] not in ('OPEN','IN_PROGRESS','DONE'):
            raise ValueError('无效跟进状态')
        if item.get('product'):
            product(item['product'])
        item['updated']=now()
        c.execute('UPDATE todos SET data=? WHERE id=?',(json.dumps(item,ensure_ascii=False),todo_id))
    return item
