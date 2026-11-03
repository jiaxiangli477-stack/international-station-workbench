"""Native executor contract: installed templates and real rendering receipts."""
import ast
import hashlib
import json
import re
import os
import subprocess
import sys
from pathlib import Path
import task_store as store
import visual_reference

REQUIRED_SKILL_SCRIPTS = ('build.py','render_v2.py','render.py','check_layout.py','check_facts.py','reference_sample.py')
REFERENCE_TEMPLATE_MARKERS = {'m2': ('{{REFERENCE_LABEL}}','{{REFERENCE_CSS}}'),
                             'd2': ('{{REFERENCE_LABEL}}',)}
REFERENCE_TEMPLATE_SHA256 = {
    'm2': '5b135798ad76ce2dd883625ef514f77121919687c888247892ce4cf583d416cb',
    'd2': '2ba57f422cf823fcece09c926b459064cf4b9f833177596f62d88ac7d1fac7c1',
}


def contract(skills):
    skill = skills / 'b2b-image-skill'
    tree = ast.parse((skill / 'scripts/build.py').read_text(encoding='utf-8-sig'))
    mappings = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'TEMPLATE_FILES' for t in n.targets))
    slots = [f'm{i}' for i in range(1, 7)] + ['d1','d2','d3','d4','df','d5','d6','dfac','d7','dc','drev','d9']
    for key, markers in REFERENCE_TEMPLATE_MARKERS.items():
        template_path = skill / 'assets/templates' / mappings[key]
        template = template_path.read_text(encoding='utf-8')
        template_hash = hashlib.sha256(template_path.read_bytes()).hexdigest()
        if template_hash != REFERENCE_TEMPLATE_SHA256[key] or any(marker not in template for marker in markers):
            raise ValueError(f'{key} does not match the reviewed competitor-reference template contract')
    return {'provider': 'codex-native', 'adapter': str(store.ROOT / 'native_template_runner.py'), 'skillRoot': str(skill),
            'templates': {key: {'file': mappings[key], 'sha256': hashlib.sha256((skill / 'assets/templates' / mappings[key]).read_bytes()).hexdigest()} for key in slots},
            'brandCssHash': hashlib.sha256((skill / 'assets/templates/_brand.css').read_bytes()).hexdigest(),
            'detailCssHash':hashlib.sha256((skill / 'assets/templates/_detail.css').read_bytes()).hexdigest(),
            'scriptHashes':{name:hashlib.sha256((skill/'scripts'/name).read_bytes()).hexdigest()
                            for name in REQUIRED_SKILL_SCRIPTS}}


def policy_matches_skill(skill, policy):
    skill=Path(skill)
    try:
        hashes = policy.get('scriptHashes', {})
        if not isinstance(hashes, dict) or not set(REQUIRED_SKILL_SCRIPTS).issubset(hashes):
            return False
        return (all(hashlib.sha256((skill/'assets/templates'/row['file']).read_bytes()).hexdigest()==row['sha256']
                    for row in policy['templates'].values())
                and hashlib.sha256((skill/'assets/templates/_brand.css').read_bytes()).hexdigest()==policy['brandCssHash']
                and hashlib.sha256((skill/'assets/templates/_detail.css').read_bytes()).hexdigest()==policy['detailCssHash']
                and all(hashlib.sha256((skill/'scripts'/name).read_bytes()).hexdigest()==digest
                        for name,digest in hashes.items()))
    except (OSError,KeyError,TypeError):
        return False


