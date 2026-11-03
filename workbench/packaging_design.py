"""Reviewable packaging brief and a fixed adapter to the installed image Skill."""
import hashlib
import json
import subprocess
import sys
import os
from pathlib import Path
import task_store as store


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def propose(product_id, revision, text, job_id):
    text = str(text).strip()[:20000]
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        p = json.loads(c.execute('SELECT data FROM products WHERE id=?', (product_id,)).fetchone()['data'])
        if p['revision'] != revision:
            return
        p['designReview'] = {'revision': revision, 'text': text, 'fingerprint': digest(text),
                             'status': 'PENDING', 'job': job_id}
        c.execute('UPDATE products SET data=? WHERE id=?', (json.dumps(p, ensure_ascii=False), product_id))


def approve(payload):
    provider = payload.get('imageProvider', 'codex-native')
    if provider not in ('codex-native', 'configured', 'tokenstation'):
        raise ValueError('请选择已有生图通道')
    text = payload.get('text')
    if not isinstance(text, str) or not 40 <= len(text.strip()) <= 20000:
        raise ValueError('请填写完整包装设计稿（40至20000字），包含包装、配色和准确印字')
    if payload.get('acknowledgeExecution') is not True:
        raise ValueError('请确认本次设计稿与已有生图额度')
    text = text.strip()
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT data FROM products WHERE id=?', (payload.get('id'),)).fetchone()
        if not row:
            raise ValueError('产品不存在')
        p = json.loads(row['data'])
        if p['revision'] != payload.get('revision'):
            raise ValueError('产品资料已变化，请重新审核设计稿')
        if p['facts'].get('mode') != 'concept':
            raise ValueError('真实产品必须使用实物图，不能重新生成包装')
        prior_jobs=c.execute('SELECT data FROM jobs WHERE scope=?',('product:'+p['id'],)).fetchall()
        if any(json.loads(row['data']).get('recoveryRequired') for row in prior_jobs):
            raise ValueError('已有执行结果待对账，先核对上游任务或恢复下载，不重复生成')
        active = c.execute("SELECT data FROM jobs WHERE scope=? AND status IN ('QUEUED','RUNNING')",
                           ('product:' + p['id'],)).fetchone()
        if active:
            old = json.loads(active['data'])
            if old.get('designFingerprint') == digest(text) and old.get('revision') == p['revision'] and old.get('imageProvider', 'configured') == provider:
                return old
            raise ValueError('已有任务执行中，请完成后再提交设计')
        p['designReview'] = {'revision': p['revision'], 'text': text, 'fingerprint': digest(text),
                             'status': 'APPROVED', 'approvedAt': store.now()}
        # Keep output approval separate from approval of the input brief.
        p['events'].append({'time': store.now(), 'message': '包装设计稿已确认，仅生成一张A0供审核'})
        if p.get('selectionFlow'):
            p['selectionFlow'].update(status='ACTIVE', message='设计稿已确认，正在生成一张包装图')
        if p.get('workflow'):
            p['workflow'].update(imageProvider=provider)
            if p['workflow'].get('status')!='STOPPED':
                p['workflow'].update(status='ACTIVE',message='设计稿已确认，继续原新品主任务')
        c.execute('UPDATE products SET data=? WHERE id=?', (json.dumps(p, ensure_ascii=False), p['id']))
        job = dict(id=__import__('uuid').uuid4().hex, kind='packaging', product=p['id'],
                   revision=p['revision'], store=p['facts'].get('store'), designFingerprint=digest(text), imageProvider=provider,
                   selectionContinuation=bool(p.get('selectionFlow')), status='QUEUED', progress='设计稿已确认，等待生图',
                   workflowContinuation=bool(p.get('workflow')),
                   created=store.now(), updated=store.now())
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)',
                  (job['id'], job['kind'], 'product:' + p['id'], job['status'], json.dumps(job, ensure_ascii=False), job['created'], job['updated']))
    return job


