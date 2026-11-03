"""Index the authorized report share; never execute files or write to the share."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import threading

ROOT = Path(__file__).resolve().parent
STATE = ROOT / '.state'
CACHE = STATE / 'shared-cache'
INDEX = STATE / 'shared-index.json'
SHARE = Path(os.environ.get('WORKBENCH_SHARED_ROOT') or str(STATE / 'shared-source'))
SHANGHAI = timezone(timedelta(hours=8))
SCAN_LOCK = threading.Lock()
MAX_FILES = 5000
MAX_BYTES = 30 * 1024 * 1024
ASSET_EXTS = {'.html', '.htm', '.css', '.js', '.json', '.png', '.jpg', '.jpeg', '.svg', '.webp', '.gif', '.ico', '.woff', '.woff2', '.xlsx'}
SKIP_DIRS = {'bin', 'node_modules', '.git', 'raw', 'database', 'logs', 'inquiry', 'resolvedId', '__pycache__'}
SENSITIVE = re.compile(r'(^\.|token|cookie|password|secret|gateway|credential|account_identity|connected-accounts)', re.I)
METRICS = ('se_imps', 'se_clk', 'total_imps', 'fb_cnt', 'fb_uv', 'fb_tm_uv', 'suc_ord_cnt')


def now():
    return datetime.now(SHANGHAI).isoformat()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def read_index():
    try:
        return json.loads(INDEX.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'version': 1, 'stores': [], 'lastSuccess': None, 'lastAttempt': None, 'status': 'NOT_SCANNED', 'records': []}


def safe_name(value):
    return re.sub(r'[^a-z0-9]', '', str(value).lower().replace('店铺', ''))


def store_id(name):
    return safe_name(name) or 'store-' + hashlib.sha256(name.encode()).hexdigest()[:12]


def iso_date(value):
    value = str(value or '').strip()
    m = re.search(r'(?<!\d)(20\d{2})[-/.年]?(\d{2})[-/.月]?(\d{2})(?!\d)', value)
    if not m:
        return None
    try:
        return date(*map(int, m.groups())).isoformat()
    except ValueError:
        return None


def date_range(text):
    dates = [iso_date(m.group()) for m in re.finditer(r'20\d{2}[-/.年]?\d{2}[-/.月]?\d{2}', text)]
    dates = [d for d in dates if d]
    return (dates[0], dates[1]) if len(dates) >= 2 and dates[0] <= dates[1] else (None, None)


def data_object(text):
    clean = text.lstrip('\ufeff \n\r\t')
    if clean.startswith('{'):
        try:
            data = json.loads(clean)
            return data if isinstance(data, dict) and ('meta' in data or 'weeks' in data or 'months' in data) else None
        except ValueError:
            return None
    # Parse JSON only. Never evaluate JavaScript from a shared file.
    for m in re.finditer(r'(?:window\.)?(?:V4_DATA|DASHBOARD_DATA)\s*=\s*', text):
        try:
            data, _ = json.JSONDecoder().raw_decode(text[m.end():])
            if isinstance(data, dict):
                return data
        except ValueError:
            continue
    return None


def period_rows(data):
    rows = []
    for kind, collection, start_key, end_key in [('week', 'weeks', 'week_start', 'week_end'), ('month', 'months', 'month_start', 'month_end')]:
        for row in data.get(collection, []) if isinstance(data.get(collection), list) else []:
            if not isinstance(row, dict):
                continue
            start, end = iso_date(row.get(start_key)), iso_date(row.get(end_key))
            if not start or not end or start > end:
                continue
            values = {key: row[key] for key in METRICS if type(row.get(key)) in (int, float) and math.isfinite(row[key])}
            if values:
                rows.append({'kind': kind, 'start': start, 'end': end, 'values': values})
    return rows


class PageInfo(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets, self.texts, self.scripts = set(), [], []
        self.in_script = False
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'img', 'link'):
            value = attrs.get('src') if tag != 'link' else attrs.get('href')
            if value:
                self.assets.add(value)
        if tag == 'script':
            self.in_script = True
    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_script = False
    def handle_data(self, value):
        (self.scripts if self.in_script else self.texts).append(value)


def walk_store(folder):
    files, issues = [], []
    def failed(error):
        raise error
    for base, dirs, names in os.walk(folder, followlinks=False, onerror=failed):
        if not Path(base).resolve().is_relative_to(folder.resolve()):
            dirs[:] = []
            issues.append('发现跨目录链接，已跳过')
            continue
        relative = Path(base).relative_to(folder)
        dirs[:] = [n for n in dirs if n not in SKIP_DIRS and not SENSITIVE.search(n)
                   and not (Path(base) / n).is_symlink() and len(relative.parts) < 5]
        for name in sorted(names):
            p = Path(base) / name
            if SENSITIVE.search(name) or p.is_symlink():
                continue
            if len(files) >= MAX_FILES:
                issues.append('文件数超出扫描上限，未宣称完整覆盖')
                return files, issues
            files.append(p)
    return files, issues


def local_asset(value, folder):
    value = value.split('?', 1)[0].split('#', 1)[0]
    if not value or re.match(r'^(?:[a-z]+:|//|/)', value, re.I) or '\\' in value:
        return None
    parts = PurePosixPath(value).parts
    if '..' in parts or any(SENSITIVE.search(part) or part in SKIP_DIRS for part in parts):
        return None
    p = folder.joinpath(*parts)
    try:
        if p.resolve().is_relative_to(folder.resolve()) and not p.is_symlink() and p.suffix.lower() in ASSET_EXTS:
            return p
    except OSError:
        pass
    return None


def render_data_preview(label, rows):
    body = ''.join('<tr><td>%s</td><td>%s ~ %s</td><td>%s</td><td>%s</td><td>%s</td></tr>' %
                   ('周' if r['kind'] == 'week' else '月', r['start'], r['end'],
                    r['values'].get('se_imps', '—'), r['values'].get('se_clk', '—'), r['values'].get('fb_cnt', '—')) for r in rows)
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<style>body{font:14px Microsoft YaHei,sans-serif;color:#355444;padding:24px}table{border-collapse:collapse;width:100%}td,th{padding:15px;border:1px solid #e0e8db;text-align:left}p{color:#8a9b7d;line-height:1.9}</style>'
            '</head><body><h2>' + escape(label) + ' · 数据文件整合预览</h2><p>来自结构化面板数据；缺失值显示“—”。周和月分别列出，不相加。</p>'
            '<table><tr><th>口径</th><th>统计期间</th><th>搜索曝光 se_imps</th><th>搜索点击 se_clk</th><th>反馈量 fb_cnt（源口径）</th></tr>' + body + '</table></body></html>')


def inspect_candidate(path, folder, label, known_stores):
    if path.stat().st_size > MAX_BYTES:
        return None, '文件过大，待人工确认'
    text = path.read_text(encoding='utf-8-sig', errors='replace')
    is_html = path.suffix.lower() in ('.html', '.htm')
    info = PageInfo()
    if is_html:
        info.feed(text)
    data = data_object(text)
    data_source = path
    if is_html and data is None:
        companion = path.parent / 'dashboard_data.js'
        if companion.is_file() and companion.stat().st_size <= MAX_BYTES:
            data = data_object(companion.read_text(encoding='utf-8-sig', errors='replace'))
            if data:
                data_source = companion
    kind = 'inquiry' if re.search(r'询盘|背调|inquiry|客户分层|客户台账', path.name, re.I) else 'data'
    if not data and not is_html:
        return None, '非已识别的面板数据结构，保留文件待适配'
    if is_html and not data and not re.search(r'面板|看板|驾驶舱|询盘|背调|dashboard|inquiry|曝光|客户分级|客户分层|客户台账', path.name + ' '.join(info.texts[:300]), re.I):
        return None, '无法确认是面板或询盘报告，待复核'
    meta = data.get('meta', {}) if isinstance(data, dict) else {}
    if not isinstance(meta, dict):
        meta = {}
    data_name = safe_name(meta.get('store_name', ''))
    if data_name and data_name in known_stores and data_name != store_id(label):
        return None, '文件内店名与所在店铺目录不一致，已隔离'
    rows = period_rows(data) if data else []
    start, end = iso_date(meta.get('week_start')), iso_date(meta.get('week_end'))
    basis = '面板元数据' if start and end else '未知'
    if not start or not end:
        start, end = date_range(path.stem)
        basis = '文件名日期范围' if start and end else '未知'
    if is_html and (not start or not end):
        text_header = ' '.join(info.texts)[:20000]
        window = re.search(r'(?:统计|数据|分析|日期|窗口|范围|周期).{0,30}20\d{2}[-/.]\d{2}[-/.]\d{2}.{0,12}20\d{2}[-/.]\d{2}[-/.]\d{2}', text_header)
        if window:
            start, end = date_range(window.group())
            basis = '报告内标注窗口' if start and end else '未知'
    if (not start or not end) and rows:
        latest = max(rows, key=lambda r: r['end'])
        start, end, basis = latest['start'], latest['end'], '结构化统计期间'
    period_ends = [r['end'] for r in rows]
    if end:
        period_ends.append(end)
    stat = path.stat()
    assets = {}
    missing = []
    if is_html:
        values = set(info.assets)
        if re.search(r'客户分层|客户台账',path.name) and path.with_suffix('.xlsx').is_file():
            values.add(path.with_suffix('.xlsx').name)
        # Existing exporter loads app.js dynamically. Include only its fixed public companions.
        values.update(n for n in ('app.js', 'styles.css', 'chart.umd.min.js', 'dashboard_data.js') if (path.parent / n).is_file())
        for script in info.scripts:
            values.update(re.findall(r'\.src\s*=\s*[\'"]([^\'"]+)[\'"]', script))
        pending = list(values)
        for _ in range(256):
            if not pending:
                break
            value = pending.pop()
            asset = local_asset(value, path.parent)
            if asset is None:
                if value and not re.match(r'^(?:[a-z]+:|//|#)', value, re.I):
                    missing.append(value[:100])
                continue
            rel = asset.relative_to(path.parent).as_posix()
            if rel in assets:
                continue
            if not asset.is_file() or asset.stat().st_size > MAX_BYTES:
                missing.append(rel)
                continue
            assets[rel] = asset
            if asset.suffix.lower() == '.css':
                css = asset.read_text(encoding='utf-8', errors='replace')
                for url in re.findall(r'url\([\'"]?([^\)\'\"]+)', css):
                    pending.append((PurePosixPath(rel).parent / url).as_posix())
        if pending:
            missing.append('依赖文件数超过上限')
    digest = hashlib.sha256()
    digest.update(text.encode('utf-8'))
    for rel, p in sorted(assets.items()):
        digest.update(rel.encode('utf-8')); digest.update(p.read_bytes())
    if data and not is_html:
        digest.update(json.dumps(data, ensure_ascii=False, sort_keys=True).encode('utf-8'))
    identity = hashlib.sha256((store_id(label) + kind + digest.hexdigest()).encode()).hexdigest()[:24]
    generated = str(meta.get('generated_at') or '')
    try:
        version_order = datetime.fromisoformat(generated).replace(tzinfo=SHANGHAI).timestamp()
    except ValueError:
        version_order = stat.st_mtime
    candidate = {'id': identity, 'store': store_id(label), 'kind': kind,
                 'fileName': path.name, 'sourceRelative': path.relative_to(SHARE).as_posix() if path.is_relative_to(SHARE) else path.relative_to(folder).as_posix(),
                 'start': start, 'end': end, 'periodEnd': max(period_ends, default=None), 'periodBasis': basis,
                 'generatedAt': generated or None, 'modified': datetime.fromtimestamp(stat.st_mtime, SHANGHAI).isoformat(),
                 'versionTime': generated or datetime.fromtimestamp(stat.st_mtime, SHANGHAI).isoformat(),
                 'versionOrder': version_order,
                 'complete': not missing, 'missingAssets': missing[:10],
                 'rows': rows, 'sourceData': data_source.relative_to(folder).as_posix(),
                 'files': [], 'duplicates': [], 'declaredStore': str(meta.get('store_name') or '')}
    candidate['reportType']='customer_ledger' if re.search(r'客户分层|客户台账',path.name) else kind
    candidate['downloads']=[{'name':rel,'url':f'/shared/{identity}/{rel}'} for rel in assets if Path(rel).suffix.lower()=='.xlsx']
    destination = CACHE / identity
    destination.mkdir(parents=True, exist_ok=True)
    if is_html:
        (destination / 'index.html').write_text(text, encoding='utf-8')
        for rel, source in assets.items():
            out = destination / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, out)
            candidate['files'].append(rel)
    else:
        (destination / 'index.html').write_text(render_data_preview(label, rows), encoding='utf-8')
    candidate['files'] = sorted(set(candidate['files'] + ['index.html']))
    return candidate, None


def consolidate(records):
    groups = {}
    for record in sorted(records, key=lambda r: (r.get('versionOrder', 0), r['sourceRelative'])):
        if record['kind'] != 'data' or not record['complete']:
            continue
        for row in record['rows']:
            key = (record['store'], row['kind'], row['start'], row['end'])
            current = {**row, 'store': record['store'], 'snapshot': record['id'],
                       'fileName': record['fileName'], 'versions': 1, 'conflict': False}
            if key in groups:
                old = groups[key]
                current['versions'] = old['versions'] + 1
                current['conflict'] = old['conflict'] or old['values'] != row['values']
            groups[key] = current
    return sorted(groups.values(), key=lambda r: (r['store'], r['kind'], r['end']), reverse=True)


def scan():
    STATE.mkdir(parents=True, exist_ok=True)
    lock = STATE / 'shared-scan.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return {'status': 'BUSY', 'message': '已有扫描正在进行，未重复启动'}
    os.close(fd)
    previous = read_index()
    try:
        previous['lastAttempt'], previous['status'] = now(), 'SCANNING'
        atomic_json(INDEX, previous)
        if not SHARE.is_dir():
            raise OSError('share unavailable')
        folders = sorted([p for p in SHARE.iterdir() if p.is_dir() and not p.is_symlink() and not SENSITIVE.search(p.name)], key=lambda p: p.name.lower())
        known = {store_id(p.name) for p in folders}
        records, stores, issues, duplicates = [], [], [], 0
        for folder in folders:
            files, warnings = walk_store(folder)
            for warning in warnings:
                issues.append({'store': store_id(folder.name), 'file': folder.name, 'reason': warning})
            by_hash, consumed = {}, set()
            candidates = [p for p in files if p.suffix.lower() in ('.html', '.htm')]
            candidates += [p for p in files if p.suffix.lower() in ('.json', '.js') and (p.name == 'dashboard_data.js' or p.suffix.lower() == '.json')]
            for p in candidates:
                if p in consumed:
                    continue
                try:
                    record, reason = inspect_candidate(p, folder, folder.name, known)
                    if reason:
                        # Ordinary JS companions are not independent reports.
                        if p.suffix.lower() != '.js':
                            issues.append({'store': store_id(folder.name), 'file': p.relative_to(folder).as_posix(), 'reason': reason})
                        continue
                    if p.suffix.lower() in ('.html', '.htm') and record['sourceData'] != p.relative_to(folder).as_posix():
                        consumed.add(folder / record['sourceData'])
                    if record['id'] in by_hash:
                        by_hash[record['id']]['duplicates'].append(record['sourceRelative'])
                        duplicates += 1
                    else:
                        by_hash[record['id']] = record
                except (OSError, ValueError, TypeError, KeyError, RecursionError):
                    issues.append({'store': store_id(folder.name), 'file': p.relative_to(folder).as_posix(), 'reason': '文件读取或格式校验失败，未导入'})
            for p in files:
                if p.suffix.lower() in ('.xlsx', '.xls', '.csv', '.zip', '.pdf'):
                    if p.suffix.lower()=='.xlsx' and p.with_suffix('.html').is_file() and re.search(r'客户分层|客户台账',p.name):
                        continue
                    issues.append({'store': store_id(folder.name), 'file': p.relative_to(folder).as_posix(), 'reason': '当前先接 HTML 面板 / 报告及配套面板 JSON；此格式待样例适配，ZIP 请先解压到本店目录'})
            records.extend(by_hash.values())
            stores.append({'id': store_id(folder.name), 'label': folder.name, 'files': len(files), 'snapshots': len(by_hash)})
        # If a previous report vanished from a successful scan, it no longer appears as current.
        result = {'version': 1, 'status': 'SUCCESS', 'source': str(SHARE), 'lastAttempt': previous['lastAttempt'],
                  'lastSuccess': now(), 'stores': stores, 'records': records,
                  'periods': consolidate(records), 'issues': issues, 'duplicateCount': duplicates,
                  'message': f'已扫描 {len(stores)} 个店铺目录，识别 {len(records)} 个快照'}
        atomic_json(INDEX, result)
        return {'status': 'SUCCESS', 'message': result['message']}
    except OSError:
        previous.update(status='FAILED', message='共享目录不可访问，保留上次成功索引；请检查网络与共享权限')
        atomic_json(INDEX, previous)
        return {'status': 'FAILED', 'message': previous['message']}
    finally:
        lock.unlink(missing_ok=True)


def public_index():
    value = read_index()
    try:
        preference=json.loads((STATE/'inquiry-display.json').read_text(encoding='utf-8'))
        inquiry_defaults={k:preference[k] for k in ('defaultStore','preferredType') if k in preference}
    except (OSError,ValueError,TypeError):
        inquiry_defaults={}
    records = []
    for record in value.get('records', []):
        records.append({k: v for k, v in record.items() if k not in ('files', 'rows', 'sourceData')})
        records[-1]['url'] = f'/shared/{record["id"]}/index.html'
    try:
        schedule = json.loads((STATE / 'shared-schedule.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        schedule = {'enabled': False}
    try:
        weekly = json.loads((STATE / 'weekly' / 'status.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        weekly = {'status': 'NOT_RUN', 'message': '尚未执行首次自动采集'}
    try:
        progress = json.loads((STATE / 'weekly' / 'progress.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        progress = None
    return {**{k: v for k, v in value.items() if k != 'records'}, 'records': records,
            'schedule': schedule, 'weeklyUpdate': weekly, 'weeklyProgress': progress,'inquiryDefaults':inquiry_defaults}


def resolve_cached(snapshot_id, relative):
    if not re.fullmatch(r'[a-f0-9]{24}', snapshot_id):
        return None
    if '\\' in relative or any(p in ('.', '..') for p in relative.split('/')):
        return None
    record = next((r for r in read_index().get('records', []) if r['id'] == snapshot_id), None)
    if record is None or relative not in record.get('files', []):
        return None
    base = CACHE / snapshot_id
    p = base / relative
    if not p.is_symlink() and p.resolve().is_relative_to(base.resolve()):
        return p
    return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scan', action='store_true', help='Scan authorized share and update local index')
    args = parser.parse_args()
    if args.scan:
        result = scan()
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result['status'] == 'SUCCESS' else 1)
