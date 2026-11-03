"""Snapshot the user's current WorkBuddy inquiry release and run its full pipeline."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

FILES=('fetch_inquiries.py','extract_entities.py','verify_companies.py','make_inquiry_report.py',
       'make_customer_table.py','customer_table_html.py','customer_rows.py','deal_blocker.py','inquiry_analysis.py','inquiry_strength.py',
       'inquiry_dossier.py','inquiry_charts.py','company_strength.py','inq_brief.py','fetch_buyer_contacts.py')
BUNDLED_PYTHON=Path(r'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
WORKBOOK_SHEETS=('0 结论与行动','1 说明与口径','2 客户分层总表','3 优质客户明细','4 待跟进行动项',
                 '5 业务员x档位','6 国家x档位','7 待核验索取清单','8 已核验主体','9 成交卡点','10 公司档案','11 图表数据')

def secure_public_verifier(source):
    """Replace the copied upstream opener, including proxy/TLS arguments."""
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == 'build_opener'
             and ast.unparse(node.func.value) == 'urllib.request']
    if len(calls) != 1:
        import weekly_update
        raise weekly_update.SyncError('公网核验传输接口变化，停止自动适配')
    call = calls[0]
    call.func = ast.Name(id='build_public_opener', ctx=ast.Load())
    call.args = []
    call.keywords = []
    return ast.unparse(ast.fix_missing_locations(tree)) + '\n'


def align_report_quality(source):
    """Use the shared buyer strength for the report's older summary calculation."""
    marker='    qmap, qconv = {}, {}\n'
    calculation="q = DO.quality_of(c, bmap.get(nm), st_of(nm))"
    if source.count(marker)!=1 or source.count(calculation)!=1:
        import weekly_update
        raise weekly_update.SyncError('报告分层接口变化，需要重新核对与台账的一致性')
    source=source.replace(marker,marker+"    _workbench_rows = (_build_rows() or ([], {}))[0]\n"
                          "    _workbench_strength = {r['name']: r['strength'] for r in _workbench_rows}\n",1)
    return source.replace(calculation,"q = DO.quality_of(c, bmap.get(nm), dict(st_of(nm), strength=_workbench_strength[nm]))",1)