def instructions(root, kind):
    return f'''
用户明确改用GPT原生生图；本次imageProvider=codex-native，仅覆盖Skill旧的第三方生图通道锁，不改模板/模式/验收。
买家视觉质量要求：内部concept模式只用于记录事实状态，不能把Internal Packaging Concept、B2B Development Concept、REFERENCE或TO_CONFIRM印到包装或正式首图上当卖点。新品包装先明确目标买家、产品品类、使用场景和2—3个有来源的选择理由；配方/含量等未知时使用已采用的包装格式、携带与场景设计理由，不编造营养或功效。包装按产品定位独立选择材质、色彩及信息层级，不默认套Listing的蓝绿配色；原Listing模板及品牌样式仍照原合同保留。不能用三个同义格式词代替三个不同买家价值点；先做内部买家视角复核，再提交正式首图给用户确认。
必须使用当前真正可调用的 image_gen 原生工具；禁止调用gen_image.py访问DeepKey/TokenStation，禁止自写API或切换服务。
如果原生工具不可用，返回blocked具体原因，不运行旧通道。
packaging：已批准的具体设计在input.json的designReview；若status=APPROVED且revision与产品一致，不重复请求同一设计签字，直接按该设计用原生工具生成一张A0。保存原生工具实际产物，不能拿参考图充当输出。
visual：包装已经由用户审核。必须实际运行已安装Skill的build.py构建模板，保持现有模板源和_brand.css，不允许仅靠提示词自由画整张图。按模块准备product.json/detail.json，使用确认过的产品资料与Skill素材库；不能抄样例产品的配方、规格或未经核实的证书。
若input.json含referenceSamples，必须把referenceSamples.m2原样写入product.json.m2.sampleReference、referenceSamples.d2原样写入detail.json.d2.sampleReference。使用referenceAssetFiles中的d2_ing1..3素材填入d2.images对应槽位；这些是无品牌原料形态示意图。只按Skill的reference_fields输出固定标题、三条成分和可见COMPETITOR REFERENCE · NOT THIS PRODUCT标签，不得写入product.formula或属性。缺任一来源或标签时阻断该模块，不得按普通本品成分图继续。
input.json.visualBlockers记录当前同版本仍未解决的事实缺口，不能渲染或交付所列模块；按该表写入blocked-modules.json并继续其余模块。只有本品事实补齐且修订后才能解除，渲染成功不能解除事实缺口。
先用input.json.nativeTemplateContract.adapter替代render_v2.py入口（其余参数相同，额外--job-root {root}，加--keep）；这个适配器内部仍运行原render_v2，只把生图步骤接入原生缓存。
例如 python native_template_runner.py --job-root {root} product.json build -o images --modules m1 m2 --keep。
遇到“等待GPT原生工具”并生成native-requests/*.json时：读取请求中的scene/product，用view_image查看两张图，再调用原生image_gen编辑scene，只换入指定产品，保留底图品牌、版式及文字。不要根据文字重画整套模板。将实际生成文件复制到本任务native-images/。
然后 python native_template_runner.py --job-root {root} --register native-requests/m1.json native-images/m1.png；再运行同一模板渲染命令。缓存只有模板底图和产品像素哈希一致才接纳。
详情页d1/d2/d3按Skill默认的composite路径；需要透明件按该Skill默认流程准备。通用模块不调用AI。未经用户许可不切换主图的模式来躲避检查。保留文字、产品规格与布局检查，失败不得伪造通过或关闭闸门。
每个成功模块会写template-receipts/模块.json。完整18项全部有真实产物、模板与成功回执，才返回completed。
缺营养表的真实或有出处数据、素材或某个模块被阻断时，不编造数据。仍继续完成不依赖该缺口的模块，返回status=partial、reason=明确剩余问题、images=实际完成模块列表；不要丢掉已完成模板图片，不标记完整套图成功。
每个阶段可写progress.json（JSON，仅message字符串与completedModules数组）让工作台显示真实进度。禁止把计划数写成完成数。
原生图初始文件可由工具保存至其默认目录，随后复制到本任务目录。所有产品资料和配置改动仍仅限本任务产物；禁止修改Skill、系统凭据或他人数据。
Windows后台渲染桥：不要在模型沙箱里直接启动Chrome或运行渲染适配器。构建HTML后，在本任务render-requests/写一个唯一文件名的JSON，例如001.json，结构 {{"spec":"product.json","build":"build","modules":["m1","m2","m3","m5","m6"]}}。工作台后台只执行固定渲染命令，不接收任意命令。读取对应render-responses/001.json确认实际结果，再处理native-requests并使用原生工具生图。等待期间可继续整理其他模块；每次等待最多30秒。
注册原生产物仍可调用适配器的--register（这个步骤不启动Chrome），登记后再提交新的render-requests文件请求继续验收。详情页另用detail.json及其实际构建目录。不要重复构建已正确构建的HTML或重复生成已登记且哈希一致的原生图。
'''