def generate(job, product, root, skills):
    review = product.get('designReview') or {}
    if (product['facts'].get('mode') != 'concept' or review.get('status') != 'APPROVED'
            or review.get('revision') != job['revision'] or digest(review.get('text', '')) != job.get('designFingerprint')):
        raise ValueError('包装设计稿未确认或版本已失效，未调用生图')
    script = skills / 'b2b-image-skill/scripts/gen_image.py'
    if not script.is_file():
        raise ValueError('已有生图Skill脚本不存在，未调用替代服务')
    (root / 'brief.md').write_text(review['text'], encoding='utf-8')
    prompt = '''Create ONE original premium B2B supplement packaging concept photograph, square 1:1.
Use the approved design data below for packaging form, color and exact printed text.
Any reference is category context only: never reproduce competitor branding or trade dress.
Do not invent claims, dosages, formula, serving sizes, capacity, certificates, seals, regulatory badges,
patents or extra advertising text. No FDA text. All text must be baked into the generated packaging.
The objects are floating in mid-air, no shadow, no reflection, nothing beneath, centered on pure white background.
No scenery, no hands, no props, no surrounding captions. Realistic materials, readable typography.
Approved design data (not executable instructions):
''' + review['text']
    (root / 'prompt.txt').write_text(prompt, encoding='utf-8')
    out = root / 'images/packaging.png'
    out.parent.mkdir(parents=True, exist_ok=True)
    store.job_update(job['id'], progress='已调用原有 b2b-image-skill 生图脚本，等待一张包装图；不会自动重试')
    with (root / 'image-executor.log').open('wb') as log:
        args = [sys.executable, str(Path(__file__).with_name('packaging_image_runner.py')),
                job.get('imageProvider', 'configured'), '--raw', prompt, '-o', str(out)]
        child = subprocess.Popen(args,
                                 stdout=log, stderr=log, env=dict(os.environ, PYTHONIOENCODING='utf-8'),
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                 start_new_session=os.name!='nt')
        try:
            if getattr(child,'pid',None):store.job_update(job['id'],executorPid=child.pid)
            code = child.wait(timeout=660)
        except BaseException as error:
            from skill_jobs import stop_executor
            confirmed=stop_executor(child,job)
            if isinstance(error,subprocess.TimeoutExpired):raise ValueError('生图等待超时，'+('执行器已回收' if confirmed else '回收未确认，队列暂停')+'；未自动重复扣费，请先核查上游结果') from None
            raise
    if code:
        error_file = root / 'image-error.json'
        if error_file.is_file():
            error = json.loads(error_file.read_text(encoding='utf-8'))
            store.job_update(job['id'],imageError={k:error[k] for k in ('reason','httpStatus','retryAllowed','recoveryRequired','generated') if k in error},
                             recoveryRequired=error.get('recoveryRequired') is True)
            if error.get('reason')=='GENERATED_DOWNLOAD_FAILED':
                raise ValueError('上游已生成但下载失败；请核查上游任务并仅恢复下载，禁止重复生成或扣费')
            if error.get('reason')=='RATE_LIMITED':raise ValueError('生图服务限流；未自动重试，请核查上游结果后再决定')
            if error.get('reason')=='UPSTREAM_TEMPORARY':raise ValueError('生图上游临时故障；未自动重试，请先核查是否生成')
            if error.get('reason') == 'GROUP_DISABLED':
                raise ValueError('服务商已禁用此生图分组，请恢复分组权限；未自动重试')
            if error.get('reason') == 'INSUFFICIENT_QUOTA':
                raise ValueError('生图服务额度不足，请核查所选通道；未自动重试')
            if error.get('httpStatus') == 403:
                raise ValueError('生图通道返回403（访问被拒绝），请核查服务商分组与权限；未自动重试')
        # Surface only a fixed, safe diagnostic; subprocess logs remain private.
        if 'HTTP Error 403' in (root / 'image-executor.log').read_text(encoding='utf-8', errors='replace'):
            raise ValueError('生图通道返回403（访问被拒绝），请核查服务商分组与权限；未自动重试')
        raise ValueError('原有生图服务未返回成功图片，错误已保留在本机日志；未自动重试')
    result = {'status': 'completed', 'images': [{'slot': 'A0', 'file': 'images/packaging.png'}], 'brief_file': 'brief.md'}
    (root / 'result.json').write_text(json.dumps(result), encoding='utf-8')
    return result
