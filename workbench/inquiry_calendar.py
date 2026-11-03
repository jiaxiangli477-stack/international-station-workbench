"""Collect closed calendar periods through verified, bounded upstream segments."""
from datetime import datetime,timezone
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from calendar_periods import chunks,kind,window as calendar_window,SHANGHAI
from bridge_materialization import verified_summary

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=1),encoding='utf-8');temp.replace(path)

def message_date(value):
    if isinstance(value,(int,float)) or isinstance(value,str) and value.isdigit():
        stamp=float(value);stamp=stamp/1000 if stamp>1e11 else stamp
        return datetime.fromtimestamp(stamp,timezone.utc).astimezone(SHANGHAI).date().isoformat()
    if not isinstance(value,str):raise ValueError('消息时间缺失，不能归入自然期间')
    try:
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=SHANGHAI)
        return stamp.astimezone(SHANGHAI).date().isoformat()
    except ValueError:raise ValueError('消息时间格式未知，不能归入自然期间') from None

def message_key(message, raw=False):
    """Match the upstream time/from/text -> sendTime/senderRole/content normalizer."""
    raw=raw and any(k in message for k in ('time','from','text'))
    value=message.get('time') if raw else message.get('sendTime')
    message_date(value)
    if isinstance(value,(int,float)) or isinstance(value,str) and value.isdigit():
        stamp=float(value);stamp=stamp/1000 if stamp>1e11 else stamp
        stamp=datetime.fromtimestamp(stamp,timezone.utc)
    else:
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=SHANGHAI)
    role=('buyer' if message.get('from')=='buyer' else 'seller') if raw else message.get('senderRole')
    content=(message.get('text') or '') if raw else (message.get('content') or '')
    return stamp.astimezone(timezone.utc).isoformat(),role,json.dumps(content,sort_keys=True,ensure_ascii=False)


def message_inventory(rows,part,raw=False,owners=None,aggregate=False):
    result=Counter()
    for c in rows:
        cid=str(c.get('conversationId') or '')
        if not cid:raise ValueError('会话编号缺失')
        seller=str(c.get('sellerAliId') or '')
        if not aggregate and not seller:
            candidates=owners.get(cid,set()) if owners else set()
            if len(candidates)!=1:raise ValueError('消息缺少可核验的所属销售账号')
            seller=next(iter(candidates))
        if not aggregate and owners is not None and seller not in owners.get(cid,set()):
            raise ValueError('消息所属销售账号与原始会话不匹配')
        for m in c.get('messages',[]):
            key=message_key(m,raw)
            day=datetime.fromisoformat(key[0]).astimezone(SHANGHAI).date().isoformat()
            if part['start']<=day<=part['end']:result[((cid,) if aggregate else (seller,cid))+key]+=1
    return result

def conversation_key(conversation):
    cid=str(conversation.get('conversationId') or '')
    owner=str(conversation.get('sellerAliId') or '')
    if not cid or not owner:raise ValueError('会话编号或所属销售账号缺失')
    return owner,cid