def verify(root, images, policy):
    from PIL import Image
    from native_template_runner import image_hash, execution_binding, spec_dependency_hash
    from skill_jobs import artifact
    if not isinstance(policy.get('templates'),dict) or not policy['templates']:
        raise ValueError('当前产物缺少已保存的固定模板合同，不能核验为通过')
    binding = execution_binding(root)
    if policy.get('executionBinding') is not None and binding != policy['executionBinding']:
        raise ValueError('回执输入不属于当前执行任务，请重新核验')
    current = store.product(binding['product'])
    require_current_binding(current, binding)
    context = json.loads((root / 'input.json').read_text(encoding='utf-8-sig'))
    for row in images:
        key = row['slot']
        if key=='m1' and policy.get('heroReuse'):
            import hero_execution
            checked=hero_execution.verify_reuse(current,root,row,policy)
            row.clear();row.update(checked)
            continue
        if key not in policy['templates']:
            raise ValueError('未知模板模块')
        receipt_file = artifact(root, 'template-receipts/' + key + '.json')
        receipt = json.loads(receipt_file.read_text(encoding='utf-8'))
        if receipt.get('slot') != key or receipt.get('exitCode') != 0 or receipt.get('renderer') != 'installed_render_v2':
            raise ValueError('模块缺少固定模板成功回执：' + key)
        if receipt.get('binding') != binding:
            raise ValueError('模块回执缺少当前任务/产品/属性版本绑定，需重新核验：' + key)
        spec_check = receipt.get('specCheck')
        if spec_check not in ('ok', 'unchecked', ''):
            raise ValueError('模块规格校验失败或状态缺失：' + key)
        if artifact(root, receipt.get('file','')) != artifact(root, row['file']):
            raise ValueError('回执与图片不一致：' + key)
        if image_hash(artifact(root, row['file'])) != receipt.get('imagePixelHash'):
            raise ValueError('产物在验收后已变化：' + key)
        html = artifact(root, receipt.get('html',''))
        if hashlib.sha256(html.read_bytes()).hexdigest() != receipt.get('htmlHash'):
            raise ValueError('验收后模板HTML已变化：' + key)
        spec = artifact(root, receipt.get('spec',''))
        if (not receipt.get('specHash')
                or (receipt.get('specDependencyHash') is not None
                    and spec_dependency_hash(spec,key) != receipt['specDependencyHash'])
                or (receipt.get('specDependencyHash') is None
                    and hashlib.sha256(spec.read_bytes()).hexdigest() != receipt['specHash'])):
            raise ValueError('模块输入规格已变化或缺少原始摘要，需重新核验：' + key)
        visual_reference.require_render(context, policy, spec, html, key)
        from skill_jobs import SKILLS
        skill = Path(policy.get('skillRoot') or (SKILLS / 'b2b-image-skill'))
        template = skill / 'assets/templates' / policy['templates'][key]['file']
        if hashlib.sha256(template.read_bytes()).hexdigest() != policy['templates'][key]['sha256']:
            raise ValueError('执行期间Skill模板变化，请重新核对：' + key)
        built = html.read_text(encoding='utf-8')
        offset = 0
        for chunk in re.split(r'\{\{[A-Z0-9_]+\}\}', template.read_text(encoding='utf-8')):
            if not chunk:
                continue
            index = built.find(chunk, offset)
            if index < 0:
                raise ValueError('固定模板结构被改动：' + key)
            offset = index + len(chunk)
        css = artifact(root, str((html.parent / '_brand.css').relative_to(root)))
        if hashlib.sha256(css.read_bytes()).hexdigest() != policy['brandCssHash']:
            raise ValueError('品牌样式未沿用Skill：' + key)
        if not key.startswith('m') and policy.get('detailCssHash'):
            detail_css=artifact(root,str((html.parent/'_detail.css').relative_to(root)))
            if hashlib.sha256(detail_css.read_bytes()).hexdigest()!=policy['detailCssHash']:
                raise ValueError('详情页布局样式未沿用原Skill：'+key)
        for name,expected_hash in policy.get('scriptHashes',{}).items():
            if hashlib.sha256((skill/'scripts'/name).read_bytes()).hexdigest()!=expected_hash:
                raise ValueError('执行期间原Skill构建或检查脚本发生变化：'+name)
        with Image.open(artifact(root, row['file'])) as image:
            width, height = image.size
            if (key.startswith('m') and (width,height)!=(1000,1000)) or (not key.startswith('m') and (width!=750 or height<100)):
                raise ValueError('固定模板产物尺寸错误：' + key)
        row.update(specCheck=spec_check or 'not_applicable',
                   reviewRequirements=['specification'] if spec_check == 'unchecked' else [],
                   quality={'reviewRequired':spec_check == 'unchecked','specCheck':spec_check or 'not_applicable'},
                   attributePlanFingerprint=binding['attributePlanFingerprint'])
    return images


