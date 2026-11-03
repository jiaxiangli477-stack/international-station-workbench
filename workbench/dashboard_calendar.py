"""Patch calendar boundaries only in the workbench's copied dashboard engine."""
import ast
from pathlib import Path

def replace_function(source,name,body):
    tree=ast.parse(source);node=next((n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name),None)
    if node is None:raise ValueError('看板日期接口变化：'+name)
    lines=source.splitlines(True);lines[node.lineno-1:node.end_lineno]=[body+'\n'];return ''.join(lines)

def install(package,code,as_of):
    import weekly_update
    package=Path(package).resolve();code=Path(code).resolve()
    if any(package==cfg['dashboard'].resolve() for cfg in weekly_update.STORES.values()):raise ValueError('拒绝修改原始看板包；请先复制到隔离运行目录')
    pipeline=package/'engine/pipeline'
    gos=pipeline/'gos_window.py';source=gos.read_text(encoding='utf-8-sig')
    body="""def compute(as_of, n_weeks=4):
    import json, sys
    from datetime import date
    from pathlib import Path
    sys.path.insert(0, __WORKBENCH_CODE_PATH__)
    from calendar_periods import dashboard_windows
    result = dashboard_windows(as_of, n_weeks)
    proof = Path(__file__).resolve().parents[1] / 'workspace' / 'raw' / 'platform_native_week_windows.json'
    if not proof.is_file():
        return result
    rows = json.loads(proof.read_text(encoding='utf-8-sig')).get('windows') or []
    confirmed = [row for row in rows if isinstance(row, dict)
                 and row.get('source') == 'platform-date-picker'
                 and row.get('confirmed') is True and row.get('evidence')]
    if not confirmed:
        return result
    selected = []
    for row in confirmed:
        start, end = date.fromisoformat(row['start']), date.fromisoformat(row['end'])
        date.fromisoformat(row['statDate'])
        if (end - start).days != 6:
            raise ValueError('平台自然周证据必须覆盖连续7日')
        selected.append({'start': start, 'end': end})
    selected.sort(key=lambda row: row['end'], reverse=True)
    result['weeks'] = [{'idx': index,
                        'week_start': row['start'].isoformat(),
                        'week_end': row['end'].isoformat(),
                        'tag': 'w%d_%s-%s' % (index, row['start'].strftime('%Y%m%d'), row['end'].strftime('%m%d'))}
                       for index, row in enumerate(selected[:n_weeks], 1)]
    return result""".replace('__WORKBENCH_CODE_PATH__', repr(str(code)))
    gos.write_text(replace_function(source,'compute',body),encoding='utf-8')
    monthly=pipeline/'v6_fetch_monthly.py';source=monthly.read_text(encoding='utf-8-sig')
    rows=source.splitlines(True);date_lines=[i for i,line in enumerate(rows) if line.strip() in ("_today = date.today()", "_today = date.fromisoformat(os.environ['DASHBOARD_AS_OF'])") or line.startswith('_today = ') and '# WORKBENCH_CALENDAR_DATE' in line]
    if len(date_lines)!=1:raise ValueError('月度看板采集日期接口变化')
    rows[date_lines[0]]="_today = date.fromisoformat(%r)  # WORKBENCH_CALENDAR_DATE\n"%as_of
    source=''.join(rows)
    lines=source.splitlines(True);matches=[i for i,line in enumerate(lines) if line.startswith('MONTHS = [')]
    if len(matches)!=1:raise ValueError('月度窗口接口变化')
    lines[matches[0]]='MONTHS = []  # Only closed calendar months; no current-month MTD.\n'
    monthly.write_text(''.join(lines),encoding='utf-8')
    products=pipeline/'v6_fetch_products_monthly.py';source=products.read_text(encoding='utf-8-sig')
    body="def default_statdate():\n    months=_gos_ctx.window().get('months') or []\n    if not months: raise ValueError('缺少完整自然月窗口')\n    latest=max(months,key=lambda p:p['month_start'])\n    return latest['month_start'],latest['month_end']"
    products.write_text(replace_function(source,'default_statdate',body),encoding='utf-8')
    judge=pipeline/'v4_judge.py'
    if judge.is_file():
        source=judge.read_text(encoding='utf-8-sig')
        marker="""wk = rall("SELECT * FROM store_weekly_stats ORDER BY stat_week_end")
latest = wk[-1]; prev = wk[-2]
WEEK_END = latest['stat_week_end']; WEEK_START = latest['stat_week_start']
PREV_END = prev['stat_week_end']
print("最新周:", WEEK_START, "~", WEEK_END, "| 上周:", prev['stat_week_start'], "~", PREV_END)
"""
        replacement="""wk = rall("SELECT * FROM store_weekly_stats ORDER BY stat_week_end")
if not wk:
    raise ValueError('缺少已核验的平台自然周数据')
latest = wk[-1]
prev = wk[-2] if len(wk) > 1 else {key: None for key in latest.keys()}
WEEK_END = latest['stat_week_end']; WEEK_START = latest['stat_week_start']
PREV_END = prev.get('stat_week_end')
prev_start = prev.get('stat_week_start') or '无可比周'
print("最新周:", WEEK_START, "~", WEEK_END, "| 上周:", prev_start, "~", PREV_END or '未采集；环比显示为未知')
"""
        if source.count(marker)!=1:raise ValueError('周度判定引擎接口变化，停止适配')
        judge.write_text(source.replace(marker,replacement,1),encoding='utf-8')
    for path in (gos,monthly,products):compile(path.read_text('utf-8'),str(path),'exec')
    if judge.is_file():compile(judge.read_text('utf-8'),str(judge),'exec')
    from dashboard_week_history import install as install_history
    import shutil
    shutil.copy2(code/'dashboard_week_history.py',package/'dashboard_week_history.py')
    shutil.copy2(code/'dashboard_native_week.py',package/'dashboard_native_week.py')
    install_history(package)
