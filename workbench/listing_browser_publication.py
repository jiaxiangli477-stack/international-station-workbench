"""Read-only product-manager observations in the original dedicated browser."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import parse_qs, urlsplit
import uuid

MANAGER = 'https://i.alibaba.com/prod/product_manage'
POST = 'https://post.alibaba.com/product/publish.htm'
SCRIPT = Path(__file__).with_suffix('.cjs')


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tab(value):
    value = re.sub(r'\s', '', str(value))
    for label, kind in [('全部', 'all'), ('草稿', 'draft')]:
        if re.fullmatch(label + r'(?:[（(]\d+[)）])?', value): return kind
    return ''


def _parse(snapshot, product_id):
    unknown = {'status': 'unknown', 'status_text': '未知', 'mapping_verified': False}
    if not isinstance(snapshot, dict) or not _tab(snapshot.get('tab')) or not isinstance(snapshot.get('rows'), list):
        return dict(unknown, reason='invalid_schema')
    rows = [row for row in snapshot['rows'] if isinstance(row, dict) and isinstance(row.get('id_text'), str)
            and re.fullmatch(r'ID:\s*' + re.escape(product_id), row['id_text'].strip())]
    if not rows: return dict(unknown, reason='not_found')
    if len(rows) != 1: return dict(unknown, reason='multiple_rows')
    row = rows[0]
    if not isinstance(row.get('status_text'), str) or row.get('edit_conflict'):
        return dict(unknown, reason='invalid_row')
    lines = [line.strip() for line in row['status_text'].splitlines() if line.strip()]
    edit = None
    if row.get('edit_url'):
        try:
            url = urlsplit(row['edit_url'])
            edit = parse_qs(url.query)
            if (url.scheme != 'https' or url.netloc != 'post.alibaba.com' or url.path != '/product/publish.htm'
                    or edit.get('itemId') != [product_id]): return dict(unknown, reason='foreign_editor')
        except (ValueError, TypeError): return dict(unknown, reason='invalid_editor')
    status, label = 'unknown', '未知'
    if _tab(snapshot['tab']) == 'draft' and not lines and edit and edit.get('pubAction') == ['draft']:
        status, label = 'draft', '草稿'
    elif _tab(snapshot['tab']) == 'all' and lines and (edit is None or edit.get('pubAction') != ['draft']):
        if set(lines) <= {'审核通过', '已上架'} and '已上架' in lines: status, label = 'published', '已上架'
        if set(lines) <= {'审核通过', '已下架'} and '已下架' in lines: status, label = 'unpublished', '已下架'
    return {'status': status, 'status_text': label, 'mapping_verified': status != 'unknown',
            'reason': '' if status != 'unknown' else 'unmapped_or_conflicting_status'}


def verify_observation(observation, product_id, draft_id, expected_account):
    """Reparse minimal DOM and hash-bound target/owner records; distrust claimed status."""
    source = observation.get('source') or {}
    if (source.get('kind') != 'product_manager_row' or source.get('method') != 'GET'
            or source.get('url') != MANAGER or source.get('collector_sha256') != _hash(SCRIPT)
            or source.get('python_sha256') != _hash(__file__)
            or any(not re.fullmatch(r'[0-9a-f]{64}', str(source.get(key, ''))) for key in (
                'request_sha256', 'dom_sha256', 'identity_before_sha256', 'identity_after_sha256'))):
        raise ValueError('Unverified browser publication source')
    raw_root = Path(source.get('evidence_root', ''))
    if not raw_root.is_absolute() or raw_root.is_symlink(): raise ValueError('Unverified evidence directory')
    root = raw_root.resolve()
    if os.name == 'nt' and root.drive.upper() != 'D:': raise ValueError('Evidence must stay on D drive')
    def read(name, digest=None):
        path = root/name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
            raise ValueError('Invalid publication evidence file')
        if digest is not None and _hash(path) != digest: raise ValueError('Publication evidence hash changed')
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict): raise ValueError('Publication evidence object required')
        return value
    if read('observation.json') != observation: raise ValueError('Observation differs from backend file')
    request = read('request.json', source.get('request_sha256'))
    target = request.get('target') or {}
    if (str(target.get('product_id')) != str(product_id) or str(target.get('draft_id')) != str(draft_id)
            or str(target.get('expected_account')) != str(expected_account) or not target.get('store')
            or not request.get('run_id') or request.get('collector_sha256') != source['collector_sha256']
            or request.get('python_sha256') != source['python_sha256']):
        raise ValueError('Publication target differs from bound request')
    category = target.get('category_id')
    if 'category_id' in target and not re.fullmatch(r'[1-9][0-9]{0,24}', str(category)):
        raise ValueError('Invalid owner probe category')
    # This route identifies the current owner, not the target product's category.
    owner_url = POST + ('?catId=' + category if category else '?itemId=' + str(draft_id) + '&pubAction=draft')
    timestamps = []
    for name, key in [('identity-before.json', 'identity_before_sha256'), ('identity-after.json', 'identity_after_sha256')]:
        identity = read(name, source.get(key))
        if (identity.get('verified') is not True or str(identity.get('account_id')) != str(expected_account)
                or identity.get('nested_account_id') not in ('', str(expected_account))
                or identity.get('source_url') != owner_url):
            raise ValueError('Publication browser owner changed')
        timestamps.append(datetime.fromisoformat(identity['observed_at'].replace('Z', '+00:00')))
    observed = datetime.fromisoformat(observation['observed_at'].replace('Z', '+00:00'))
    age = (datetime.now(timezone.utc) - observed).total_seconds()
    if not timestamps[0] <= timestamps[1] <= observed or not -30 <= age <= 300:
        raise ValueError('Publication evidence time is not current')
    if observation.get('identity') != {'verified': True, 'account_id': str(expected_account)}:
        raise ValueError('Publication owner differs from evidence')
    dom = read('manager-dom.json', source.get('dom_sha256'))
    queries = dom.get('queries')
    if dom.get('source_url') != MANAGER or not isinstance(queries, list) or len(queries) not in (1, 2):
        raise ValueError('Invalid product-manager query evidence')
    parsed = None
    for index, query in enumerate(queries):
        response = query.get('response') or {}
        if (_tab(query.get('tab')) != ('all' if index == 0 else 'draft')
                or query.get('queried_id') != str(product_id)
                or response.get('host') != 'hz-productposting.alibaba.com'
                or response.get('path') != '/product/managementproducts/asyQueryProductsList.do'
                or response.get('method') != 'GET' or response.get('request_product_id') != str(product_id)
                or response.get('request_status') != ('all' if index == 0 else 'sketch')
                or response.get('repository_type') != 'all' or response.get('show_type') != 'onlyMarket'
                or type(response.get('status')) is not int or not 200 <= response['status'] < 300
                or index and parsed.get('reason') != 'not_found'):
            raise ValueError('Product-manager query context differs')
        parsed = _parse(query, str(product_id))
    expected_row = {'item_id': str(product_id), 'draft_id': str(draft_id),
                    'status_field': '商品状态', 'status_text': parsed['status_text']}
    if observation.get('row') != expected_row: raise ValueError('Claimed status differs from observed DOM')
    return dict(parsed, **expected_row)


def collect(target, root, run=None):
    """Connect to existing CDP only; never launch/login, fill or save a product."""
    if (not isinstance(target, dict) or not re.fullmatch(r'[1-9][0-9]{0,24}', str(target.get('product_id', '')))
            or not re.fullmatch(r'[1-9][0-9]{0,24}', str(target.get('draft_id', '')))
            or not target.get('expected_account') or not target.get('store')):
        raise ValueError('Explicit product/draft/account/store required')
    if 'category_id' in target and not re.fullmatch(r'[1-9][0-9]{0,24}', str(target['category_id'])):
        raise ValueError('Owner probe category must be a positive integer string')
    import listing_adapter
    executable = shutil.which('node')
    if not executable: raise ValueError('Existing Node runtime required')
    root = Path(root).resolve()
    if os.name == 'nt' and root.drive.upper() != 'D:': raise ValueError('Evidence must stay on D drive')
    root.mkdir(parents=True, exist_ok=True)
    for name in ('observation.json', 'identity-before.json', 'identity-after.json', 'manager-dom.json', 'error.json'):
        (root/name).unlink(missing_ok=True)
    request = {'target': {key: str(target[key]) for key in ('store', 'product_id', 'draft_id', 'expected_account')},
               'run_id': uuid.uuid4().hex, 'collector_sha256': _hash(SCRIPT), 'python_sha256': _hash(__file__)}
    if 'category_id' in target: request['target']['category_id'] = str(target['category_id'])
    request_file = root/'request.json'
    request_file.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
    stage = 'node_process'
    try:
        done = (run or subprocess.run)([executable, str(SCRIPT), str(request_file)], cwd=str(root),
            env=listing_adapter.environment(), capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=240,
            stdin=subprocess.DEVNULL, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if done.returncode != 0: raise ValueError('Browser publication observation failed')
        stage = 'evidence_verification'
        observation = json.loads((root/'observation.json').read_text(encoding='utf-8'))
        verify_observation(observation, target['product_id'], target['draft_id'], target['expected_account'])
        return observation
    except Exception as error:
        if not (root/'error.json').is_file():
            name = type(error).__name__
            if name not in ('ValueError', 'OSError', 'TimeoutExpired', 'JSONDecodeError'): name = 'Error'
            (root/'error.json').write_text(json.dumps({'stage': stage, 'error_name': name}), encoding='utf-8')
        # Browser/CLI exceptions can carry page/account data; keep failures private.
        raise ValueError('Read-only browser publication evidence was not verified') from None