def require_current_binding(product, binding, job=None):
    import attribute_plan
    if (product['id'] != binding.get('product') or product['revision'] != binding.get('revision')
            or (job and (job['id'] != binding.get('job') or job['revision'] != binding.get('revision')))
            or not attribute_plan.artifact_matches(product, binding)):
        raise ValueError('资料或属性方案已变化，产物保留在原任务待重新核验')


def save_partial(product, job, root, result, policy):
    images = result.get('images') or []
    if not images:
        return
    if not isinstance(images,list) or len(images)>len(policy['templates']) or len({x.get('slot') for x in images})!=len(images):
        raise ValueError('部分模板产物清单无效')
    images = verify(root, images, policy)
    from native_template_runner import execution_binding
    binding = execution_binding(root)
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        p=json.loads(c.execute('SELECT data FROM products WHERE id=?',(product['id'],)).fetchone()['data'])
        require_current_binding(p, binding, job)
        prior=p.get('visualPartial') or {}
        blocked_file=root/'blocked-modules.json'
        blocked_hash=hashlib.sha256(blocked_file.read_bytes()).hexdigest() if blocked_file.is_file() else ''
        reason=str(result.get('reason',''))[:500]
        if (prior.get('job')==job['id'] and prior.get('images')==images and prior.get('reason')==reason
                and prior.get('blockedHash','')==blocked_hash):
            return
        p['visualPartial']={'job':job['id'],'revision':job['revision'],'images':images,
                            'templateCount':len(policy['templates']),'skillRoot':policy.get('skillRoot',''),
                            'attributePlanFingerprint':binding['attributePlanFingerprint'],
                            'executionSource':'codex-native-imagegen','complete':False,'reason':reason,'blockedHash':blocked_hash}
        blocked=root/'blocked-modules.json'
        if blocked.is_file():
            try:
                source=json.loads(blocked.read_text(encoding='utf-8-sig'))
                if isinstance(source,dict):
                    p['visualPartial']['blockedModules']=[{'slot':k,'reason':str(v)[:500]} for k,v in source.items() if k in policy['templates']]
            except (OSError,ValueError):pass
        p['events'].append({'time':store.now(),'message':'固定模板已完成'+str(len(images))+'/'+str(len(policy['templates']))+'，尚未完成全套，保留实际预览'})
        c.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(p,ensure_ascii=False),p['id']))
    store.job_update(job['id'],partialModules=[x['slot'] for x in images])


def publish_receipts(product,job,root,policy):
    if store.product(product['id'])['revision']!=job['revision']:
        return []
    images=[]
    for key in policy['templates']:
        path=root/'template-receipts'/(key+'.json')
        if not path.is_file():continue
        try:
            row=json.loads(path.read_text(encoding='utf-8'))
            image={'slot':key,'file':row['file'].replace('\\','/')}
            verify(root,[image],policy)
            images.append(image)
        except (OSError,ValueError,KeyError):
            continue  # Only finished, verified modules enter the gallery.
    if images and job.get('kind')!='hero':
        save_partial(product,job,root,{'images':images,'reason':'其余固定模板模块正在执行或待补资料'},policy)
    return images


