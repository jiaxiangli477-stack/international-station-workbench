"""Guarded weekly collector: existing bridge -> isolated reports -> shared scan."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import shared_scan as catalog

ROOT = Path(__file__).resolve().parent
STATE = ROOT / '.state' / 'weekly'
PACKAGE = Path(r'D:\work\alibaba-growth-os-share')
STORES = {
    'lifeworthcn': {'folder': 'Lifeworthcn', 'label': 'lifeworthcn店铺',
                   'expected_id': os.environ.get('WORKBENCH_STORE_LIFEWORTHCN_ID', ''), 'dashboard': Path(r'D:\work\boards\lifeworthcn')},
    'youhealth': {'folder': 'Youhealth', 'label': 'YH店铺',
                 'expected_id': os.environ.get('WORKBENCH_STORE_YOUHEALTH_ID', ''), 'dashboard': Path(r'D:\work\boards\YH')},
}


class SyncError(Exception):
    pass


def safe_failure(output):
    """Expose only known collector errors, never raw account or credential output."""
    messages = {
        '账号范围消息未完整核验，停止生成新报告': '跨销售账号的会话消息归属未核验，询盘报告未生成',
        '会话账号消息映射缺失，停止生成新报告': '会话缺少所属销售账号的消息证据，询盘报告未生成',
        '采集未完整成功，停止生成新报告': '会话或消息采集不完整，询盘报告未生成',
        '平台自然周起止日期尚未与页面选择器核对': '缺少平台日期选择器的自然周起止证据，经营面板未更新',
        '按T+2等待完整平台自然周出数': '按T+2等待平台自然周数据完整，经营面板未更新',
        '平台返回的是另一个自然周': '平台接口返回其他自然周，经营面板未更新；需核对页面所选期间',
    }
    return next((reason for marker,reason in messages.items() if marker in output),
                '调用失败，请核对连接或接口权限；原始输出未公开')


def run(command, cwd, timeout=60, env=None):
    child_env = dict(os.environ if env is None else env)
    import bridge_runtime
    try:
        child_env = bridge_runtime.child_environment(command[0], child_env)
    except ValueError as error:
        raise SyncError(str(error)) from None
    child_env['PYTHONIOENCODING'] = 'utf-8'
    # cmd.exe cannot reliably start with a non-ASCII working directory on some
    # Windows builds. The bridge commands receive absolute output paths, so run
    # their launcher from the containing drive root instead.
    effective_cwd = cwd
    if os.name == 'nt' and str(command[0]).lower().endswith(('.cmd', '.bat')):
        drive = Path(cwd).resolve().drive
        if drive:
            effective_cwd = drive + os.sep
    result = subprocess.run([str(x) for x in command], cwd=effective_cwd, env=child_env,
                            shell=os.name == 'nt' and str(command[0]).endswith('.cmd'),
                            stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=timeout,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode != 0:
        # Raw CLI errors may contain account or credential material; do not persist them.
        raise SyncError(safe_failure((result.stdout or '')+'\n'+(result.stderr or '')))
    return result.stdout


def bridge_identity(bridge, output, env=None):
    output.parent.mkdir(parents=True, exist_ok=True)
    run([bridge / 'workctl.cmd', 'workflow', 'chat-analysis', 'resolve-id',
         '--output-file', output, '--format', 'json'], cwd=output.parent, timeout=120, env=env)
    data = json.loads(output.read_text(encoding='utf-8-sig'))
    current = str(data.get('CURRENT_SELF_ALIID') or '')
    if not current.isdigit():
        raise SyncError('未取得有效的当前店铺身份')
    return current


def require_identity(bridge, output, expected, env=None):
    if bridge_identity(bridge, output, env=env) != str(expected):
        raise SyncError('当前 Accio 店铺与目标店铺不匹配；未切换账号、未发布新报告')


def prepare_bridge(destination):
    source = ROOT / '.state' / 'yh-check' / 'bridge'
    if source.resolve().parent != (ROOT / '.state' / 'yh-check').resolve():
        raise SyncError('当前 Accio 桥接模板路径无效')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    setup = source / 'setup_env.py'
    if not setup.is_file() or setup.resolve().parent != source.resolve():
        raise SyncError('当前 Accio 桥接脚本不可用')
    shutil.copy2(setup, destination / 'setup_env.py')
    source_bin, dest_bin = source / 'bin', destination / 'bin'
    dest_bin.mkdir(exist_ok=True)
    for name in ('workctl', 'workctl.cmd', 'accio-mcp-cli', 'accio-mcp-cli.cmd'):
        item = source_bin / name
        if not item.is_file() or item.resolve().parent != source_bin.resolve():
            raise SyncError('当前 Accio 命令桥接不可用')
        shutil.copy2(item, dest_bin / name)
    if any(p.name.lower().startswith('_token') for p in dest_bin.iterdir()):
        raise SyncError('桥接暂存区出现禁止写入的凭据文件')
    return dest_bin


def patch_inquiry_source(source):
    old = "start = time.strftime('%Y-%m-%d', time.localtime(time.time() - args.days * 86400))"
    if source.count(old) != 1:
        raise SyncError('询盘脚本版本变化，需重新核验日期窗口')
    source = source.replace('import time\n', 'import time\nimport datetime as calendar_dt\nfrom bridge_materialization import verified_summary, account_scoped_messages, save_account_messages\n', 1)
    nested_run_cwd = "errors='replace', shell=True, timeout=timeout, env=env(), cwd=HERE)"
    if source.count(nested_run_cwd) != 1:
        raise SyncError('询盘脚本命令运行目录变化，需重新核验桥接路径')
    source = source.replace(nested_run_cwd,
                            "errors='replace', shell=True, timeout=timeout, env=env(), cwd=os.path.splitdrive(HERE)[0] + os.sep)", 1)
    source = source.replace(old, "start = (calendar_dt.date.fromisoformat(end) - calendar_dt.timedelta(days=args.days - 1)).isoformat()", 1)
    message_block = """    msgs = {c.get('conversationId'): (c.get('messages') or [])
            for c in ((jload(msg_file) or {}).get('conversations') or [])}
