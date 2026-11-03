"""Narrow commands and a serial worker for explicit user operations."""
import json
from pathlib import Path
import re
import threading
from urllib.request import urlopen
import task_store as store
import weekly_update
import skill_jobs
import topic_workflow
import recruitment_board
import recruitment_chain
import selection_jobs
import recruitment_images
import production_flow
import attribute_plan
import single_approval_flow

_worker_lock=threading.Lock()

def overview():
    jobs=store.records('jobs')
    # Never send runner logs, account identifiers or local credential paths.
    products=store.records('products')
    for product in products:
        product['rectification']=topic_workflow.report(product)
        if product['rectification']:
            import recruitment_detect
            product['rectification']['platform']=recruitment_detect.current(product)
        product['workflowPlan']=production_flow.plan(product)
        product['templatePreviews']=[]
        for kind in ('hero','visual','visualPartial','visualPending'):
            asset=product.get(kind) or {}
            if asset.get('revision')!=product['revision']:continue
            for row in asset.get('images',[]):
                if re.fullmatch(r'm[12]|d[123]',row.get('slot','')) and (store.STATE/'runs'/asset['job']/'native-requests'/(row['slot']+'.json')).is_file():
                    product['templatePreviews'].append({'job':asset['job'],'slot':row['slot'],
                        'url':'/task-template-assets/'+asset['job']+'/'+row['slot']})
    return {'jobs':jobs[:100], 'products':products, 'todos':store.records('todos'),
            'recruitmentRuns':recruitment_board.latest(summary=True),
            'stores':[{'id':key,'label':cfg['label']} for key,cfg in weekly_update.STORES.items()],
            'executor':skill_jobs.capability(), 'today':store.now()[:10]}


def quality_reports():
    """Read only the current-revision summaries from the isolated local Skill runs."""
    import product_intelligence_adapter
    return product_intelligence_adapter.latest_diagnostics()


def quality_report(product_id, run_id):
    import product_intelligence_adapter
    return product_intelligence_adapter.read_report(product_id, run_id)


def quality_diagnose(payload):
    if not isinstance(payload, dict):
        raise ValueError('诊断请求格式无效')
    import product_intelligence_adapter
    return product_intelligence_adapter.diagnose(payload.get('product_id'), payload.get('revision'))

