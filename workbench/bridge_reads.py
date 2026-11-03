"""Narrow, store-checked read adapters. No arbitrary command execution endpoint."""
from pathlib import Path
import json
import sys
import re
import threading

import shared_scan
import weekly_update
import bridge_catalog

ROOT = Path(__file__).resolve().parent
STATE = ROOT / '.state' / 'tools' / 'live'
TOPIC_REFRESH_STATUS_LOCK = threading.Lock()


def topic_refresh_path(store):
    if store not in weekly_update.STORES:
        raise ValueError('店铺尚未绑定')
    return STATE / (store + '-refresh.json')


def write_topic_refresh_status(store, job_id, status, message, server_id=None):
    if not re.fullmatch(r'[a-f0-9]{32}', str(job_id)) or status not in {'RUNNING', 'SUCCESS', 'FAILED', 'ALREADY_RUNNING'}:
        raise ValueError('无效主题刷新状态')
    row = {'jobId': job_id, 'store': store, 'status': status,
           'message': str(message)[:180], 'updatedAt': shared_scan.now()}
    if server_id:
        row['serverId'] = str(server_id)[:40]
    with TOPIC_REFRESH_STATUS_LOCK:
        shared_scan.atomic_json(topic_refresh_path(store), row)
    return row


def read_topic_refresh_status(store, server_id=None):
    path = topic_refresh_path(store)
    with TOPIC_REFRESH_STATUS_LOCK:
        try:
            row=json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {'status': 'NOT_STARTED', 'store': store, 'message': '尚无主题刷新任务'}
    if row.get('status') == 'RUNNING' and server_id and row.get('serverId') != server_id:
        return {'jobId':row.get('jobId'),'store':store,'status':'STALE',
                'message':'服务已重启，状态无法确认；重试前需核对残留 collection.lock'}
    return row


def image_url(value):
    value = str(value or '')
    if value.startswith('//'):
        value = 'https:' + value
    return value if re.match(r'^https://[a-zA-Z0-9.-]+\.(?:alicdn\.com|alibaba\.com)/', value) else ''


def normalize_topics(records, categories):
    result = []
    categories = categories.get('value', {}) if isinstance(categories, dict) else {}
    for row in records:
        if not isinstance(row, dict):
            continue
        ids = str(row.get('categoryIds') or row.get('categoryId') or '').split(',')
        labels = [str((categories.get(i) or {}).get('name') or i) for i in ids if i]
        result.append({'id': str(row.get('id') or ''), 'title': str(row.get('title') or ''),
                       'categories': labels, 'categoryIds': ids,
                       'businessType': str(row.get('businessType') or ''),
                       'reason': str(row.get('reason') or ''), 'image': image_url(row.get('sampleImgUrl')),
                       'capabilities': row.get('capacityNameList') if isinstance(row.get('capacityNameList'), list) else [],
                       'ruleSummary': row.get('ruleDTO') if isinstance(row.get('ruleDTO'), dict) else {},
                       'status': str(row.get('status') or ''), 'review': '待类目与需求复核'})
    return result


def _call(cli, args, output):
    command = [str(cli), *args, '--format', 'json', '--compact-output', 'off', '--output', str(output)]
    try:
        weekly_update.run(command, cwd=ROOT, timeout=120)
    except weekly_update.SyncError:
        raise weekly_update.SyncError('只读查询未成功，请核对当前账号连接或权限') from None
    if not output.is_file():
        raise weekly_update.SyncError('只读查询未成功，请核对当前账号连接或权限')
    data = json.loads(output.read_text(encoding='utf-8-sig'))
    if isinstance(data, dict) and isinstance(data.get('data'), dict) and 'value' in data['data']:
        data = data['data']
    if not isinstance(data, dict) or data.get('success') is not True:
        raise weekly_update.SyncError('平台未返回成功结果，未覆盖旧缓存')
    return data


def refresh_topics(store):
    from recruitment import collect
    return collect(store)


def read_topics(store, query=None):
    from recruitment import read_page
    return read_page(store, query)


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    store = sys.argv[1] if len(sys.argv)>1 else 'youhealth'
    print(json.dumps(refresh_topics(store), ensure_ascii=False))