def render_owner_alive(pid):
    """False means confirmed dead; None must never permit takeover."""
    try:
        if not isinstance(pid, int) or pid <= 0:
            return None
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return False if ctypes.get_last_error() == 87 else None
            try:
                code = wintypes.DWORD()
                if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return None
                return code.value == 259
            finally:
                kernel.CloseHandle(handle)
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except (OSError, ValueError, TypeError):
        return None


def acquire_render_lock(lock, response, request, product, job, root, policy):
    import uuid
    owner = {'pid':os.getpid(),'token':uuid.uuid4().hex,'job':job['id'],
             'phase':'claimed','startedAt':store.now() if hasattr(store,'now') else '',
             'requestHash':hashlib.sha256(request.read_bytes()).hexdigest()}
    try:
        with lock.open('x', encoding='utf-8') as stream:
            json.dump(owner, stream)
        return owner
    except FileExistsError:
        pass
    # Only one reconciler may examine/replace a stale lock at a time. A guard
    # left by a crash is deliberately conservative and needs manual recovery.
    guard = lock.with_suffix('.recovery')
    try:
        fd=os.open(guard,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    except FileExistsError:
        response.write_text(json.dumps({'status':'NEEDS_ATTENTION','recoveryRequired':True,
            'reason':'另一个恢复检查尚未确认结束，请核对执行者；未重复渲染'},ensure_ascii=False),encoding='utf-8')
        return None
    try:
        try:
            previous=json.loads(lock.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            previous={}
        alive=render_owner_alive(previous.get('pid'))
        if alive is True:
            return None
        reply={'status':'NEEDS_ATTENTION','recoveryRequired':True,
               'reason':'渲染锁拥有者或执行结果未能确认；未重复渲染，请先核对现有产物与执行进程'}
        if alive is False:
            data=json.loads(request.read_text(encoding='utf-8-sig'))
            modules=data.get('modules') or []
            done=publish_receipts(product,job,root,policy)
            completed={row['slot'] for row in done}
            if modules and set(modules)<=completed:
                reply={'status':'COMPLETED','completedModules':sorted(completed),'recovered':True}
            elif (previous.get('phase')=='claimed' and previous.get('job')==job['id']
                    and previous.get('requestHash')==owner['requestHash']):
                lock.unlink()
                with lock.open('x',encoding='utf-8') as stream:json.dump(owner,stream)
                return owner
        response.write_text(json.dumps(reply,ensure_ascii=False,indent=2),encoding='utf-8')
        return None
    finally:
        guard.unlink(missing_ok=True)


def release_render_lock(lock, owner):
    try:
        current=json.loads(lock.read_text(encoding='utf-8'))
        if current.get('token')==owner['token']:
            lock.unlink()
    except FileNotFoundError:
        pass


def process_render_requests(product,job,root,policy):
    requests=root/'render-requests';responses=root/'render-responses'
    if not requests.is_dir():return
    responses.mkdir(exist_ok=True)
    for marker in responses.glob('*.uncertain'):
        response=marker.with_suffix('.json')
        if not response.exists():
            response.write_text(json.dumps({'status':'NEEDS_ATTENTION','recoveryRequired':True,
                'reason':'上次渲染没有确认执行结果，请先核对原执行进程和已完成回执；未重新渲染'},ensure_ascii=False),encoding='utf-8')
    # A renamed request must not bypass an unresolved earlier render outcome.
    for prior_response in responses.glob('*.json'):
        prior=json.loads(prior_response.read_text(encoding='utf-8'))
        if prior.get('recoveryRequired'):
            prior_request=requests/prior_response.name
            data=json.loads(prior_request.read_text(encoding='utf-8-sig')) if prior_request.is_file() else {}
            modules=data.get('modules') or []
            completed={row['slot'] for row in publish_receipts(product,job,root,policy)}
            if modules and set(modules)<=completed:
                prior_response.write_text(json.dumps({'status':'COMPLETED','completedModules':sorted(completed),
                                                      'recovered':True}),encoding='utf-8')
                prior_response.with_suffix('.uncertain').unlink(missing_ok=True)
            else:
                return
    from skill_jobs import artifact
    for request in sorted(requests.glob('*.json')):
        response=responses/request.name
        if response.exists():continue
        lock=response.with_suffix('.lock')
        owner=acquire_render_lock(lock,response,request,product,job,root,policy)
        if owner is None:continue
        try:
            if store.product(product['id'])['revision']!=job['revision']:
                raise ValueError('资料版本已变化，停止渲染')
            data=json.loads(request.read_text(encoding='utf-8-sig'))
            modules=data.get('modules')
            if not isinstance(modules,list) or not 1<=len(modules)<=len(policy['templates']) or any(k not in policy['templates'] for k in modules):
                raise ValueError('模板模块清单无效')
            if job.get('kind')=='hero' and modules!=['m1']:
                raise ValueError('首图确认前只允许渲染m1')
            if policy.get('heroReuse') and 'm1' in modules:
                raise ValueError('已确认首图须原样复用，禁止再次渲染m1')
            spec=artifact(root,data.get('spec',''))
            build=(root/str(data.get('build',''))).resolve()
            if not build.is_relative_to(root.resolve()) or not build.is_dir():raise ValueError('构建目录无效')
            context=json.loads(artifact(root,'input.json').read_text(encoding='utf-8-sig'))
            for key in modules:
                if key=='m6':
                    html=artifact(root,str((build/(key+'.html')).relative_to(root)))
                    original=html.read_text(encoding='utf-8')
                    prepared=visual_reference.prepare_render(context,policy,
                        json.loads(spec.read_text(encoding='utf-8-sig')),original,key)
                    if prepared!=original:
                        html.write_text(prepared,encoding='utf-8')
                visual_reference.require_render(context,policy,spec,build/(key+'.html'),key)
            # Validate fixed template structure before launching the trusted renderer.
            from skill_jobs import SKILLS
            skill=Path(policy.get('skillRoot') or (SKILLS/'b2b-image-skill'))
            for key in modules:
                source=skill/'assets/templates'/policy['templates'][key]['file']
                if hashlib.sha256(source.read_bytes()).hexdigest()!=policy['templates'][key]['sha256']:raise ValueError('Skill模板已变化')
                html=artifact(root,str((build/(key+'.html')).relative_to(root))).read_text(encoding='utf-8')
                offset=0
                for chunk in re.split(r'\{\{[A-Z0-9_]+\}\}',source.read_text(encoding='utf-8')):
                    if not chunk:continue
                    i=html.find(chunk,offset)
                    if i<0:raise ValueError('构建HTML没有沿用固定模板：'+key)
                    offset=i+len(chunk)
            logs=root/'render-logs';logs.mkdir(exist_ok=True)
            # Persist before launching. If the service dies after this write,
            # ownership death alone does not prove its renderer also exited.
            owner['phase']='rendering'
            lock.write_text(json.dumps(owner),encoding='utf-8')
            uncertain_marker=lock.with_suffix('.uncertain')
            uncertain_marker.write_text(json.dumps(owner),encoding='utf-8')
            with (logs/request.name.replace('.json','.log')).open('wb') as log:
                executable=Path(sys.executable).with_name('python.exe') if os.name=='nt' else Path(sys.executable)
                cmd=[str(executable),str(store.ROOT/'native_template_runner.py'),'--job-root',str(root),str(spec),str(build),'-o',str(root/'images'),'--modules',*modules,'--keep']
                env=dict(os.environ,PYTHONIOENCODING='utf-8');env.pop('PYTHONUTF8',None)
                result=subprocess.run(cmd,stdout=log,stderr=log,timeout=600,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            # A normal wait return proves this invocation exited. If wait/IO
            # fails, retain a separate marker even if writing the reply fails.
            uncertain_marker.unlink(missing_ok=True)
            done=publish_receipts(product,job,root,policy)
            all_verified=set(modules)<={i['slot'] for i in done}
            reply={'status':'COMPLETED' if result.returncode==0 and all_verified else 'NEEDS_NATIVE_OR_ATTENTION','exitCode':result.returncode,
                   'completedModules':[i['slot'] for i in done],
                   'pendingSpecificationModules':[i['slot'] for i in done if i.get('specCheck')=='unchecked'],
                   'nativeRequests':[p.name for p in (root/'native-requests').glob('*.json')],
                   'log':'render-logs/'+request.name.replace('.json','.log')}
        except Exception as error:
            uncertain=owner.get('phase')=='rendering'
            reply={'status':'NEEDS_ATTENTION' if uncertain else 'REJECTED',
                   'recoveryRequired':uncertain,
                   'reason':str(error)[:220] if isinstance(error,ValueError) else '后台渲染失败，请检查私有日志'}
        try:
            response.write_text(json.dumps(reply,ensure_ascii=False,indent=2),encoding='utf-8')
        finally:
            release_render_lock(lock,owner)
        if reply.get('recoveryRequired'):
            return


def session(root):
    for path in sorted(root.glob('executor*.log'),key=lambda p:p.stat().st_mtime,reverse=True):
        with path.open(encoding='utf-8',errors='replace') as log:
            for _,line in zip(range(100),log):
                try:
                    row=json.loads(line)
                    if row.get('type')=='thread.started' and re.fullmatch(r'[a-f0-9-]{32,36}',str(row.get('thread_id',''))):
                        return row['thread_id']
                except ValueError:pass
    raise ValueError('没有可恢复的本次原生执行上下文')


def save_pending_images(product,job,root,policy=None):
    """Expose genuine generated images that failed a later check as pending only."""
    from native_template_runner import image_hash,inside,execution_binding
    import shutil
    binding = execution_binding(root)
    require_current_binding(store.product(product['id']), binding, job)
    images=[]
    for key in ('m1','m2'):
        cache=root/'native-cache'/(key+'.json')
        fit=root/'build/v2'/(key+'_fit.png')
        receipt=root/'template-receipts'/(key+'.json')
        if not cache.is_file() or not fit.is_file() or receipt.is_file():continue
        row=json.loads(cache.read_text(encoding='utf-8'))
        request=root/'native-requests'/(key+'.json')
        if not request.is_file():continue
        expected=json.loads(request.read_text(encoding='utf-8'))
        if row.get('binding') != binding or expected.get('binding') != binding:continue
        if any(row.get(k)!=expected.get(k) for k in ('slot','scenePixelHash','productPixelHash','subject')):continue
        if fit.stat().st_mtime<cache.stat().st_mtime:continue
        if image_hash(inside(root,row['image']))!=row.get('imagePixelHash'):continue
        target=root/'images-pending'/(key+'.png');target.parent.mkdir(exist_ok=True)
        shutil.copy2(fit,target)
        images.append({'slot':key,'file':target.relative_to(root).as_posix(),'review':'PENDING',
                       'specCheck':'unchecked','reviewRequirements':['specification'],
                       'quality':{'reviewRequired':True,'specCheck':'unchecked'},
                       'attributePlanFingerprint':binding['attributePlanFingerprint']})
    if images:
        with store.db() as c:
            c.execute('BEGIN IMMEDIATE')
            p=json.loads(c.execute('SELECT data FROM products WHERE id=?',(product['id'],)).fetchone()['data'])
            require_current_binding(p, binding, job)
            p['visualPending']={'job':job['id'],'revision':job['revision'],'images':images,'complete':False,
                                'templateCount':len((policy or {}).get('templates',{})) or 18,
                                'attributePlanFingerprint':binding['attributePlanFingerprint'],
                                'reason':'图片已由GPT原生工具生成；自动文案核验未完成，不能作为正式验收通过产物'}
            c.execute('UPDATE products SET data=? WHERE id=?',(json.dumps(p,ensure_ascii=False),p['id']))
    return images