def candidate(candidate_id):
    if not isinstance(candidate_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',candidate_id):
        raise ValueError('候选编号无效')
    item=next((c for c in selection_jobs.source() if c['id']==candidate_id),None)
    if item is None:
        raise ValueError('候选已变化或不存在，请刷新选品工作台')
    if item.get('screening',{}).get('status')=='EXCLUDED':
        raise ValueError('该候选已被经营范围规则排除')
    return store.create_product('selection:'+candidate_id,item['title'],
                                references=[{'url':r.get('url'),'image_url':r.get('image_url'),'name':r.get('name'),'scope':'外部参考，非我方事实'} for r in item.get('product_references',[])],
                                facts={'mode':'concept','market':' / '.join(m['country'] for m in item.get('markets',[])),
                                       'form':item.get('form',''), 'design':item.get('differentiation',''),
                                       'spec':'','formula':'','price':'','moq':'','store':'','own_image':''})

def selection_choices():
    return selection_jobs.choices()

def command(payload):
    import single_approval_flow
    action=payload.get('action')
    if action=='listing.browser.status':
        import listing_browser
        return listing_browser.status()
    if action=='recruitment.detect':
        import recruitment_detect
        from uuid import uuid4
        p=store.product(payload.get('id'))
        if payload.get('revision')!=p['revision']:raise ValueError('产品版本已变化，请刷新后检测')
        scope=recruitment_detect.target(p)
        result=recruitment_detect.collect(p,store.STATE/'recruitment-detect'/uuid4().hex)
        verified=recruitment_detect.current(dict(p,platformDetection=result))
        if verified.get('status') not in ('PASSED','FAILED'):raise ValueError('本次平台检测证据未通过核验，未回填')
        with store.db() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row=connection.execute('SELECT data FROM products WHERE id=?',(p['id'],)).fetchone()
            current=json.loads(row['data']) if row else {}
            try:same=recruitment_detect.target(current)==scope
            except ValueError:same=False
            if not same:raise ValueError('检测期间产品、店铺、草稿或主题已变化，结果保留但未覆盖')
            current['platformDetection']=verified
            current.setdefault('events',[]).append({'time':store.now(),'message':'平台草稿征品检测已完成：'+('符合要求' if verified['meet'] else '存在未满足项')+'；未报名或发布'})
            connection.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(current,ensure_ascii=False),p['id']))
        return current
    if action=='listing.browser.open':
        import listing_browser
        product=store.product(payload.get('id'))
        if payload.get('revision')!=product['revision']:raise ValueError('产品版本已变化，请刷新')
        return listing_browser.open_browser(product)
    if action=='listing.skill.prepare':
        import listing_adapter
        from project_paths import skill_root
        import uuid
        product=store.product(payload.get('id'))
        if payload.get('revision')!=product['revision']:raise ValueError('产品版本已变化，请刷新后准备')
        result=listing_adapter.prepare_original_skill(product,store.STATE/'listing-skill'/uuid.uuid4().hex,skill_root('alibaba-attribute-filler').parent)
        return listing_adapter.persist_skill_preparation(product,result)
    if action in ('listing.content.save','listing.skill.complete'):
        import listing_adapter
        from project_paths import skill_root
        import uuid
        product=store.product(payload.get('id'))
        if payload.get('revision')!=product['revision']:raise ValueError('产品版本已变化，请刷新')
        if action=='listing.content.save':
            return listing_adapter.save_listing_content(product,payload.get('manifest'),payload.get('field_sources'))
        return listing_adapter.complete_saved_draft(product,store.STATE/'listing-skill'/uuid.uuid4().hex,skill_root('alibaba-attribute-filler').parent)
    if action in ('cloud.sync','cloud.adopt','cloud.reject'):
        import cloud_team
        return cloud_team.sync_once() if action=='cloud.sync' else cloud_team.review(payload.get('id'),action=='cloud.adopt')
    if action=='publication.refresh':
        import listing_adapter
        p=store.product(payload.get('id'))
        observed=(listing_adapter.refresh_publication(p,recover_browser=True) if payload.get('recoverBrowser') is True
                  else listing_adapter.refresh_publication(p))
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            current=json.loads(c.execute('SELECT data FROM products WHERE id=?',(p['id'],)).fetchone()['data'])
            if current['revision']!=p['revision'] or (current.get('draft') or {}).get('draft_id')!=(p.get('draft') or {}).get('draft_id'):
                raise ValueError('产品或草稿已变化，请重新读取发布状态')
            current['publication']=observed
            c.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(current,ensure_ascii=False),p['id']))
        return current
    if action=='job.reconcile-output':
        job=next((j for j in store.records('jobs') if j['id']==payload.get('id')),None)
        if not job or not job.get('product') or job['status']!='NEEDS_ATTENTION':
            raise ValueError('当前任务无需产物对账')
        if job.get('executorStillRunning') or production_flow.process_alive(job.get('executorPid')):
            raise ValueError('原执行器仍在运行，请等待结束，不重复接管')
        p=store.product(job['product']);root=store.STATE/'runs'/job['id']
        if p['revision']!=job['revision']:raise ValueError('资料版本已变化，保留旧产物供核对，不能直接交接')
        if job['kind']=='listing':
            import listing_adapter
            from project_paths import skill_root
            if payload.get('refreshSavedDraft') is True:
                result=listing_adapter.refresh_saved(job,p,root,skill_root('alibaba-attribute-filler').parent)
                current=store.commit_output(p['id'],job['revision'],'listing',dict(result,job=job['id'],revision=job['revision']))
                store.job_update(job['id'],status='SUCCESS',recoveryRequired=False,finished=store.now(),
                                 progress='已有草稿只读回读完成，未再次保存或新建商品')
                if (current.get('workflow') or {}).get('status')!='STOPPED':
                    production_flow.update(p['id'],status='DRAFT_SAVED',next='done',gaps=[],
                                           message='草稿已保存并回读，等待后台最终检查；未发布')
                return store.product(p['id'])
            checked=listing_adapter.reconcile_saved(job,p,root,skill_root('alibaba-attribute-filler').parent)
            released=checked.get('status')=='no_save_verified' and checked.get('reconciliationRequired') is False
            store.job_update(job['id'],status='NEEDS_ATTENTION',recoveryRequired=not released,reconciliation=checked,
                             progress=checked.get('next','本地证据已核对；仍需核对当前平台权威状态，未解除防重'))
            return store.product(p['id'])
        else:
            if not (root/'result.json').is_file():raise ValueError('尚无可验收的完整产物；未重新调用模型或平台')
            result=json.loads((root/'result.json').read_text(encoding='utf-8-sig'))
            if job['kind']=='attributes':attribute_plan.install(p,job,root,result)
            else:
                saved_input=json.loads((root/'input.json').read_text(encoding='utf-8-sig')) if (root/'input.json').is_file() else {}
                saved_policy=saved_input.get('nativeTemplateContract')
                if job['kind'] in ('visual','hero'):
                    import native_skill_jobs
                    policy=saved_policy if isinstance(saved_policy,dict) and isinstance(saved_policy.get('templates'),dict) else native_skill_jobs.contract(skill_jobs.SKILLS)
                    if not policy.get('skillRoot'):
                        legacy=Path.home()/'.codex/skills/b2b-image-skill'
                        if native_skill_jobs.policy_matches_skill(legacy,policy):policy['skillRoot']=str(legacy)
                    policy['executionBinding']={'job':job['id'],'product':p['id'],'revision':job['revision'],
                                                'attributePlanFingerprint':(p.get('attributePlan') or {}).get('fingerprint','')}
                else:
                    policy=None
                images=skill_jobs.validate_result(root,job['kind'],result,
                    policy.get('templates') if job['kind']=='visual' and policy else None)
                if policy:
                    images=native_skill_jobs.verify(root,images,policy)
                binding=saved_input.get('executionBinding') or {}
                asset={'job':job['id'],'revision':p['revision'],'images':images,
                       'attributePlanFingerprint':binding.get('attributePlanFingerprint','')}
                if job['kind']=='visual' and policy:asset['templateCount']=len(policy['templates'])
                if not attribute_plan.artifact_matches(p,asset):raise ValueError('产物属性方案已变化，请重新预检')
                if job['kind']=='hero':
                    asset['templateVerified']=True
                    single_approval_flow.install_hero(p['id'],p['revision'],asset)
                else:
                    store.commit_output(p['id'],p['revision'],job['kind'],asset)
        store.job_update(job['id'],status='SUCCESS',recoveryRequired=False,progress='已重新核对落盘产物，未重复执行',finished=store.now())
        if (p.get('workflow') or {}).get('status')!='STOPPED':
            production_flow.update(p['id'],status='ACTIVE')
            production_flow.advance(p['id'])
        return store.product(p['id'])
    if action=='workflow.adopt':
        identities=payload.get('ids'); key=payload.get('store')
        if not isinstance(identities,list) or not 1<=len(identities)<=10 or key not in weekly_update.STORES:
            raise ValueError('请选择已绑定店铺及1至10个来源产品')
        items=[]
        for identity in dict.fromkeys(identities):
            if payload.get('source')=='selection':
                p=candidate(identity)
                if p['facts'].get('store') not in (None,'',key):
                    raise ValueError('候选已有其他店铺任务，请打开原任务核对')
                if not p['facts'].get('store'):
                    p=store.amend_product(p['id'],dict(p['facts'],store=key),p['revision'])
            elif payload.get('source')=='recruitment':
                t,_=topic_workflow.cached_topic(key,str(identity),payload.get('businessType'))
                origin=recruitment_images.identity(key,t['businessType'],t['id'])
                previous=next((p for p in store.records('products') if p['source']==origin),None)
                if previous and previous.get('recruitment',{}).get('fingerprint')!=topic_workflow.fingerprint(t):
                    raise ValueError('主题要求已变化，请核对原任务后重新关联')
                p=recruitment_images.prepare(t,key,previous)
                if not p['id']:
                    import uuid
                    p['id']='P-'+uuid.uuid4().hex[:12]
                p=store.save_product(p)
            else:
                raise ValueError('无效产品来源')
            items.append({'id':p['id'],'revision':p['revision']})
        return {'items':items,'target':payload.get('target','DRAFT')}
    if action=='workflow.preview':
        return production_flow.preview(payload.get('items'),payload.get('store'),payload.get('target','DRAFT'),payload.get('approvalPolicy'))
    if action=='workflow.start':
        return production_flow.start(payload.get('items'),payload.get('store'),payload.get('acknowledgeExecution'),payload.get('imageProvider','codex-native'),payload.get('target','DRAFT'),payload.get('approvalPolicy'),payload.get('freshVisualContract') is True)
    if action=='workflow.stop':
        return production_flow.stop(payload.get('id'))
    if action=='hero.approve':
        p=single_approval_flow.approve(payload.get('id'),payload.get('revision'),payload.get('artifactJob'),
            payload.get('fingerprint'),payload.get('pixelHash'),payload.get('acknowledgeHero'))
        production_flow.advance(p['id'])
        return store.product(p['id'])
    if action=='attributes.edit':
        return attribute_plan.edit(payload.get('id'),payload.get('revision'),payload.get('manifest'),payload.get('field_sources'),payload.get('unresolved'),payload.get('fingerprint'))
    if action=='attributes.approve':
        result=attribute_plan.approve(payload.get('id'),payload.get('revision'),payload.get('job'),payload.get('fingerprint'),payload.get('acknowledgeSpecifications'))
        production_flow.advance(result['id'])
        return store.product(result['id'])
    if action=='job.resume-native':
        import native_skill_jobs
        job=next((j for j in store.records('jobs') if j['id']==payload.get('id')),None)
        if not job or job.get('imageProvider')!='codex-native' or job['kind'] not in ('visual','hero') or job['status']!='NEEDS_ATTENTION':
            raise ValueError('此任务不能恢复原生模板执行')
        p=store.product(job['product'])
        if job.get('executorStillRunning') or production_flow.process_alive(job.get('executorPid')):
            raise ValueError('原生执行器仍在运行，请勿重复恢复')
        if payload.get('acknowledgeExecution') is not True:raise ValueError('请确认继续本次固定模板制作')
        if p['revision']!=job['revision'] or payload.get('revision')!=p['revision']:raise ValueError('资料版本已变化，请重新预览')
        if single_approval_flow.enabled(p) and job['kind']=='visual':single_approval_flow.require_hero(p)
        gaps=skill_jobs.missing(p,job['kind'])
        if gaps:raise ValueError('请先处理：'+'、'.join(gaps))
        if any(j.get('product')==p['id'] and j['status'] in store.ACTIVE for j in store.records('jobs')):
            raise ValueError('该产品已有活动任务')
        sid=native_skill_jobs.session(store.STATE/'runs'/job['id'])
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            current=json.loads(c.execute('SELECT data FROM products WHERE id=?',(p['id'],)).fetchone()['data'])
            latest=json.loads(c.execute('SELECT data FROM jobs WHERE id=?',(job['id'],)).fetchone()['data'])
            if current['revision']!=job['revision'] or latest['status']!='NEEDS_ATTENTION':raise ValueError('恢复前任务或产品已变化，请刷新')
            if latest.get('executorStillRunning'):raise ValueError('原执行器回收尚未确认，先处理恢复待办')
            if c.execute("SELECT 1 FROM jobs WHERE scope=? AND status IN ('QUEUED','RUNNING')",('product:'+p['id'],)).fetchone():raise ValueError('该产品已有活动任务')
            if single_approval_flow.enabled(current) and job['kind']=='visual':single_approval_flow.require_hero(current)
            gaps=skill_jobs.missing(current,job['kind'])
            if gaps:raise ValueError('请先处理：'+'、'.join(gaps))
            updated=dict(latest,status='QUEUED',nativeResumeSession=sid,finished=None,recoveryRequired=False,
                         progress='恢复已有固定模板及缓存，继续未完成模块',updated=store.now())
            flow=current.get('workflow')
            if flow:
                if flow.get('revision')!=current['revision']:raise ValueError('主流程版本已变化，请重新预检')
                if flow.get('status')=='NEEDS_ATTENTION':
                    flow.update(status='ACTIVE',job=job['id'],next=job['kind'],message=updated['progress'],updated=store.now())
            else:
                current['selectionFlow']=dict(current.get('selectionFlow') or {},revision=p['revision'],status='ACTIVE',target='VISUALS',imageProvider='codex-native',message=updated['progress'])
            c.execute('UPDATE jobs SET status=?,data=?,updated=? WHERE id=?',('QUEUED',json.dumps(updated,ensure_ascii=False),updated['updated'],job['id']))
            c.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(current,ensure_ascii=False),p['id']))
        return updated
    if action=='product.design.approve':
        import packaging_design
        return packaging_design.approve(payload)
    if action=='topic.products.preview':
        return recruitment_images.preview_products(payload.get('items'),payload.get('store'))
    if action=='topic.products.start':
        return recruitment_images.start_products(payload.get('items'),payload.get('store'),payload.get('acknowledgeExecution'))
    if action=='topic.concept.direction':
        import concept_direction
        return concept_direction.resolve(payload.get('id'),payload.get('revision'),payload.get('choice'))
    if action=='topic.images.preview':
        return recruitment_images.preview(payload.get('store'),payload.get('businessType'),payload.get('topics'))
    if action=='topic.images.start':
        return recruitment_images.start(payload.get('store'),payload.get('businessType'),payload.get('items'),payload.get('acknowledgeExecution'))
    if action=='topic.images.stop':
        return recruitment_images.stop(payload.get('id'))
    if action=='selection.preview':
        return selection_jobs.preview(payload.get('candidates'))
    if action=='selection.start':
        return selection_jobs.start(payload.get('items'),payload.get('acknowledgeExecution'))
    if action=='recruitment.scan':
        query=payload.get('query')
        if not isinstance(query,dict):raise ValueError('筛选条件无效')
        run=recruitment_board.scan(payload.get('store'),query)
        return {k:v for k,v in run.items() if k!='items'}
    if action=='recruitment.adopt':
        topics=payload.get('topics')
        if not isinstance(topics,list) or not 1<=len(topics)<=10:raise ValueError('请选择1至10个主题')
        adopted=[];blocked=[]
        for topic_id in dict.fromkeys(topics):
            try:adopted.append(recruitment_board.adopt(payload.get('run'),topic_id))
            except ValueError as error:blocked.append({'topic':topic_id,'reason':str(error)})
        return {'products':adopted,'blocked':blocked}
    if action=='recruitment.preview':
        return recruitment_chain.preview(payload.get('items'),payload.get('store'))
    if action=='recruitment.start':
        return recruitment_chain.start(payload.get('items'),payload.get('store'),payload.get('acknowledgeExecution'))
    if action=='recruitment.stop':
        return recruitment_chain.stop(payload.get('id'))
    if action=='job.resume-handoff':
        job=next((j for j in store.records('jobs') if j['id']==payload.get('id')),None)
        if not job or job['kind']!='inquiry' or job['status']!='NEEDS_ATTENTION':
            raise ValueError('此任务不可恢复交接')
        root=store.STATE/'runs'/job['id']/'inquiry-engine/inquiry'
        if not (root/'conversations.json').is_file():
            raise ValueError('尚无已采集数据，请先处理采集或连接阻塞')
        ready=(root.parent/'analysis_result.json').is_file() and bool(list(root.glob('询盘客户背调分析_*.html')))
        return store.job_update(job['id'],status='QUEUED',resumeHandoff=ready,resumeAnalysis=not ready,progress='恢复已有数据的分析或报告交接，不重新采集')
    if action=='inquiry.create':
        key=payload.get('store')
        if key not in weekly_update.STORES:
            raise ValueError('所选店铺未完成身份绑定')
        window=store.period(payload.get('periodMode'),payload.get('start'),payload.get('end'))
        mode=payload.get('sourceMode','live')
        if mode not in ('live','cached'):
            raise ValueError('无效数据采集方式')
        return store.enqueue('inquiry','inquiry:'+key,{'store':key,'period':window,'sourceMode':mode,'verifyPublic':payload.get('verifyPublic',True) is True,'analysisBoundary':'最新主体抽取、公网核验、分层台账；未能核验的保留待核验'})
    if action=='candidate.adopt':
        return candidate(payload.get('candidate'))
    if action=='topic.adopt':
        key=payload.get('store'); topic_id=str(payload.get('topic') or '')
        business=payload.get('businessType')
        topic,_=topic_workflow.cached_topic(key,topic_id,business)
        product=store.create_product('topic:'+key+':'+business+':'+topic_id,topic['title'],
                                     references=[{'name':'平台征品主题 '+topic_id,'scope':'主题要求，非我方事实'}],
                                     facts={'mode':'concept','store':key,'design':'参考征品主题方向设计原创包装；平台条件须逐项核对我方实际产品。'})
        return topic_workflow.attach(product,key,topic)
    if action=='topic.rectify':
        return topic_workflow.save(payload.get('id'),payload.get('revision'),payload.get('entries'))
    if action=='product.create':
        title=str(payload.get('title') or '').strip()[:200]
        if not title:
            raise ValueError('请填写产品名称')
        import uuid
        facts={'mode':'concept','market':'INTERNAL_B2B','form':str(payload.get('form') or '')[:100],
               'design':str(payload.get('design') or '按新品需求设计原创包装，沿用原Skill固定主图及详情模板')[:4000],
               'store':payload.get('store') if payload.get('store') in weekly_update.STORES else ''}
        return store.create_product('manual:'+uuid.uuid4().hex,title,facts=facts)
    if action=='product.save':
        if not isinstance(payload.get('facts'),dict):
            raise ValueError('缺少产品资料')
        return store.amend_product(payload.get('id'),payload['facts'],payload.get('revision'))
    if action=='product.run':
        product=store.product(payload.get('id')); kind=payload.get('kind')
        if kind not in ('packaging','hero','visual','attributes','listing'):
            raise ValueError('无效执行阶段')
        if payload.get('revision')!=product['revision']:
            raise ValueError('产品资料已更新，请刷新后执行')
        if kind=='hero' and not single_approval_flow.enabled(product):
            raise ValueError('正式首图任务须先显式启用首图确认策略')
        if single_approval_flow.enabled(product):
            if (product.get('workflow') or {}).get('status') in ('STOPPED','STALE','NEEDS_ATTENTION'):
                raise ValueError('主任务已暂停，请先明确重新预检')
            product=single_approval_flow.apply_automatic(product['id'])
            if kind in ('visual','listing'):single_approval_flow.require_hero(product)
            if kind=='listing':single_approval_flow.require_listing(product,original_skill=(product.get('workflow') or {}).get('listingMechanism')=='original-skill-v1')
        if kind=='listing' and (product.get('workflow') or {}).get('target')=='VISUALS':
            raise ValueError('当前仅图片目标，请先明确预检并选择草稿目标')
        if any(j.get('product')==product['id'] and j.get('recoveryRequired') for j in store.records('jobs')):
            raise ValueError('已有执行结果待对账，请核对上游产物或原任务；不重复执行或扣费')
        if kind=='listing' and (product.get('workflow') or {}).get('target')=='VISUALS':
            raise ValueError('当前主任务仅图片；请明确预检并启动草稿目标后再上品')
        if kind=='listing' and (product.get('draft') or product.get('draftHistory')):
            raise ValueError('已有草稿记录，请先回读或更新已有草稿，不重复创建')
        gaps=skill_jobs.missing(product,kind)
        if gaps:
            raise ValueError('请先补齐并保存：'+'、'.join(gaps))
        if kind=='listing' and product['facts'].get('store') not in weekly_update.STORES:
            raise ValueError('上品目标店铺未绑定')
        if payload.get('acknowledgeExecution') is not True:
            raise ValueError('请确认使用现有执行器与服务额度')
        if not skill_jobs.capability()['available']:
            raise ValueError('本机 Skill 执行器不可用')
        provider=payload.get('imageProvider','codex-native')
        if provider not in ('codex-native','configured','tokenstation'):raise ValueError('无效生图通道')
        partial=product.get('visualPartial') or {}
        if kind=='visual' and provider=='codex-native' and partial.get('revision')==product['revision']:
            prior=next((j for j in store.records('jobs') if j['id']==partial.get('job')),None)
            if prior and prior.get('imageProvider')=='codex-native' and prior['status']=='NEEDS_ATTENTION':
                return command({'action':'job.resume-native','id':prior['id'],'revision':product['revision'],'acknowledgeExecution':True})
        job=store.enqueue(kind,'product:'+product['id'],{'product':product['id'],'revision':product['revision'],'store':product['facts'].get('store'),
                          'imageProvider':provider,'selectionContinuation':kind=='visual' and bool(product.get('selectionFlow'))})
        if kind=='visual' and product.get('selectionFlow'):
            with store.db() as c:
                c.execute('BEGIN IMMEDIATE')
                p=json.loads(c.execute('SELECT data FROM products WHERE id=?',(product['id'],)).fetchone()['data'])
                if p['revision']==product['revision']:
                    p['selectionFlow'].update(status='ACTIVE',target='VISUALS',imageProvider=provider,message='已明确提交，按固定模板继续整套生图')
                    c.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(p,ensure_ascii=False),p['id']))
        return job
    if action=='product.approve':
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT data FROM products WHERE id=?',(payload.get('id'),)).fetchone()
            if not row:
                raise ValueError('产品不存在')
            p=json.loads(row['data'])
            if payload.get('revision')!=p['revision']:
                raise ValueError('资料版本已变化，请重新审核')
            if single_approval_flow.enabled(p) and payload.get('phase') in ('packaging','visual'):
                raise ValueError('本任务仅需确认正式m1首图，包装与套图不重复人工批准；质检缺口仍须处理')
            if payload.get('phase')=='packaging':
                if not p.get('packaging') or p['packaging']['revision']!=p['revision']:
                    raise ValueError('没有可审核的当前包装版本')
                if payload.get('artifactJob')!=p['packaging'].get('job'):
                    raise ValueError('包装产物已变化或未指定，请重新查看后审核')
                if not attribute_plan.artifact_matches(p,p['packaging']):raise ValueError('包装使用的属性方案已变化，请重新制作')
                p.update(approvedPackaging=p['packaging']['job'],stage='VISUAL')
                flow=p.get('selectionFlow') or {}
                if (p['packaging'].get('executionSource')=='codex-native-imagegen' and flow.get('revision')==p['revision']
                        and flow.get('target')=='PACKAGING' and flow.get('status')=='STOPPED'):
                    flow.update(status='ACTIVE',target='VISUALS',imageProvider='codex-native',message='包装已审核，交接固定模板原生生图')
            elif payload.get('phase')=='visual':
                if not p.get('visual') or p['visual']['revision']!=p['revision']:
                    raise ValueError('没有可审核的当前图片版本')
                if p['visual'].get('needsRegeneration'):
                    raise ValueError('新品参数变化影响当前图片，请明确重新制作后再审核')
                if payload.get('artifactJob')!=p['visual'].get('job'):
                    raise ValueError('套图产物已变化或未指定，请重新查看后审核')
                if not attribute_plan.artifact_matches(p,p['visual']):raise ValueError('图片使用的属性方案已变化，请重新制作')
                unchecked=[i.get('slot') for i in p['visual'].get('images',[]) if i.get('specCheck')=='unchecked' or (i.get('quality') or {}).get('reviewRequired')]
                if unchecked:
                    if payload.get('specificationReviewed') is not True:raise ValueError('请明确核对规格待验模块：'+'、'.join(str(s) for s in unchecked))
                    p['visual']['specificationReview']={'slots':unchecked,'reviewedAt':store.now(),'job':p['visual']['job']}
                p.update(approvedVisual=p['visual']['job'],stage='VISUALS_READY' if (p.get('workflow') or {}).get('target')=='VISUALS' else 'LISTING')
                if p.get('recruitment') and any(r['kind']=='image' for r in topic_workflow.requirements(p['recruitment']['snapshot'])):
                    if payload.get('topicImageReviewed') is not True:
                        raise ValueError('请确认该版本首图符合征品主体相似要求')
                    p['recruitment']['entries']['image']={'actual':'主体相似','evidence':'人工审核图片版本 '+p['visual']['job'],'note':'图片审核后进入草稿，仍需平台检测'}
            elif payload.get('phase')=='draft':
                if not p.get('draft') or not p['draft'].get('readback_verified'):
                    raise ValueError('草稿尚未完成回读')
                if p.get('recruitment'):
                    raise ValueError('征品草稿尚需平台匹配检测及证书人工绑定，不能用普通草稿验收代替征品通过')
                p['stage']='COMPLETE'
            else:
                raise ValueError('无效审核阶段')
            p['events'].append({'time':store.now(),'message':'人工审核通过：'+payload['phase']})
            c.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(p,ensure_ascii=False),p['id']))
        if payload.get('phase') in ('packaging','visual'):
            if p.get('workflow'):
                production_flow.advance(p['id'])
            else:
                recruitment_chain.advance(p['id'])
                selection_jobs.advance(p['id'])
        return p
    if action=='todo.save':
        return store.update_todo(payload.get('id'),payload.get('changes') or {})
    if action=='todo.product':
        todo=next((t for t in store.records('todos') if t['id']==payload.get('id')),None)
        if not todo:
            raise ValueError('跟进事项不存在')
        title=str(payload.get('title') or '').strip()[:200]
        if not title:
            raise ValueError('请填写从客户需求提炼的产品名称')
        p=store.create_product('inquiry:'+todo['store']+':'+todo['id'],title)
        store.update_todo(todo['id'],{'product':p['id']})
        return p
    raise ValueError('不支持的工作台操作')