"""
    if source.count(message_block) != 1:
        raise SyncError('询盘消息映射接口变化，停止自动适配')
    message_adapter = """    message_rows = (jload(msg_file) or {}).get('conversations') or []
    def normalize_timestamp(value):
        if isinstance(value, (int, float)) or isinstance(value, str) and value.isdigit():
            stamp = float(value)
            stamp = stamp / 1000 if stamp > 1e11 else stamp
            return calendar_dt.datetime.fromtimestamp(int(stamp), calendar_dt.timezone.utc).isoformat(timespec='seconds')
        return value if isinstance(value, str) and value else None
    def fetch_duplicate_messages(conversation):
        seller_id = str(conversation.get('sellerAliId') or '')
        buyer_id = str(conversation.get('contactAliId') or '')
        if not seller_id or not buyer_id:
            return None
        tz = calendar_dt.timezone(calendar_dt.timedelta(hours=8))
        start_ms = int(calendar_dt.datetime.fromisoformat(start).replace(tzinfo=tz).timestamp() * 1000)
        end_dt = (calendar_dt.datetime.fromisoformat(end) + calendar_dt.timedelta(days=1)).replace(tzinfo=tz)
        end_ms = int(end_dt.timestamp() * 1000) - 1
        rc_dup, out_dup = run(['workctl', 'icbu', 'tm', 'list-conversation-msg-time-range',
                               '--conversation-id', str(conversation.get('conversationId') or ''),
                               '--self-ali-id', seller_id, '--domain', 'icbu',
                               '--start-time', str(start_ms), '--end-time', str(end_ms), '--format', 'json'], timeout=600)
        result = jparse(out_dup)
        if rc_dup != 0 or not isinstance(result, dict) or result.get('success') is not True or result.get('hasMore') is not False:
            return None
        messages = []
        for item in result.get('messages') or []:
            sender_id = str(item.get('senderAliId') or '')
            role = 'seller' if sender_id == seller_id else 'buyer' if sender_id == buyer_id else ''
            if not role or item.get('timestamp') is None:
                return None
            # The bulk fetch contract stores whole seconds. Normalize the
            # recovery API to the same precision and a string type expected by
            # the downstream report Skill.
            timestamp = normalize_timestamp(item['timestamp'])
            if not timestamp:
                return None
            content = item.get('content') or ''
            messages.append({'time': timestamp, 'from': role,
                             'text': content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)})
        return messages
    try:
        account_msgs = account_scoped_messages(convs, message_rows, fetch_duplicate_messages)
        save_account_messages(os.path.join(WORK, 'account_messages.json'),
                              os.path.join(WORK, 'conversations_all.json'), msg_file, account_msgs)
    except Exception:
        print('账号范围消息未完整核验，停止生成新报告')
        return 5
