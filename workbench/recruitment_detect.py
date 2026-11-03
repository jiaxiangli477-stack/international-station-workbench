"""Read-only draft eligibility checks with account, scope and file evidence binding."""
from datetime import datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re

COMMAND = 'icbu.recruitment-topic.product-topic-detect'
MAX_AGE = timedelta(hours=24)


def target(product):
    import weekly_update
    draft = product.get('draft') or {}
    rec = product.get('recruitment') or {}
    store = (product.get('facts') or {}).get('store')
    revision = product.get('revision')
    if (not product.get('id') or type(revision) is not int or revision < 1
            or store not in weekly_update.STORES
            or draft.get('status') != 'completed' or draft.get('readback_verified') is not True
            or type(draft.get('revision')) is not int or draft['revision'] != revision
            or draft.get('store') != store or draft.get('expected_store', store) != store
            or rec.get('store') != store
            or not re.fullmatch(r'[1-9][0-9]{0,24}', str(draft.get('draft_id', '')))
            or not re.fullmatch(r'[1-9][0-9]{0,24}', str(rec.get('topicId', '')))
            or not re.fullmatch(r'[a-f0-9]{64}', str(rec.get('fingerprint', '')))):
        raise ValueError('需同版本、同店铺且实际回读通过的草稿及有效征品主题')
    expected = weekly_update.STORES[store].get('expected_id')
    if not expected:
        raise ValueError('店铺身份尚未绑定，未执行征品检测')
    return {'product': product['id'], 'revision': revision, 'store': store,
            'draft_id': str(draft['draft_id']), 'topic_id': str(rec['topicId']),
            'sourceFingerprint': rec['fingerprint'], 'expected_account': str(expected)}


def _schema(value):
    if (value.get('success') is not True
            or value.get('command') != 'workctl icbu recruitment-topic product-topic-detect'
            or value.get('mutating') is True or value.get('requires_yes')):
        raise ValueError('征品只读检测接口契约变化，未执行')
    params = {p.get('name'): p for p in value.get('params', []) if isinstance(p, dict)}
    for name, flag, kind, required in [('productId', '--prod-id', 'integer', True),
                                       ('topicId', '--topic-id', 'integer', True),
                                       ('productVersion', '--product-version', 'string', False)]:
        row = params.get(name, {})
        if (row.get('agent_flag') != flag or row.get('type') != kind
                or row.get('required') is not required):
            raise ValueError('征品检测参数契约变化，未执行')


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'): self.hidden += 1
        elif tag in ('br', 'p', 'div'): self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'): self.hidden = max(0, self.hidden - 1)
        elif tag in ('p', 'div'): self.parts.append(' ')

    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)


def _text(value):
    parser = _Text()
    parser.feed(value if isinstance(value, str) else '')
    return ' '.join(''.join(parser.parts).split())[:2000]


def _response(value):
    meta, data = value.get('meta') or {}, value.get('data') or {}
    if (value.get('success') is not True or value.get('truncated') is True
            or not isinstance(data, dict) or data.get('success') is not True or data.get('rc') != 'SUCCESS'
            or meta.get('mode') != 'live' or meta.get('mutating') is not False or meta.get('path') != COMMAND):
        raise ValueError('平台未返回有效的实时只读征品检测结果')
    dto = (data.get('value') or {}).get('detectionResultDTO') or {}
    rows = dto.get('detectionItemDTOList')
    if (dto.get('isChecked') is not True or type(dto.get('meet')) is not bool
            or not isinstance(rows, list) or not rows):
        raise ValueError('平台检测未完成或结果字段不完整')
    items = []
    for row in rows:
        if not isinstance(row, dict) or type(row.get('meet')) is not bool:
            raise ValueError('平台检测项未提供明确布尔结果')
        values = row.get('itemValue') or []
        if not isinstance(values, list) or any(not isinstance(x, str) for x in values):
            raise ValueError('平台检测项内容格式变化')
        name, description = _text(row.get('itemName')), _text(row.get('description'))
        plain = [_text(x) for x in values]
        item = {'itemCode': _text(row.get('itemCode')), 'itemName': name,
                'type': _text(row.get('type')), 'meet': row['meet'],
                'itemValue': plain, 'description': description,
                'reason': '' if row['meet'] else description or ('；'.join([name, *plain]))}
        score = (row.get('extend') or {}).get('score')
        if type(score) in (int, float) and math.isfinite(score): item['score'] = score
        items.append(item)
    if dto['meet'] != all(row['meet'] for row in items):
        raise ValueError('平台总结果与逐项检测结果不一致')
    return {'status': 'PASSED' if dto['meet'] else 'FAILED', 'meet': dto['meet'], 'items': items}


def _read(path):
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict): raise ValueError('检测证据须为JSON对象')
    return value


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(path, expected):
    if str(_read(path).get('CURRENT_SELF_ALIID') or '') != expected:
        raise ValueError('检测证据店铺身份不匹配')