def worker():
    if not _worker_lock.acquire(blocking=False):
        return
    try:
        while not skill_jobs.executor_blocked() and (job:=store.claim()):
            try:
                if job['kind']=='inquiry':
                    import inquiry_jobs
                    # Share the same inter-process lock as Tuesday's automatic collector.
                    import os
                    weekly_update.STATE.mkdir(parents=True,exist_ok=True)
                    lock=weekly_update.STATE/'update.lock'
                    try:
                        fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY); os.close(fd)
                    except FileExistsError:
                        raise ValueError('定时更新或其他采集正在运行，请等待完成后重新提交')
                    try:
                        result=inquiry_jobs.run(job)
                    finally:
                        lock.unlink(missing_ok=True)
                else:
                    result=skill_jobs.run(job)
                store.job_update(job['id'],status='SUCCESS',progress='产物验证完成',result=result,finished=store.now())
            except Exception as error:
                # Raw subprocess errors and stderr stay private.
                message=str(error)[:240] if isinstance(error,(ValueError,weekly_update.SyncError)) else '执行或产物校验失败，原报告和既有产物保留；请检查运行环境'
                store.job_update(job['id'],status='NEEDS_ATTENTION',progress=message,finished=store.now())
                if job.get('workflowContinuation') and job.get('product'):
                    current=store.product(job['product'])
                    if (current.get('workflow') or {}).get('revision')==job.get('revision'):
                        production_flow.update(job['product'],status='NEEDS_ATTENTION',message=message)
                if job.get('recruitmentChain') and job.get('product'):
                    current=store.product(job['product'])
                    if (current.get('productionFlow') or {}).get('revision')==job.get('revision'):
                        recruitment_chain.update(job['product'],{'status':'NEEDS_ATTENTION','message':message})
                if job.get('product') and (job.get('selectionCandidate') or job.get('selectionContinuation')):
                    selection_jobs.failure(job['product'],job['revision'],message)
                continue
            # Output execution has already succeeded. Handoff errors cannot undo that fact.
            if job.get('product'):
                try:
                    if store.product(job['product']).get('workflow'):
                        production_flow.advance(job['product'])
                    else:
                        recruitment_chain.advance(job['product'])
                        selection_jobs.advance(job['product'])
                except Exception:
                    message='产物已验证完成；后续阶段交接失败，请核对主流程后恢复交接，勿重跑本任务'
                    store.job_update(job['id'],orchestrationError=True,progress=message)
                    if store.product(job['product']).get('workflow'):
                        production_flow.update(job['product'],status='NEEDS_ATTENTION',message=message)
    finally:
        _worker_lock.release()
        if not skill_jobs.executor_blocked() and any(j['status']=='QUEUED' for j in store.records('jobs')):
            kick()