"""
    source = source.replace(message_block, message_adapter, 1)
    lookup = "        ms = msgs.get(c.get('conversationId')) or []\n"
    if source.count(lookup) != 1:
        raise SyncError('询盘会话消息引用接口变化，停止自动适配')
    source = source.replace(lookup, "        key = (str(c.get('sellerAliId') or ''), str(c.get('conversationId') or ''))\n        if key not in account_msgs:\n            print('会话账号消息映射缺失，停止生成新报告')\n            return 5\n        ms = account_msgs[key]\n", 1)
    time_mapping = "'sendTime': m.get('time')"
    if source.count(time_mapping) != 1:
        raise SyncError('询盘时间字段契约变化，需重新核验报告兼容性')
    source = source.replace(time_mapping, "'sendTime': normalize_timestamp(m.get('time'))", 1)
    for marker, variable in [('    d = jparse(out)\n', 'd'), ('    d2 = jparse(out)\n', 'd2')]:
        if source.count(marker) != 1:
            raise SyncError('询盘脚本输出契约变化，停止自动适配')
        guard = (f"    if rc != 0 or not isinstance({variable}, dict) or {variable}.get('status') != 'success':\n"
                 "        print('采集未完整成功，停止生成新报告')\n        return 5\n")
        kind = 'conversations' if variable == 'd' else 'messages'
        filename = 'conversations_all.json' if variable == 'd' else 'messages_all.json'
        extra = ', expected_accounts=len(ids)' if variable == 'd' else ''
        normalize = f"    {variable} = verified_summary({variable}, os.path.join(WORK, '{filename}'), '{kind}', start, end{extra}) if rc == 0 else None\n"
        source = source.replace(marker, marker + normalize + guard, 1)
    return source


class RemovePriorCustomers(ast.NodeTransformer):
    def visit_Assign(self, node):
        if isinstance(node.value, ast.Dict):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if names & {'ANALYSIS', 'STRENGTH', 'COMPANIES'}:
                node.value = ast.Dict(keys=[], values=[])
            elif 'ASK' in names:
                pairs = [(k, v) for k, v in zip(node.value.keys, node.value.values)
                         if isinstance(k, ast.Constant) and k.value == '_default']
                if not pairs:
                    raise SyncError('缺少通用询问模板，停止自动适配')
                node.value = ast.Dict(keys=[p[0] for p in pairs], values=[p[1] for p in pairs])
        return node


def prepare_inquiry(destination):
    from inquiry_release import prepare
    return prepare(destination)


def prepare_dashboard(destination, cfg, windows=None):
    import hashlib
    from datetime import date
    source = cfg['dashboard']
    source_workspace = source / 'engine' / 'workspace'
    stores_path = source_workspace / 'stores.json'
    stores_bytes = stores_path.read_bytes()
    stores_config = json.loads(stores_bytes.decode('utf-8-sig'))
    active = stores_config.get('active')
    current = stores_config.get('stores', {}).get(active)
    if not isinstance(current, dict) or str(current.get('store_id')) != str(cfg['expected_id']):
        raise SyncError('源看板缺少匹配目标店铺的配置；不能重标其他店铺的日期证据')
    # Copy only date-picker evidence, never the private workspace or cached metrics.
    proof_path = source_workspace / 'raw' / 'platform_native_week_windows.json'
    requested = None if windows is None else {
        (w.get('start', w.get('week_start')), w.get('end', w.get('week_end'))) for w in windows}
    bindings = []
    proof = None
    if proof_path.is_file():
        proof_bytes = proof_path.read_bytes()
        proof = json.loads(proof_bytes.decode('utf-8-sig'))
        if not isinstance(proof, dict) or not isinstance(proof.get('windows'), list):
            raise SyncError('平台日期证据格式无效')
        for row in proof.get('windows', []):
            if not isinstance(row, dict):
                raise SyncError('平台日期证据窗口格式无效')
            if requested is not None and (row.get('start'), row.get('end')) not in requested:
                continue
            if row.get('source') != 'platform-date-picker' or row.get('confirmed') is not True or not row.get('evidence'):
                continue
            if not all(isinstance(row.get(key), str) for key in ('start', 'end', 'statDate')):
                raise SyncError('平台日期证据缺少有效起止或接口日期')
            if (date.fromisoformat(row['end']) - date.fromisoformat(row['start'])).days != 6:
                raise SyncError('平台日期证据不是连续7日')
            date.fromisoformat(row['statDate'])
            for item in (proof, row):
                for field in ('store', 'store_id', 'storeId', 'aliId'):
                    if field in item and str(item[field]) != str(cfg['expected_id']):
                        raise SyncError('平台日期证据店铺不匹配')
            allowed = ('start', 'end', 'statDate', 'source', 'confirmed', 'evidence', 'store', 'store_id', 'storeId', 'aliId')
            clean = {key: row[key] for key in allowed if key in row}
            if any((b['start'], b['end']) == (clean['start'], clean['end']) and b != clean for b in bindings):
                raise SyncError('同一平台周存在冲突的日期证据')
            if clean not in bindings:
                bindings.append(clean)
    if requested is not None and {(b['start'], b['end']) for b in bindings} != requested:
        raise SyncError('请求的平台自然周缺少页面选择器日期证明；不猜日期、不逐日汇总')
    destination.mkdir(parents=True, exist_ok=True)
    for name in ('make_dashboard.py', 'setup_env.py'):
        shutil.copy2(source / name, destination / name)
    shutil.copytree(source / 'engine', destination / 'engine',
                    ignore=shutil.ignore_patterns('workspace', 'bin', 'logs', '__pycache__', '.git'))
    workspace = destination / 'engine' / 'workspace'
    workspace.mkdir(parents=True, exist_ok=True)
    current.update(store_id=cfg['expected_id'], name=cfg['label'], full_name=cfg['label'])
    catalog.atomic_json(workspace / 'stores.json', stores_config)
    if bindings:
        store_fields = ('store', 'store_id', 'storeId', 'aliId')
        catalog.atomic_json(workspace / 'raw' / 'platform_native_week_windows.json', {
            'windows': bindings,
            'provenance': {'source': str(proof_path), 'sourceSha256': hashlib.sha256(proof_bytes).hexdigest(),
                           'sourceStoresSha256': hashlib.sha256(stores_bytes).hexdigest(),
                           'sourceStore': str(cfg['expected_id']),
                           # Legacy bindings carry no page-level store proof. Do not manufacture one.
                           'storeBinding': 'explicit' if all(any(k in b or k in proof for k in store_fields)
                                                           for b in bindings) else 'source_config_only'}})
    # Use the existing confirmed 4-week / 6-month settings, and pin this run's cutoff.
    settings = json.loads((source / 'settings.json').read_text(encoding='utf-8-sig'))
    settings['as_of'] = None
    catalog.atomic_json(destination / 'settings.json', settings)


def dashboard_requested_windows(cfg, as_of):
    """Use verified picker windows when available; otherwise keep the default windows fail-closed."""
    from calendar_periods import dashboard_windows
    source=cfg.get('dashboard')
    proof_path=(Path(source)/'engine'/'workspace'/'raw'/'platform_native_week_windows.json') if source else None
    if proof_path and proof_path.is_file():
        proof=json.loads(proof_path.read_text(encoding='utf-8-sig'))
        rows=proof.get('windows') if isinstance(proof,dict) else None
        confirmed=[row for row in rows or [] if isinstance(row,dict)
                   and row.get('source')=='platform-date-picker'
                   and row.get('confirmed') is True and row.get('evidence')]
        if confirmed:
            return [{'week_start':row.get('start'),'week_end':row.get('end')} for row in confirmed]
    return dashboard_windows(as_of)['weeks']


def publish_files(files, folder, name):
    if not folder.resolve().is_relative_to(catalog.SHARE.resolve()):
        raise SyncError('输出目录不在授权共享盘内')
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    if target.exists():
        raise SyncError('本次输出目录已存在，未覆盖已有报告')
    temp = folder / ('.upload-' + name)
    temp.mkdir()
    for source, relative in files:
        relative = Path(relative)
        if relative.is_absolute() or '..' in relative.parts:
            raise SyncError('无效输出文件名')
        out = temp / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, out)
    temp.rename(target)
    return target


def do_store(key, cfg, stage, bridge, as_of):
    expected = cfg['expected_id']
    identity_file = stage / 'identity.json'
    require_identity(bridge, identity_file, expected)
    verified_at = catalog.now()
    env = dict(os.environ)
    env['PATH'] = str(bridge) + os.pathsep + env.get('PATH', '')
    import bridge_runtime
    try:
        env = bridge_runtime.child_environment(bridge / 'workctl.cmd', env)
    except ValueError as error:
        raise SyncError(str(error)) from None
    published = {}
    failures = []
    selected_dashboard_periods = []
    from calendar_periods import window
    reporting_window=window('previous_week',today=as_of)
    start=datetime.fromisoformat(reporting_window['start']).date()
    end=datetime.fromisoformat(reporting_window['end']).date()
    for kind in ('inquiry', 'dashboard'):
        try:
            catalog.atomic_json(STATE / 'progress.json', {'store': key, 'stage': kind, 'status': 'RUNNING', 'started': catalog.now()})
            require_identity(bridge, identity_file, expected)
            if kind == 'inquiry':
                dest = stage / 'inquiry-engine'
                prepare_inquiry(dest)
                import inquiry_calendar
                inquiry_calendar.collect(dest,bridge,expected,reporting_window,env=env)
                require_identity(bridge, identity_file, expected)
                conversations = json.loads((dest / 'inquiry' / 'conversations.json').read_text(encoding='utf-8-sig'))
                if str(conversations.get('store', {}).get('aliId')) != expected:
                    raise SyncError('新询盘数据店铺身份未通过核验')
                import inquiry_release
                # Contacts were enriched within each guarded <=7-day calendar segment.
                require_identity(bridge,identity_file,expected)
                inquiry_release.run_analysis(dest,verify_public=True)
                report = max((dest / 'inquiry').glob('询盘客户背调分析_*.html'), default=None)
                if report is None or report.stat().st_size < 1000:
                    raise SyncError('未生成有效询盘报告')
                require_identity(bridge, identity_file, expected)
                filename = f'询盘分析_{start.isoformat()}_{end.isoformat()}.html'
                files=[(report,filename)]
                files.extend((p,'客户分层分析表_'+start.isoformat()+'_'+end.isoformat()+p.suffix) for p in (dest/'inquiry').glob('客户分层分析表_*') if p.suffix in ('.html','.xlsx'))
                published[kind] = str(publish_files(files, catalog.SHARE / cfg['folder'], stage.parent.name + '-inquiry'))
                # Automatic Tuesday reports feed the same task/follow-up records as manual runs.
                import task_store
                completed = task_store.record_completed('inquiry', 'weekly:'+key+':'+stage.parent.name,
                    {'store':key,'period':{'start':start.isoformat(),'end':end.isoformat()},'sourceMode':'scheduled',
                     'result':{'conversations':len(conversations.get('conversations',[])),
                               'analysis':'自动分析完成；公网背调及逐条回复审核待核验'}})
                task_store.add_followups(key,conversations.get('conversations',[]),completed['id'])
            else:
                dest = stage / 'dashboard-engine'
                selected_windows=dashboard_requested_windows(cfg,as_of)
                selected_dashboard_periods=[{'start':w.get('week_start'),'end':w.get('week_end')} for w in selected_windows]
                prepare_dashboard(dest, cfg, windows=selected_windows)
                # The copied adapter guards each pipeline step; no installation, account selection or browser pop-up.
                helper = (ROOT / 'weekly_dashboard_adapter.py').read_text(encoding='utf-8')
                (dest / 'weekly_dashboard_adapter.py').write_text(helper, encoding='utf-8')
                run([sys.executable, dest / 'weekly_dashboard_adapter.py', '--bridge', bridge,
                     '--expected', expected, '--identity', identity_file, '--workspace-code', ROOT,
                     '--as-of', as_of.isoformat(), '--label', cfg['label']], cwd=dest, env=env, timeout=21600)
                dashboard = dest / 'engine' / 'workspace' / 'dashboard'
                from shared_scan import data_object
                data = data_object((dashboard / 'dashboard_data.js').read_text(encoding='utf-8-sig')) or {}
                if str(data.get('meta', {}).get('store_id')) != expected:
                    raise SyncError('新看板店铺身份未通过核验')
                require_identity(bridge, identity_file, expected)
                names = ('index.html', 'app.js', 'styles.css', 'chart.umd.min.js', 'dashboard_data.js')
                published[kind] = str(publish_files([(dashboard / n, n) for n in names], catalog.SHARE / cfg['folder'], stage.parent.name + '-dashboard'))
            catalog.atomic_json(STATE / 'progress.json', {'store': key, 'stage': kind, 'status': 'SUCCESS', 'finished': catalog.now()})
        except (SyncError, OSError, ValueError, subprocess.TimeoutExpired) as error:
            catalog.atomic_json(STATE / 'progress.json', {'store': key, 'stage': kind, 'status': 'FAILED', 'finished': catalog.now()})
            failures.append({'kind': kind, 'reason': str(error) if isinstance(error, SyncError) else '执行或文件校验未成功，旧报告保持不变'})
    return {'status': 'SUCCESS' if len(published) == 2 and not failures else 'PARTIAL' if published else 'FAILED',
            'publishedKinds': list(published), 'failures': failures,
            'period': {'start': start.isoformat(), 'end': end.isoformat()},
            'dashboardPeriods': selected_dashboard_periods,
            'bridgeVerifiedAt': verified_at,
            'finished': catalog.now(),
            'lastSuccess': catalog.now() if len(published) == 2 and not failures else None}


def update(store=None):
    STATE.mkdir(parents=True, exist_ok=True)
    try:
        previous = json.loads((STATE / 'status.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        previous = {}
    today = datetime.now(catalog.SHANGHAI).date().isoformat()
    selected = [store] if store in STORES else list(STORES)
    if store is not None and store not in STORES:
        return {'status': 'FAILED', 'message': '所选店铺未绑定'}
    if all(str(previous.get('stores', {}).get(key, {}).get('lastSuccess') or '').startswith(today) for key in selected):
        return {'status': 'ALREADY_RUN', 'message': '今天已执行过自动更新，未重复调用接口；请查看已保存结果'}
    lock = STATE / 'update.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return {'status': 'BUSY', 'message': '已有更新任务运行，未启动重复采集'}
    os.close(fd)
    result = {'status': 'RUNNING', 'started': catalog.now(), 'stores': dict(previous.get('stores', {})), 'targetStores': selected, 'message': '正在核对桥接与店铺身份'}
    status_file = STATE / 'status.json'
    catalog.atomic_json(status_file, result)
    stage_name = datetime.now(catalog.SHANGHAI).strftime('%Y%m%d-%H%M%S')
    stage_root = STATE / 'runs' / stage_name
    stage_root.mkdir(parents=True, exist_ok=True)
    try:
        if not catalog.SHARE.is_dir():
            raise SyncError('共享目录不可访问；未启动接口采集，保留旧报告')
        # Reuse the existing local launcher; bridge_runtime injects live credentials only in child environments.
        bridge_stage = stage_root / 'bridge'
        bridge = prepare_bridge(bridge_stage)
        current_identity = bridge_identity(bridge, stage_root / 'current-identity.json')
        for key in selected:
            cfg = STORES[key]
            if current_identity != cfg['expected_id']:
                old_success = result['stores'].get(key, {}).get('lastSuccess')
                result['stores'][key] = {'status': 'WAITING_ACCOUNT', 'message': '当前连接其他店铺，本店跳过；未自动切换账号', 'lastSuccess': old_success}
                catalog.atomic_json(status_file, result)
                continue
            old_success = result['stores'].get(key, {}).get('lastSuccess')
            result['stores'][key] = do_store(key, cfg, stage_root / key, bridge, datetime.now(catalog.SHANGHAI).date())
            if not result['stores'][key].get('lastSuccess'):
                result['stores'][key]['lastSuccess'] = old_success
            result['bridgeVerifiedAt'] = result['stores'][key].get('bridgeVerifiedAt')
            catalog.atomic_json(status_file, result)
        for folder in ('1901', '1903', 'Lifeworth'):
            result['stores'][folder.lower()] = {'status': 'NEEDS_BINDING', 'message': '尚未验证独立账号身份；只扫描已有文件，不自动切换账号'}
        statuses = [result['stores'][key]['status'] for key in selected]
        result['status'] = 'SUCCESS' if all(s == 'SUCCESS' for s in statuses) else 'PARTIAL' if any(s in ('SUCCESS', 'PARTIAL') for s in statuses) else 'FAILED'
        result['message'] = '已完成已绑定店铺的更新检查；未绑定店铺保持原状'
    except (SyncError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        result.update(status='FAILED', message=str(error) if isinstance(error, SyncError) else '桥接或更新前置检查未通过；请确认 Accio 运行、已登录并连接正确店铺')
    finally:
        result['finished'] = catalog.now()
        catalog.atomic_json(status_file, result)
        lock.unlink(missing_ok=True)
        result['scan'] = catalog.scan()
    return result


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--store', choices=list(STORES), help='Update one verified store only')
    args = parser.parse_args()
    if args.run:
        result = update(args.store)
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result['status'] in ('SUCCESS', 'ALREADY_RUN') else 1)