def collect(product, root, bridge=None, run=None, require_identity=None):
    """Collect one explicit draft check; no database write, enrollment or publication."""
    import bridge_catalog
    import weekly_update
    scope = target(product)
    root = Path(root).resolve()
    if os.name == 'nt' and root.drive.upper() != 'D:':
        raise ValueError('检测证据仅允许保存至D盘')
    root.mkdir(parents=True, exist_ok=True)
    temporary, config = root / 'tmp', root / 'workctl-config'
    temporary.mkdir(exist_ok=True); config.mkdir(exist_ok=True)
    env = dict(os.environ, WORKCTL_CONFIG_DIR=str(config), TMP=str(temporary), TEMP=str(temporary),
               PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    bridge = Path(bridge or bridge_catalog.current_bridge())
    run, require_identity = run or weekly_update.run, require_identity or weekly_update.require_identity
    files = {key: root / name for key, name in [('request', 'request.json'), ('schema', 'schema.json'),
             ('response', 'response.json'), ('identityBefore', 'identity-before.json'),
             ('identityAfter', 'identity-after.json')]}
    checked = datetime.now(timezone.utc).isoformat()
    binding = {k: v for k, v in scope.items() if k != 'expected_account'}
    request = dict(binding, productVersion='draft', checkedAt=checked)
    files['request'].write_text(json.dumps(request, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    require_identity(bridge, files['identityBefore'], scope['expected_account'], env=env)
    _identity(files['identityBefore'], scope['expected_account'])
    try:
        schema = json.loads(run([bridge / 'workctl.cmd', 'schema', COMMAND, '--format', 'json'],
                                cwd=root, timeout=45, env=env))
        _schema(schema)
        files['schema'].write_text(json.dumps(schema, ensure_ascii=False, sort_keys=True), encoding='utf-8')
        files['response'].unlink(missing_ok=True)
        run([bridge / 'workctl.cmd', 'icbu', 'recruitment-topic', 'product-topic-detect',
             '--prod-id', scope['draft_id'], '--topic-id', scope['topic_id'], '--product-version', 'draft',
             '--format', 'json', '--compact-output', 'off', '--output', str(files['response'])],
            cwd=root, timeout=120, env=env)
        result = _response(_read(files['response']))
    finally:
        require_identity(bridge, files['identityAfter'], scope['expected_account'], env=env)
        _identity(files['identityAfter'], scope['expected_account'])
    authority = {'kind': 'workctl-tool', 'method': 'TOOLS/CALL', 'command': COMMAND, 'read_only': True,
                 'files': {key: {'path': str(path), 'sha256': _hash(path)} for key, path in files.items()}}
    return dict(binding, checkedAt=checked, **result, authority=authority)


def current(product):
    """Reparse saved native evidence; changed scope/files and checks older than 24h are stale."""
    saved = product.get('platformDetection')
    if not saved:
        return {'status': 'NOT_RUN', 'message': '尚未执行平台征品检测'}
    try:
        scope = target(product)
        binding = {k: v for k, v in scope.items() if k != 'expected_account'}
        if any(saved.get(k) != v for k, v in binding.items()): raise ValueError('检测目标已变化')
        checked = datetime.fromisoformat(saved['checkedAt'])
        age = datetime.now(timezone.utc) - checked
        if checked.tzinfo is None or not timedelta(0) <= age <= MAX_AGE:
            raise ValueError('检测超过24小时或时间无效')
        authority = saved.get('authority') or {}
        if (authority.get('kind') != 'workctl-tool' or authority.get('method') != 'TOOLS/CALL'
                or authority.get('command') != COMMAND or authority.get('read_only') is not True):
            raise ValueError('检测来源无效')
        records = authority['files']
        files = {}
        for key in ('request', 'schema', 'response', 'identityBefore', 'identityAfter'):
            row = records[key]; path = Path(row['path'])
            if (not path.is_absolute() or path.is_symlink() or path.resolve() != path.absolute()
                    or os.name == 'nt' and path.drive.upper() != 'D:' or _hash(path) != row['sha256']):
                raise ValueError('检测证据已改变')
            files[key] = path
        if len({p.parent for p in files.values()}) != 1: raise ValueError('检测证据目录不一致')
        expected_request = dict(binding, productVersion='draft', checkedAt=saved['checkedAt'])
        if _read(files['request']) != expected_request: raise ValueError('检测请求与当前产品不一致')
        _schema(_read(files['schema']))
        for key in ('identityBefore', 'identityAfter'): _identity(files[key], scope['expected_account'])
        parsed = _response(_read(files['response']))
        if any(saved.get(k) != v for k, v in parsed.items()): raise ValueError('检测摘要与原生证据不一致')
        return dict(binding, checkedAt=saved['checkedAt'], **parsed, authority=authority)
    except (ValueError, KeyError, TypeError, OSError, AttributeError):
        return {'status': 'STALE', 'message': '检测已过期或目标/证据变化，请重新执行平台检测'}