def kick():
    threading.Thread(target=worker,daemon=True).start()

def artifact_file(job_id,relative):
    if not re.fullmatch(r'[a-f0-9]{32}',job_id):
        raise ValueError('无效任务编号')
    # Expose only image outputs explicitly registered to a product; logs/inputs stay private.
    allowed={row['file'] for p in store.records('products') for kind in ('packaging','hero','visual','visualPartial','visualPending') if (p.get(kind) or {}).get('job')==job_id for row in p[kind]['images']}
    if relative not in allowed:
        raise ValueError('未登记的产物')
    return skill_jobs.artifact(store.STATE/'runs'/job_id,relative)


def template_file(job_id,slot):
    if not re.fullmatch(r'[a-f0-9]{32}',job_id) or not re.fullmatch(r'm[12]|d[123]',slot):
        raise ValueError('无效模板对照')
    registered=any(row.get('slot')==slot for p in store.records('products') for kind in ('hero','visual','visualPartial','visualPending')
                   if (p.get(kind) or {}).get('job')==job_id for row in p[kind].get('images',[]))
    if not registered:raise ValueError('模板未关联实际产物')
    root=(store.STATE/'runs'/job_id).resolve()
    request=json.loads((root/'native-requests'/(slot+'.json')).read_text(encoding='utf-8'))
    scene=Path(request.get('scene','')).resolve()
    if not scene.is_relative_to(root) or not scene.is_file() or scene.suffix.lower() not in ('.png','.jpg','.jpeg','.webp'):
        raise ValueError('模板底图不在本次任务目录')
    from native_template_runner import image_hash
    if image_hash(scene)!=request.get('scenePixelHash'):
        raise ValueError('模板底图已变化，不能作为原版本对照')
    return scene
