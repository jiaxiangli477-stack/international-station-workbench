"""Discover CLI schemas only. Catalog discovery never runs a business action."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import argparse
import json
import re
import sys
import threading

import shared_scan

ROOT = Path(__file__).resolve().parent
STATE = ROOT / '.state' / 'tools'
CATALOG = STATE / 'catalog.json'
DISCOVERY_STATE = STATE / 'discovery-status.json'
DISCOVERY_STATUS_LOCK = threading.Lock()
BRIDGE = ROOT / '.state' / 'yh-check' / 'bridge' / 'bin'
GROUPS = {
    'advisor': ('经营数据', 'analytics', '店铺大盘、流量渠道、地区、产品表现、员工与服务效率'),
    'product': ('商品与市场', 'catalog', '商品资料、类目、行业供需、买家偏好与产品机会'),
    'recruitment-topic': ('定向征品', 'demands', '征品主题、主题要求、产品匹配检测'),
    'tm': ('询盘与买家', 'inquiries', '会话、聊天、买家资料、接待质量与跟进建议'),
    'rfq': ('RFQ 商机', 'bridge', '采购需求搜索、详情、报价历史与权益查询'),
    'ads': ('推广与广告', 'bridge', '推广报告、关键词、诊断；投放变更单独确认'),
    'trade': ('交易与风控', 'bridge', '订单、交易趋势、税费与风险查询'),
    'logistics': ('物流查询', 'bridge', '运费、物流方案与相关订单查询'),
    'cco': ('规则与知识', 'bridge', '平台规则、市场准入与物流知识'),
    'member': ('账号与团队', 'team', '账号成员相关能力，权限变更需确认'),
    'storefront': ('旺铺与内容', 'bridge', '旺铺页面、预览与内容能力，发布需确认'),
    'other': ('店铺健康', 'bridge', '星等级、报告与补充经营工具'),
}
SENSITIVE = re.compile(r'login-token|credential|password|secret|gateway|auth-token', re.I)
SIDE_EFFECT = re.compile(r'(?:^|[-.])(send|publish|create|edit|delete|remove|upload|generate|update|submit|apply|recharge|upgrade)(?:[-.]|$)', re.I)


def record_discovery_status(job_id, status, message, server_id=None, **details):
    if not re.fullmatch(r'[a-f0-9]{32}', str(job_id)) or status not in {'RUNNING', 'SUCCESS', 'FAILED'}:
        raise ValueError('Invalid catalog discovery job state')
    if set(details) - {'tools', 'groups', 'failedSchemas'}:
        raise ValueError('Invalid catalog discovery details')
    if any(not isinstance(value, int) or value < 0 for key, value in details.items() if key != 'failedSchemas'):
        raise ValueError('Invalid catalog discovery counts')
    if 'failedSchemas' in details and (not isinstance(details['failedSchemas'], list)
                                       or any(not isinstance(x, str) for x in details['failedSchemas'])):
        raise ValueError('Invalid failed schema list')
    row = {'jobId': job_id, 'status': status, 'updatedAt': shared_scan.now(),
           'message': str(message)[:180], **details}
    if server_id:
        row['serverId'] = str(server_id)[:40]
    with DISCOVERY_STATUS_LOCK:
        shared_scan.atomic_json(DISCOVERY_STATE, row)
    return row


def read_discovery_status(job_id=None, server_id=None):
    with DISCOVERY_STATUS_LOCK:
        try:
            row = json.loads(DISCOVERY_STATE.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {'status': 'NOT_STARTED', 'message': '尚无接口发现任务'}
    if job_id and row.get('jobId') != job_id:
        return {'status': 'SUPERSEDED', 'message': '该发现任务已被更新的状态替代'}
    if row.get('status') == 'RUNNING' and server_id and row.get('serverId') != server_id:
        return {'jobId':row.get('jobId'),'status':'STALE','message':'服务已重启，该后台任务已中断，可重新发起'}
    return row


def current_bridge():
    candidates = [BRIDGE]
    candidates.extend(p.parent for p in (ROOT / '.state' / 'weekly' / 'runs').glob('*/bridge/bin/workctl.cmd'))
    candidates.extend(p.parent for p in (ROOT / '.state' / 'operations' / 'runs').glob('*/bridge/bin/workctl.cmd'))
    candidates = [p for p in candidates if (p / 'workctl.cmd').is_file()]
    return max(candidates, key=lambda p: (p / 'workctl.cmd').stat().st_mtime, default=BRIDGE)


def cli_schema(path):
    if not re.fullmatch(r'[a-z0-9_.-]+', path):
        raise ValueError('Invalid schema path')
    import weekly_update
    try:
        output = weekly_update.run([current_bridge() / 'workctl.cmd', 'schema', path, '--format', 'json'],
                                   cwd=ROOT, timeout=30)
    except weekly_update.SyncError:
        return {'success': False}
    try:
        data, _ = json.JSONDecoder().raw_decode(output[output.index('{'):])
        return data
    except (ValueError, TypeError):
        return {'success': False}


def describe(group, path, schema):
    mutating = schema.get('mutating')
    risk = 'confirm' if mutating is True or schema.get('requires_yes') or SIDE_EFFECT.search(path) else 'read' if mutating is False else 'unknown'
    if risk == 'unknown' and re.match(r'^(?:data-advisor-|list-|query-|get-|search$|fetch-|rfq-.*(?:search|detail)|product-topic-detect)', path.split('.')[-1]):
        risk = 'query'
    params = schema.get('params') or []
    return {'id': path, 'group': group, 'name': path.split('.')[-1],
            'summary': str(schema.get('summary') or schema.get('description') or '')[:700],
            'risk': risk, 'schemaVerified': schema.get('success') is True,
            'required': [{'name': p.get('name'), 'description': str(p.get('description') or '')[:220]} for p in params if p.get('required')],
            'params': [{'name': p.get('name'), 'description': str(p.get('description') or '')[:220],
                        'type': p.get('type'), 'required': bool(p.get('required')), 'default': p.get('default')}
                       for p in params if p.get('scope') != 'inherited'][:35],
            'mappedModule': GROUPS[group][1], 'execution': 'NOT_CONNECTED'}


def discover():
    STATE.mkdir(parents=True, exist_ok=True)
    nodes = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = {pool.submit(cli_schema, 'icbu.' + group): group for group in GROUPS}
        for future in as_completed(pending):
            group = pending[future]
            try:
                schema = future.result()
                for child in schema.get('children', []):
                    name = child.get('name') or ''
                    path = 'icbu.' + group + '.' + name
                    if re.fullmatch(r'[a-z0-9_.-]+', path) and not SENSITIVE.search(path):
                        nodes[path] = group
            except Exception:
                continue
    entries, failures = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        pending = {pool.submit(cli_schema, path): (path, group) for path, group in nodes.items()}
        for future in as_completed(pending):
            path, group = pending[future]
            try:
                schema = future.result()
                if schema.get('success') is True:
                    entries.append(describe(group, path, schema))
                else:
                    failures.append(path)
            except Exception:
                failures.append(path)
    result = {'discoveredAt': shared_scan.now(), 'status': 'SUCCESS' if entries else 'FAILED',
              'groups': [{'id': key, 'label': values[0], 'module': values[1], 'purpose': values[2]} for key, values in GROUPS.items()],
              'tools': sorted(entries, key=lambda x: x['id']), 'failedSchemas': failures,
              'message': '仅发现并映射接口说明，未执行业务操作'}
    shared_scan.atomic_json(CATALOG, result)
    return result


def read_catalog():
    try:
        return json.loads(CATALOG.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'status': 'NOT_DISCOVERED', 'groups': [], 'tools': [], 'failedSchemas': []}


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--discover', action='store_true')
    args = parser.parse_args()
    if args.discover:
        result = discover()
        print(json.dumps({'status': result['status'], 'tools': len(result['tools']), 'groups': len(result['groups']), 'failed': len(result['failedSchemas'])}, ensure_ascii=False), flush=True)
