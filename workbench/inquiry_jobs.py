"""Manual date-scoped inquiry adapter using the existing verified Skill scripts."""
from datetime import date
import json
import hashlib
from pathlib import Path
import shutil
import sys
import uuid
import bridge_catalog
import shared_scan
import task_store as store
import weekly_update as weekly
from bridge_materialization import verified_summary

def cached_source(key, window):
    candidates=[]
    paths=list((weekly.STATE / 'runs').glob('*/'+key+'/inquiry-engine/inquiry/conversations.json'))
    paths.extend((store.STATE/'runs').glob('*/inquiry-engine/inquiry/conversations.json'))
    for path in paths:
        try:
            data=json.loads(path.read_text(encoding='utf-8-sig'))
            w=data.get('window',{})
            if (str(data.get('store',{}).get('aliId'))==weekly.STORES[key]['expected_id']
                and str(w.get('since',''))[:10]==window['start'] and str(w.get('until',''))[:10]==window['end']
                and (path.parent/'buyers.json').is_file()):
                work=path.parent/'.work'
                conv=verified_summary(None,work/'conversations_all.json','conversations',window['start'],window['end'],expected_accounts=data['store'].get('accountCount'))
                messages=verified_summary(None,work/'messages_all.json','messages',window['start'],window['end'])
                if conv and messages:
                    import inquiry_calendar
                    inquiry_calendar.verified_part(path.parent,weekly.STORES[key]['expected_id'],window)
                    candidates.append(path)
        except (OSError,ValueError,KeyError,TypeError):
            pass
    return max(candidates,key=lambda p:p.stat().st_mtime,default=None)

def run(job):
    key=job['store']; cfg=weekly.STORES[key]; window=job['period']
    root=store.STATE/'runs'/job['id']; root.mkdir(parents=True,exist_ok=True)
    engine=root/'inquiry-engine'
    if job.get('resumeHandoff'):
        return finish(job)
    from calendar_periods import window as calendar_window
    calendar_window('custom',window['start'],window['end'])
    release=weekly.prepare_inquiry(engine)
    store.job_update(job['id'],skillVersion=release['version'],pipeline='latest-dossier')
    # Country templates are not current destination-specific legal verification.
    analysis=engine/'inquiry_analysis.py'
    source=analysis.read_text(encoding='utf-8')
    source+='\nREGION_PLAYBOOK = []\n'
    analysis.write_text(source,encoding='utf-8')
    if job.get('resumeAnalysis'):
        if (engine/'calendar-chunks').is_dir():
            import inquiry_calendar
            marker=engine/'inquiry/calendar-collection.json'
            if not marker.is_file() or inquiry_calendar.read(marker).get('status')!='VERIFIED':
                raise ValueError('自然期间分段尚未完整合并，不能把部分采集当成完整报告恢复分析')
            inquiry_calendar.verified_part(engine/'inquiry',cfg['expected_id'],window)
        store.job_update(job['id'],progress='恢复已有聊天的新版分析；公开核验优先复用本次缓存，不重新采集')
    elif job.get('sourceMode')=='cached':
        cached=cached_source(key,window)
        if cached is None:
            raise ValueError('所选店铺和日期没有完整已采集数据，请使用实时采集')
        store.job_update(job['id'],progress='复用同店铺、同日期已采集数据；不重新抓取')
        target=engine/'inquiry'; target.mkdir()
        for name in ('conversations.json','buyers.json','fetch_stats.json','contacts.json','calendar-collection.json'):
            if (cached.parent/name).is_file():
                shutil.copy2(cached.parent/name,target/name)
        work=target/'.work';work.mkdir()
        sources={}
        for name in ('conversations_all.json','messages_all.json','account_messages.json'):
            source=cached.parent/'.work'/name
            if source.is_file():
                sources[name]=hashlib.sha256(source.read_bytes()).hexdigest()
                shutil.copy2(source,work/name)
        messages=json.loads((work/'messages_all.json').read_text(encoding='utf-8-sig'))
        messages['meta']['sourceConversationFile']=str((work/'conversations_all.json').resolve())
        weekly.catalog.atomic_json(work/'messages_all.json',messages)
        if (work/'account_messages.json').is_file():
            account=json.loads((work/'account_messages.json').read_text(encoding='utf-8-sig'))
            account['sources']={name:hashlib.sha256((work/name).read_bytes()).hexdigest()
                                for name in ('conversations_all.json','messages_all.json')}
            weekly.catalog.atomic_json(work/'account_messages.json',account)
        import inquiry_calendar
        inquiry_calendar.verified_part(target,cfg['expected_id'],window)
        weekly.catalog.atomic_json(target/'cached-collection.json',{'source':str(cached.parent),'sourceSha256':sources})
    else:
        store.job_update(job['id'],progress='核验当前桥接店铺')
        if not shared_scan.SHARE.is_dir():
            raise ValueError('共享盘不可访问，未开始采集；旧报告保持不变')
        bridge=weekly.prepare_bridge(root/'bridge')
        weekly.require_identity(bridge,root/'identity.json',cfg['expected_id'])
        import os
        import bridge_runtime
        env=dict(os.environ,PATH=str(bridge)+os.pathsep+os.environ.get('PATH',''))
        env=bridge_runtime.child_environment(bridge/'workctl.cmd',env)
        days=(date.fromisoformat(window['end'])-date.fromisoformat(window['start'])).days+1
        store.job_update(job['id'],progress='采集完整聊天和买家资料，耗时取决于会话数量')
        import inquiry_calendar
        inquiry_calendar.collect(engine,bridge,cfg['expected_id'],window,env=env,
            progress=lambda text:store.job_update(job['id'],progress=text))
        weekly.require_identity(bridge,root/'identity.json',cfg['expected_id'])
        import inquiry_release
        store.job_update(job['id'],progress='补充同店铺客户详情中的邮箱与公司字段')
        contact_result={'source':'platform_contact_details','complete':True,'segmented':True}
        store.job_update(job['id'],contactEnrichment=contact_result)
        weekly.require_identity(bridge,root/'identity.json',cfg['expected_id'])
    data=json.loads((engine/'inquiry/conversations.json').read_text(encoding='utf-8-sig'))
    actual=data.get('window',{})
    if (str(data.get('store',{}).get('aliId'))!=cfg['expected_id'] or
        str(actual.get('since',''))[:10]!=window['start'] or str(actual.get('until',''))[:10]!=window['end']):
        raise ValueError('询盘文件店铺或统计期间不匹配，未更新报告')
    import inquiry_release
    analysis_run=inquiry_release.run_analysis(engine,verify_public=job.get('verifyPublic',True),
        progress=lambda message:store.job_update(job['id'],progress=message))
    weekly.catalog.atomic_json(engine/'analysis_result.json',dict(analysis_run,skillVersion=release['version']))
    reports=list((engine/'inquiry').glob('询盘客户背调分析_*.html'))
    if len(reports)!=1 or reports[0].stat().st_size<1000:
        raise ValueError('报告产物未通过验证')
    # New reports must state the actual analysis boundary, even if a legacy title says "背调".
    report=reports[0]
    html=report.read_text(encoding='utf-8-sig')
    notice='<div style="padding:16px;background:#eef5ef;color:#355743">本次使用最新询盘 Skill，包含主体抽取、自动分层与客户台账。'+('已执行公开来源核验，查不到或不可访问的来源保留待核验。' if analysis_run['publicChecksExecuted'] else '本次未执行公网核验。')+'国家如由账号前缀推断需再次确认；公开来源匹配不是信誉担保。跟进事项仍需人工确认，不自动向客户发送消息。</div>'
    import re
    html=re.sub(r'(<body\b[^>]*>)',lambda m:m.group(1)+notice,html,count=1,flags=re.I)
    report.write_text(html,encoding='utf-8')
    store.job_update(job['id'],progress='报告校验完成，归档共享盘并更新工作台')
    if job.get('sourceMode')!='cached' and not job.get('resumeAnalysis'):
        weekly.require_identity(bridge,root/'identity.json',cfg['expected_id'])
    return finish(job)