def prepare(destination):
    import weekly_update as weekly
    destination.mkdir(parents=True,exist_ok=True)
    manifest={'capturedAt':weekly.catalog.now(),'files':{}}
    for name in FILES:
        source_path=weekly.PACKAGE/name
        if not source_path.is_file():
            raise weekly.SyncError('最新询盘 Skill 缺少依赖：'+name)
        before=source_path.stat().st_mtime_ns
        raw=source_path.read_bytes()
        if before!=source_path.stat().st_mtime_ns:
            raise weekly.SyncError('询盘 Skill 正在更新，请稍后重新提交，未混用版本')
        source=raw.decode('utf-8-sig').replace('\r\n','\n').replace('\r','\n')
        for node in ast.walk(ast.parse(source)):
            imports=([node.module.split('.')[0]] if isinstance(node,ast.ImportFrom) and node.module else
                     [name.name.split('.')[0] for name in node.names] if isinstance(node,ast.Import) else [])
            for module in imports:
                local_name=module+'.py'
                if local_name not in FILES and (weekly.PACKAGE/local_name).is_file():
                    raise weekly.SyncError('最新询盘 Skill 新增本地依赖，需要先接入：'+local_name)
        manifest['files'][name]={'sha256':hashlib.sha256(raw).hexdigest(),'source':str(source_path),'modifiedNs':before}
        if name=='fetch_inquiries.py':
            source=weekly.patch_inquiry_source(source)
        elif name=='make_inquiry_report.py':
            source=align_report_quality(source)
        elif name=='fetch_buyer_contacts.py':
            marker='s_ms, e_ms = ms(start), ms(end) + 12 * 3600 * 1000'
            if source.count(marker)!=1:
                raise weekly.SyncError('联系人采集日期接口变化，停止自动适配')
            source=source.replace(marker,'s_ms, e_ms = ms(start), ms(end) + 24 * 3600 * 1000 - 1',1)
        elif name in ('inquiry_analysis.py','inquiry_strength.py','inquiry_dossier.py'):
            source=ast.unparse(ast.fix_missing_locations(weekly.RemovePriorCustomers().visit(ast.parse(source))))
            if name=='inquiry_analysis.py':source+='\nREGION_PLAYBOOK = []\n'
        elif name=='verify_companies.py':
            # The upstream helper disables TLS verification for its proxy. Keep verification on.
            source=source.replace('ctx.check_hostname = False','ctx.check_hostname = True')
            source=source.replace('ctx.verify_mode = ssl.CERT_NONE','ctx.verify_mode = ssl.CERT_REQUIRED')
            source=source.replace('import argparse\n','import argparse\nfrom public_checks import build_public_opener, require_public_url\n',1)
            marker='        req = urllib.request.Request(url, headers={'
            if source.count(marker)!=1:
                raise weekly.SyncError('公网核验脚本接口变化，停止自动适配')
            source=source.replace(marker,'        require_public_url(url)\n'+marker,1)
            source=secure_public_verifier(source)
        compile(source,name,'exec')
        (destination/name).write_text(source,encoding='utf-8',newline='\n')
    shutil.copy2(weekly.ROOT/'bridge_materialization.py',destination/'bridge_materialization.py')
    shutil.copy2(weekly.ROOT/'public_checks.py',destination/'public_checks.py')
    manifest['adapterSha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    policy=weekly.ROOT/'.agents/skills/alibaba-inquiry-dossier/SKILL.md'
    policy_bytes=policy.read_bytes()
    (destination/'SKILL.md').write_bytes(policy_bytes)
    manifest['calendarPolicy']={'sha256':hashlib.sha256(policy_bytes).hexdigest(),'source':str(policy)}
    manifest['calendarAdapter']={name:hashlib.sha256((weekly.ROOT/name).read_bytes()).hexdigest() for name in ('calendar_periods.py','inquiry_calendar.py')}
    manifest['version']=hashlib.sha256(json.dumps({'files':manifest['files'],'adapter':manifest['adapterSha256'],'calendarPolicy':manifest['calendarPolicy'],'calendarAdapter':manifest['calendarAdapter']},sort_keys=True).encode()).hexdigest()[:16]
    if any(Path(value['source']).stat().st_mtime_ns!=value['modifiedNs'] for value in manifest['files'].values()):
        raise weekly.SyncError('询盘 Skill 更新期间版本发生变化，请稍后重新提交')
    weekly.catalog.atomic_json(destination/'skill_manifest.json',manifest)
    return manifest


def collect_contacts(engine,bridge,expected,start,end,env=None):
    """Enrich only a freshly identity-checked store/window; never switch accounts."""
    import weekly_update as weekly
    result=weekly.run([sys.executable,weekly.ROOT/'contact_enrichment.py','--engine',engine,
                      '--bridge',bridge,'--expected',str(expected),'--start',start,'--end',end],
                     engine,timeout=7200,env=env)
    return json.loads(result)

def run_analysis(engine,verify_public=True,progress=None):
    import weekly_update as weekly
    def update(message):
        if progress:progress(message)
    update('最新 Skill：从聊天提取客户主体线索')
    weekly.run([sys.executable,engine/'extract_entities.py'],engine,timeout=600)
    if verify_public:
        update('最新 Skill：核验公开域名、官网与工商来源；无证据不会标为已核验')
        weekly.run([sys.executable,engine/'verify_companies.py'],engine,timeout=7200)
    update('最新 Skill：生成综合询盘报告与客户分层 HTML 台账')
    weekly.run([sys.executable,engine/'make_inquiry_report.py'],engine,timeout=600)
    python=Path(sys.executable) if importlib.util.find_spec('openpyxl') else BUNDLED_PYTHON
    if not python.is_file():
        raise weekly.SyncError('缺少已有 Excel 运行环境，报告已保留，台账生成未完成')
    weekly.run([python,engine/'make_customer_table.py'],engine,timeout=600)
    folder=engine/'inquiry'
    ledgers=list(folder.glob('客户分层分析表_*.html'))
    books=list(folder.glob('客户分层分析表_*.xlsx'))
    if len(ledgers)!=1 or len(books)!=1 or ledgers[0].stat().st_size<1000:
        raise weekly.SyncError('最新 Skill 台账产物缺失或不完整')
    # Validate names as well as count: a missing blocker table must not pass as complete.
    command='import json,openpyxl,sys;w=openpyxl.load_workbook(sys.argv[1],read_only=True);assert w.sheetnames==json.loads(sys.argv[2]),w.sheetnames;w.close()'
    weekly.run([python,'-c',command,books[0],json.dumps(WORKBOOK_SHEETS,ensure_ascii=False)],engine,timeout=120)
    reports=list(folder.glob('询盘客户背调分析_*.html'))
    if len(reports)!=1:
        raise weekly.SyncError('综合询盘报告缺失或有多份，未交接')
    import calendar_periods
    from html import escape
    period=json.loads((folder/'conversations.json').read_text(encoding='utf-8-sig')).get('window',{})
    start,end=str(period.get('since',''))[:10],str(period.get('until',''))[:10]
    period_kind=calendar_periods.kind(start,end)
    label='自然周（周一至周日）' if period_kind=='week' else '自然月（1日至月末）'
    for page in reports+ledgers:
        html=page.read_text(encoding='utf-8-sig')
        import re
        notice='<div style="padding:14px;background:#eef5ef;color:#355743"><b>统计口径：'+label+'</b> · '+escape(start)+' 至 '+escape(end)+' · Asia/Shanghai。跨分段会话已合并；不使用滚动7/30天替代。</div>'
        html=re.sub(r'(<body\b[^>]*>)',lambda m:m.group(1)+notice,html,count=1,flags=re.I)
        page.write_text(html,encoding='utf-8')
    consistency="""import openpyxl,sys,re
from collections import Counter
from pathlib import Path
w=openpyxl.load_workbook(sys.argv[1],read_only=True,data_only=True)
counts=Counter(r[0] for r in w['2 客户分层总表'].iter_rows(min_row=2,values_only=True) if r[0])
html=Path(sys.argv[2]).read_text(encoding='utf-8-sig')
for tier in ('优质客户','潜力客户','无效 / 风险'):
    match=re.search(re.escape('<div class="l">'+tier+'</div>')+r'\\s*<div class="v">(\\d+)</div>',html)
    assert match and int(match.group(1))==counts[tier],('HTML/Excel tier mismatch',tier)
w.close()
"""
    weekly.run([python,'-c',consistency,books[0],reports[0]],engine,timeout=120)
    entities=json.loads((folder/'entities.json').read_text(encoding='utf-8-sig'))
    result={'pipeline':'latest-dossier','publicChecksExecuted':bool(verify_public),
            'periodKind':period_kind,'period':{'start':start,'end':end},'timezone':'Asia/Shanghai',
            'entityBuyers':len(entities.get('buyers',{})),'workbookSheets':len(WORKBOOK_SHEETS),
            'dealBlockersIncluded':True,'companyStrengthIncluded':True,'actionBriefIncluded':True}
    if verify_public:
        verified=json.loads((folder/'verify_auto.json').read_text(encoding='utf-8-sig'))
        groups=list(verified.get('buyers',{}).values())
        result['publicEvidenceBuyers']=sum(any(not str(e).startswith('身份线索') for e in v.get('evidence',[])) for v in groups)
        result['traceableIdentityBuyers']=sum(any(str(e).startswith('身份线索') for e in v.get('evidence',[])) for v in groups)
        result['publicUnverifiedBuyers']=len(groups)-result['publicEvidenceBuyers']
    return result