def verified_part(folder,expected,part):
    folder=Path(folder);data=read(folder/'conversations.json');actual=data.get('window',{});identity=data.get('store',{})
    if str(identity.get('aliId'))!=str(expected) or str(actual.get('since',''))[:10]!=part['start'] or str(actual.get('until',''))[:10]!=part['end']:raise ValueError('分段数据店铺或日期不匹配')
    conv=verified_summary(None,folder/'.work/conversations_all.json','conversations',part['start'],part['end'],expected_accounts=identity.get('accountCount'))
    msgs=verified_summary(None,folder/'.work/messages_all.json','messages',part['start'],part['end'])
    if not conv or not msgs or not isinstance(read(folder/'buyers.json'),list):raise ValueError('分段会话、消息或画像未完整通过核验')
    raw=read(folder/'.work/conversations_all.json')['conversations']
    if {conversation_key(c) for c in raw}!={conversation_key(c) for c in data.get('conversations',[])}:raise ValueError('规范化会话与原始分页编号不一致')
    ids=[conversation_key(c) for c in data.get('conversations',[])]
    if len(ids)!=len(set(ids)) or len(raw)!=len(ids):raise ValueError('规范化或原始会话编号重复')
    raw_by_key={conversation_key(c):c for c in raw}
    for c in data['conversations']:
        buyer=raw_by_key[conversation_key(c)].get('contactAliId')
        if buyer and str(c.get('contactAliId') or '')!=str(buyer):raise ValueError('规范化会话买家与原始记录不匹配')
    raw_messages=read(folder/'.work/messages_all.json')['conversations']
    owners={}
    for c in raw:owners.setdefault(str(c['conversationId']),set()).add(str(c['sellerAliId']))
    account_file=folder/'.work/account_messages.json'
    if account_file.is_file():
        account=read(account_file)
        hashes={name:hashlib.sha256((folder/'.work'/name).read_bytes()).hexdigest()
                for name in ('conversations_all.json','messages_all.json')}
        if account.get('format')!='account-messages/v1' or account.get('sources')!=hashes:
            raise ValueError('账号消息证据与本次原始采集不匹配')
        scoped=account.get('conversations',[])
        if len(scoped)!=len(raw) or {conversation_key(c) for c in scoped}!={conversation_key(c) for c in raw}:
            raise ValueError('账号消息证据未完整覆盖原始会话')
        if message_inventory(scoped,part,raw=True,aggregate=True)!=message_inventory(raw_messages,part,raw=True,aggregate=True):
            raise ValueError('账号补取消息与原始窗口内消息不一致')
        raw_messages=scoped
    if message_inventory(raw_messages,part,raw=True,owners=owners)!=message_inventory(data['conversations'],part):
        raise ValueError('规范化窗口内消息与原始消息内容、角色、时间或重复次数不一致')
    return data

def merge_parts(parts,output,expected,start,end):
    expected_parts=chunks(start,end)
    if [p for _,p in parts]!=expected_parts:raise ValueError('自然期间分段不连续或不完整')
    conversations={};raw_rows={};buyers={};message_keys={};store=None;contacts={};sources=[];source_messages=Counter()
    for folder,part in parts:
        folder=Path(folder);data=verified_part(folder,expected,part)
        source_messages |= message_inventory(data['conversations'],part)
        sources.append({'period':part,'rawTotalMessages':read(folder/'.work/messages_all.json')['meta']['totalMessages'],
                        'rawTotalConversations':read(folder/'.work/conversations_all.json')['meta']['totalConversations'],
                        'store':str(expected),'accounts':data['store']['accountCount'],
                        'windowMessages':sum(message_inventory(data['conversations'],part).values()),
                        'sha256':{name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in (
                            ('messages_all.json',folder/'.work/messages_all.json'),
                            ('conversations_all.json',folder/'.work/conversations_all.json'),
                            ('conversations.json',folder/'conversations.json'))}})
        if store and data['store'].get('accountCount')!=store.get('accountCount'):raise ValueError('分段子账号覆盖发生变化，不能假定整月完整')
        store=data['store']
        for row in read(folder/'.work/conversations_all.json')['conversations']:raw_rows[conversation_key(row)]=row
        for c in data['conversations']:
            cid=conversation_key(c)
            if cid in conversations and c.get('contactAliId') and conversations[cid].get('contactAliId') and str(c['contactAliId'])!=str(conversations[cid]['contactAliId']):raise ValueError('同一会话编号对应不同买家，停止合并')
            old=conversations.setdefault(cid,dict(c,messages=[],_owners=[]));seen=message_keys.setdefault(cid,set())
            for owner in (c.get('_owners') or [c.get('sellerName')]):
                if owner and owner not in old['_owners']:old['_owners'].append(owner)
            if c.get('channel')=='询盘':old['channel']='询盘'
            if c.get('crm'):old['crm']={**old.get('crm',{}),**{k:v for k,v in c['crm'].items() if v not in (None,'',[])}}
            occurrences={}
            for m in c.get('messages',[]):
                day=message_date(m.get('sendTime'))
                if not part['start']<=day<=part['end']:continue
                # Keep repeated identical messages within a segment; dedupe only corresponding occurrences across segments.
                signature=message_key(m)
                index=occurrences.get(signature,0);occurrences[signature]=index+1;key=(signature,index)
                if key not in seen:seen.add(key);old['messages'].append(m)
        for buyer in read(folder/'buyers.json'):
            key=str(buyer.get('contactAliId') or buyer.get('contactLoginId') or hashlib.sha256(json.dumps(buyer,sort_keys=True,ensure_ascii=False).encode()).hexdigest());buyers[key]=buyer
        cp=folder/'contacts.json'
        if cp.is_file():contacts.update(read(cp).get('contacts',{}))
    rows=list(conversations.values())
    if message_inventory(rows,{'start':start,'end':end})!=source_messages:
        raise ValueError('合并消息与原分段窗口内消息多重集合不一致')
    for c in rows:c['messages'].sort(key=lambda m:str(m.get('sendTime') or ''))
    out=Path(output);out.mkdir(parents=True,exist_ok=True);work=out/'.work';work.mkdir(exist_ok=True)
    base_meta={'startDate':start,'endDate':end,'failureRatio':0,'calendarPeriod':kind(start,end),'timezone':'Asia/Shanghai','segments':len(parts)}
    raw=list(raw_rows.values());raw_path=(work/'conversations_all.json').resolve()
    write(raw_path,{'conversations':raw,'meta':dict(base_meta,totalConversations=len(raw),totalAccounts=store['accountCount'],totalFailedAccounts=0)})
    raw_messages=[{'conversationId':c['conversationId'],'sellerAliId':c['sellerAliId'],'messages':[{'time':m['sendTime'],'from':m['senderRole'],'text':m.get('content','')} for m in c['messages']]} for c in rows if c['messages']]
    total=sum(len(c['messages']) for c in rows)
    write(work/'messages_all.json',{'conversations':raw_messages,'meta':dict(base_meta,sourceConversationFile=str(raw_path),sourceTotalConversations=len(raw),totalInputConversations=len(raw),totalConversationsWithMessages=len(raw_messages),totalMessages=total)})
    normalized={'window':{'since':start+'T00:00:00','until':end+'T23:59:59','kind':kind(start,end),'timezone':'Asia/Shanghai','basis':'calendar'},'store':store,'conversations':rows}
    write(out/'conversations.json',normalized);write(out/'buyers.json',list(buyers.values()))
    if contacts:write(out/'contacts.json',{'store':{'CURRENT_SELF_ALIID':str(expected)},'window':{'start':start,'end':end},'contacts':contacts})
    stats={'window':{'start':start,'end':end},'calendarPeriod':kind(start,end),'accounts':store['accountCount'],'conversations':len(rows),'messages':total,'inquiry_conversations':sum(c.get('channel')=='询盘' for c in rows),'tm_conversations':sum(c.get('channel')!='询盘' for c in rows),'buyers_with_persona':len(buyers),'segments':len(parts)}
    write(out/'fetch_stats.json',stats)
    if not verified_summary(None,raw_path,'conversations',start,end,expected_accounts=store['accountCount']) or not verified_summary(None,work/'messages_all.json','messages',start,end):raise ValueError('自然期间合并结果未通过完整性验证')
    write(out/'calendar-collection.json',{'status':'VERIFIED','period':normalized['window'],'parts':[p for _,p in parts],'counts':stats,'sources':sources})
    return stats

