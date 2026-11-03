"""Verify complete materialized CLI files when stdout is compacted to an artifact."""
import hashlib
import json
from pathlib import Path


def account_scoped_messages(conversations, bulk_rows, fetch_duplicate):
    """Use account-scoped fetches when a conversation id collides across sellers."""
    conversations_by_id = {}
    for row in conversations:
        cid = str(row.get('conversationId') or '')
        seller = str(row.get('sellerAliId') or '')
        if not cid or not seller:
            raise ValueError('会话缺少编号或所属销售账号')
        conversations_by_id.setdefault(cid, []).append(row)
    bulk_by_id = {}
    for row in bulk_rows:
        cid = str(row.get('conversationId') or '')
        if not cid:
            raise ValueError('消息缺少会话编号')
        bulk_by_id.setdefault(cid, []).append(row)
    if set(bulk_by_id)-set(conversations_by_id):
        raise ValueError('消息引用了未采集的会话')
    result = {}
    for cid, group in conversations_by_id.items():
        sellers = [str(row['sellerAliId']) for row in group]
        if len(set(sellers)) != len(sellers):
            raise ValueError('同一销售账号内会话编号重复')
        if len(group) == 1:
            rows = bulk_by_id.get(cid, [])
            if len(rows) > 1:
                raise ValueError('唯一会话对应多份消息记录')
            if rows and rows[0].get('sellerAliId') and str(rows[0]['sellerAliId'])!=sellers[0]:
                raise ValueError('消息所属销售账号不匹配')
            result[(sellers[0], cid)] = (rows[0].get('messages') or []) if rows else []
            continue
        rows = bulk_by_id.get(cid, [])
        if len(rows) > len(group):
            raise ValueError('跨账号重复会话的消息记录数量不匹配')
        for row, seller in zip(group, sellers):
            messages = fetch_duplicate(row)
            if not isinstance(messages, list):
                raise ValueError('跨账号重复会话未取得可核验消息')
            result[(seller, cid)] = messages
    if set(result) != {(str(row['sellerAliId']), str(row['conversationId'])) for row in conversations}:
        raise ValueError('账号范围消息映射不完整')
    return result


def save_account_messages(path, source_conversations, source_messages, account_messages):
    """Keep recovered account attribution separately; never rewrite the bulk evidence."""
    sources={Path(p).name:hashlib.sha256(Path(p).read_bytes()).hexdigest()
             for p in (source_conversations,source_messages)}
    rows=[{'sellerAliId':seller,'conversationId':cid,'messages':messages}
          for (seller,cid),messages in account_messages.items()]
    target=Path(path)
    target.write_text(json.dumps({'format':'account-messages/v1','sources':sources,
                                 'conversations':rows},ensure_ascii=False),encoding='utf-8')


def verified_summary(response, fallback, kind, start, end, expected_accounts=None):
    value = response or {}
    if isinstance(value.get('data'), dict) and 'output_file' in value['data']:
        value = value['data']
    path = Path(value.get('output_file') or fallback)
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        meta = data['meta']; rows = data['conversations']
        if meta.get('startDate') != start or meta.get('endDate') != end or meta.get('failureRatio') != 0:
            return None
        if kind == 'conversations':
            if meta.get('totalFailedAccounts') != 0 or meta.get('totalConversations') != len(rows):
                return None
            if expected_accounts is not None and meta.get('totalAccounts') != expected_accounts:
                return None
        else:
            source = Path(meta['sourceConversationFile'])
            original = json.loads(source.read_text(encoding='utf-8-sig'))['conversations']
            expected_ids = {r['conversationId'] for r in original}
            if meta.get('totalInputConversations') != len(original) or meta.get('sourceTotalConversations') != len(original):
                return None
            if not {r['conversationId'] for r in rows}.issubset(expected_ids):
                return None
            if meta.get('totalMessages') != sum(len(r.get('messages') or []) for r in rows):
                return None
            if meta.get('totalConversationsWithMessages') != len(rows):
                return None
        return {**meta, 'status':'success', 'output_file':str(path)}
    except (OSError, ValueError, KeyError, TypeError):
        return None