def finish(job):
    key=job['store'];cfg=weekly.STORES[key];window=job['period']
    engine=store.STATE/'runs'/job['id']/'inquiry-engine'
    data=json.loads((engine/'inquiry/conversations.json').read_text(encoding='utf-8-sig'))
    if (str(data.get('store',{}).get('aliId'))!=cfg['expected_id'] or
        str(data.get('window',{}).get('since',''))[:10]!=window['start'] or
        str(data.get('window',{}).get('until',''))[:10]!=window['end']):
        raise ValueError('本次产物店铺或统计期间不匹配，无法恢复交接')
    reports=list((engine/'inquiry').glob('询盘客户背调分析_*.html'))
    if len(reports)!=1 or reports[0].stat().st_size<1000:
        raise ValueError('缺少有效报告产物，无法恢复交接')
    report=reports[0]
    name='询盘分析_'+window['start']+'_'+window['end']+'.html'
    directory='manual-'+job['id']+'-inquiry'
    target=shared_scan.SHARE/cfg['folder']/directory/name
    files=[(report,name)]
    ledger_name=None
    for ledger in (engine/'inquiry').glob('客户分层分析表_*'):
        if ledger.suffix in ('.html','.xlsx'):
            ledger_name='客户分层分析表_'+window['start']+'_'+window['end']+ledger.suffix
            files.append((ledger,ledger_name))
    if not target.is_file():
        weekly.publish_files(files,shared_scan.SHARE/cfg['folder'],directory)
    elif target.read_bytes()!=report.read_bytes():
        raise ValueError('共享盘已有同名不同内容，未覆盖；请人工核对')
    shared_scan.scan()
    index=shared_scan.read_index()
    match=next((r for r in index.get('records',[]) if r.get('store')==key and r.get('complete') and
                (directory in r.get('sourceRelative','') or any(directory in path for path in r.get('duplicates',[])))),None)
    if not match:
        raise ValueError('报告已归档，但索引未完成；请扫描共享盘更新，不要重复采集')
    added=store.add_followups(key,data.get('conversations',[]),job['id'])
    profiles=json.loads((engine/'inquiry/buyers.json').read_text(encoding='utf-8-sig'))
    try:
        analysis_run=json.loads((engine/'analysis_result.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):
        analysis_run={}
    return {'reportSnapshot':match.get('id') if match else None,'followupsAdded':added,
            'conversations':len(data.get('conversations',[])), 'analysis':'最新 Skill 分析完成；公开来源的实证、线索和待核验分别展示' if analysis_run else '自动分析完成；公网背调及逐条回复审核待核验',
            'buyerProfiles':len(profiles),'reportIndexed':bool(match),**analysis_run}