def collect(engine,bridge,expected,period,env=None,progress=None):
    import weekly_update as weekly
    import inquiry_release
    # Revalidate before any network read. Legacy rolling jobs cannot silently acquire a new label.
    calendar_window('custom',period['start'],period['end'])
    engine=Path(engine);parts=[]
    for index,part in enumerate(chunks(period['start'],period['end']),1):
        destination=engine/'calendar-chunks'/part['start'];destination.mkdir(parents=True,exist_ok=True)
        for name in ('fetch_inquiries.py','fetch_buyer_contacts.py','bridge_materialization.py'):shutil.copy2(engine/name,destination/name)
        if progress:progress('采集自然期间分段 '+str(index)+'：'+part['start']+' 至 '+part['end'])
        weekly.require_identity(bridge,engine/'identity-calendar.json',expected)
        import bridge_runtime
        env=bridge_runtime.child_environment(Path(bridge)/'workctl.cmd',os.environ if env is None else env)
        days=(datetime.fromisoformat(part['end'])-datetime.fromisoformat(part['start'])).days+1
        weekly.run([sys.executable,destination/'fetch_inquiries.py','--days',str(days),'--end-date',part['end'],'--refresh-identity'],destination,timeout=14400,env=env)
        weekly.require_identity(bridge,engine/'identity-calendar.json',expected)
        verified_part(destination/'inquiry',expected,part)
        inquiry_release.collect_contacts(destination,bridge,expected,part['start'],part['end'],env)
        weekly.require_identity(bridge,engine/'identity-calendar.json',expected)
        parts.append((destination/'inquiry',part))
    return merge_parts(parts,engine/'inquiry',expected,period['start'],period['end'])
