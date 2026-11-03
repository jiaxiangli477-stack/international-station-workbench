"""Replace only render_v2's image-service step with verified native image outputs.

All other rendering, normalization and verification remain in the installed Skill.
Missing images produce reviewable requests; they never call a third-party fallback.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import os
import subprocess
from PIL import Image
from project_paths import skill_root

SCRIPTS = skill_root('b2b-image-skill') / 'scripts'
DEFAULT_TEMPLATES = {f'm{i}' for i in range(1,7)} | {'d1','d2','d3','d4','df','d5','d6','dfac','d7','dc','drev','d9'}


def execution_binding(root):
    """Read an explicit execution identity, never infer an old receipt's identity."""
    context = json.loads(inside(root, 'input.json').read_text(encoding='utf-8-sig'))
    binding = context.get('executionBinding')
    if (not isinstance(binding, dict) or not binding.get('job') or not binding.get('product')
            or binding.get('product') != context.get('id')
            or binding.get('revision') != context.get('revision')
            or 'attributePlanFingerprint' not in binding
            or binding['attributePlanFingerprint'] != (context.get('attributePlan') or {}).get('fingerprint', '')):
        raise ValueError('任务缺少当前输入身份绑定，请重新核验')
    return {key: binding[key] for key in ('job','product','revision','attributePlanFingerprint')}


def spec_dependency_hash(spec_file, key):
    """Shared product fields + this module; other modules may be filled later."""
    data=json.loads(spec_file.read_text(encoding='utf-8-sig'))
    templates=(data.get('nativeTemplateContract') or {}).get('templates')
    modules=set(templates) if isinstance(templates,dict) and templates else DEFAULT_TEMPLATES
    relevant={name:value for name,value in data.items() if name not in modules or name==key}
    assets={}
    def collect(value):
        if isinstance(value,dict):
            for item in value.values():collect(item)
        elif isinstance(value,list):
            for item in value:collect(item)
        elif isinstance(value,str) and Path(value).suffix.lower() in {'.png','.jpg','.jpeg','.webp','.gif','.svg'}:
            path=(spec_file.parent/value).resolve()
            assets[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else 'MISSING'
    collect(relevant)
    return hashlib.sha256(json.dumps({'spec':relevant,'assets':assets},sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def receipt_reusable(root, receipt, binding, dependency_hash, html, final, expected_slot):
    if not receipt.is_file() or not html.is_file() or not final.is_file():
        return False
    try:
        row = json.loads(receipt.read_text(encoding='utf-8'))
        return (row.get('slot') == expected_slot and row.get('binding') == binding and bool(row.get('specHash'))
                and row.get('specDependencyHash') == dependency_hash
                and row.get('renderer') == 'installed_render_v2' and row.get('exitCode') == 0
                and row.get('specCheck') in ('ok','unchecked','')
                and inside(root,row['html']) == html.resolve()
                and inside(root,row['file']) == final.resolve()
                and row.get('htmlHash') == hashlib.sha256(html.read_bytes()).hexdigest()
                and row.get('imagePixelHash') == image_hash(final))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def reusable_modules(root, binding, spec_file, build, output):
    """Return only current-contract receipts whose bound inputs and outputs still match."""
    try:
        data=json.loads(spec_file.read_text(encoding='utf-8-sig'))
        templates=(data.get('nativeTemplateContract') or {}).get('templates')
        modules=set(templates) if isinstance(templates,dict) and templates else DEFAULT_TEMPLATES
    except (OSError, ValueError, TypeError):
        return []
    completed=[]
    for key in sorted(modules):
        try:
            receipt=root/'template-receipts'/(key+'.json')
            html=build/(key+'.html')
            final=output/(key+'.png')
            dependency_hash=spec_dependency_hash(spec_file,key)
            if receipt_reusable(root,receipt,binding,dependency_hash,html,final,key):
                completed.append(key)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return completed


def image_hash(path):
    with Image.open(path) as im:
        im.load()
        return hashlib.sha256(str(im.size).encode() + im.convert('RGBA').tobytes()).hexdigest()


def inside(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('原生产物不在本次任务目录')
    return path


def register(request_file, image_file):
    request_file = Path(request_file).resolve()
    data = json.loads(request_file.read_text(encoding='utf-8'))
    root = request_file.parent.parent
    image = Path(image_file).resolve()
    if not image.is_relative_to(root) or not image.is_file():
        raise ValueError('先把GPT原生产物复制进本次任务目录，再登记')
    with Image.open(image) as im:
        im.verify()
    data.update(image=str(image.relative_to(root)), imagePixelHash=image_hash(image))
    target = root / 'native-cache' / request_file.name
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return target


def native_swap(command, out, root):
    if '--scene' not in command or '--product' not in command or '--element' in command:
        raise ValueError('原生模板适配器仅接单个产品场景替换；多元素需先补齐明确映射')
    scene = Path(command[command.index('--scene') + 1]).resolve()
    product = Path(command[command.index('--product') + 1]).resolve()
    destination = Path(command[command.index('-o') + 1]).resolve()
    if not destination.is_relative_to(root.resolve()):
        raise ValueError('输出必须在本次任务目录')
    key = destination.stem.split('_')[0]
    request = {'slot': key, 'scene': str(scene), 'product': str(product), 'subject': command[2],
               'scenePixelHash': image_hash(scene), 'productPixelHash': image_hash(product)}
    if (root/'input.json').is_file():
        request['binding']=execution_binding(root)
    requests = root / 'native-requests'; requests.mkdir(exist_ok=True)
    (requests / (key + '.json')).write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding='utf-8')
    cached = root / 'native-cache' / (key + '.json')
    if not cached.is_file():
        raise ValueError('等待GPT原生工具按固定底图换入产品：native-requests/' + key + '.json')
    row = json.loads(cached.read_text(encoding='utf-8'))
    if any(row.get(k) != request[k] for k in ('slot', 'scenePixelHash', 'productPixelHash', 'subject')):
        raise ValueError('模板底图或产品已变化，请重新生成该模块：' + key)
    if request.get('binding') and row.get('binding') != request['binding']:
        raise ValueError('原生缓存属性方案或任务已变化，请重新核验该模块：' + key)
    image = inside(root, row['image'])
    if image_hash(image) != row.get('imagePixelHash'):
        raise ValueError('登记后原生产物被改动：' + key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(image, destination)
    out.append('已接入GPT原生真实产物：' + key + '；继续原Skill尺寸归一与验收')


def main():
    # Background service uses pythonw. The renderer and Windows netstat need the
    # console interpreter's native locale; captured Skill output is decoded above.
    if os.name=='nt' and (Path(sys.executable).name.lower()=='pythonw.exe' or sys.flags.utf8_mode):
        python=Path(sys.executable).with_name('python.exe')
        env=dict(os.environ,PYTHONIOENCODING='utf-8');env.pop('PYTHONUTF8',None)
        raise SystemExit(subprocess.call([str(python),str(Path(__file__).resolve()),*sys.argv[1:]],env=env,
                                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
    parser = argparse.ArgumentParser()
    parser.add_argument('--job-root', required=True)
    parser.add_argument('--register', nargs=2, metavar=('REQUEST', 'IMAGE'))
    args, remaining = parser.parse_known_args()
    root = Path(args.job_root).resolve()
    if args.register:
        request = Path(args.register[0]).resolve()
        if request.parent != root / 'native-requests':
            raise ValueError('请求不属于本次任务')
        print(register(*args.register)); return
    # Snapshot before the renderer reads its input. Never stamp a completed image
    # with identity/spec values re-read after the render has run.
    binding = execution_binding(root)
    spec_file = inside(root, str(Path(remaining[0]).resolve().relative_to(root)))
    spec_hash = hashlib.sha256(spec_file.read_bytes()).hexdigest()
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location('installed_render_v2', SCRIPTS / 'render_v2.py')
    renderer = importlib.util.module_from_spec(spec); spec.loader.exec_module(renderer)
    # _compat emits UTF-8 on Windows while subprocess(text=True) may assume GBK.
    # Preserve all original commands/exit codes; make only decoding explicit.
    run_process = renderer.subprocess.run
    def utf8_process(*values, **options):
        from codex_copy_ocr import wrap_command
        command = values[0] if values else options.get('args')
        spec_check = (isinstance(command, (list, tuple)) and len(command) > 1
                      and Path(command[1]).name == 'check_product_spec.py')
        wrapped = wrap_command(command, SCRIPTS, root / ('spec-ocr' if spec_check else 'copy-ocr'))
        if wrapped is not command:
            if values:values = (wrapped, *values[1:])
            else:options['args'] = wrapped
        if options.get('text') or options.get('universal_newlines'):
            options.setdefault('encoding','utf-8');options.setdefault('errors','replace')
        return run_process(*values, **options)
    renderer.subprocess.run = utf8_process
    original = renderer._run
    def execute(command, out):
        if len(command) > 1 and Path(command[1]).name == 'gen_image.py':
            return native_swap(command, out, root)
        return original(command, out)
    renderer._run = execute
    process = renderer.process
    def process_module(*values, **options):
        key, _, _, json_dir, build, output = values[:6]
        receipts = root / 'template-receipts'; receipts.mkdir(exist_ok=True)
        receipt = receipts / (key + '.json')
        html = build / (key + '.html'); final = output / (key + '.png')
        dependency_hash=spec_dependency_hash(spec_file,key)
        if receipt_reusable(root, receipt, binding, dependency_hash, html, final, key):
            row = json.loads(receipt.read_text(encoding='utf-8'))
            return key, '复用输入、模板及图片哈希一致的已核验模块', True, False, False, '', [], row['specCheck'], ''
        html_hash = hashlib.sha256(html.read_bytes()).hexdigest()
        receipt.unlink(missing_ok=True)
        result = process(*values, **options)
        # Per-module success is independent of another module waiting for input.
        if result[2] and not any(result[i] for i in (3,4,5,6)) and result[7] != 'bad':
            if (execution_binding(root) != binding
                    or hashlib.sha256(spec_file.read_bytes()).hexdigest() != spec_hash
                    or spec_dependency_hash(spec_file,key) != dependency_hash
                    or hashlib.sha256(html.read_bytes()).hexdigest() != html_hash):
                raise ValueError('执行期间输入或模板已变化，产物保留但须重新核验：' + key)
            # The installed renderer exports detail modules at 2x. Keep that master,
            # then export the workbench's documented 750px delivery size.
            if not key.startswith('m'):
                with Image.open(final) as image:
                    image.load()
                    if image.width == 1500:
                        masters=root/'rendered-highres';masters.mkdir(exist_ok=True)
                        shutil.copy2(final,masters/final.name)
                        image.resize((750,image.height//2),Image.Resampling.LANCZOS).save(final)
            row = {'slot':key,'html':html.relative_to(root).as_posix(),
                   'htmlHash':hashlib.sha256(html.read_bytes()).hexdigest(),
                   'file':final.relative_to(root).as_posix(),'imagePixelHash':image_hash(final),
                   'spec':spec_file.relative_to(root).as_posix(),'specHash':spec_hash,
                   'specDependencyHash':dependency_hash,'binding':binding,
                   'renderer':'installed_render_v2','exitCode':0,'specCheck':result[7]}
            receipt.write_text(json.dumps(row),encoding='utf-8')
        completed = reusable_modules(root,binding,spec_file,build,output)
        template_count=len((json.loads(inside(root,'input.json').read_text(encoding='utf-8-sig')).get('nativeTemplateContract') or {}).get('templates') or {}) or 18
        progress={'message':'固定模板已完成 '+str(len(completed))+'/'+str(template_count)+'；其余模块继续执行或等待资料/原生图',
                  'completedModules':completed}
        import uuid
        temp=root/('progress-'+uuid.uuid4().hex+'.tmp')
        temp.write_text(json.dumps(progress,ensure_ascii=False),encoding='utf-8')
        try:
            temp.replace(root/'progress.json')
        except PermissionError:
            # Windows readers may briefly deny replace; progress must not fail rendering.
            temp.unlink(missing_ok=True)
        return result
    renderer.process = process_module
    # Original copy judgment runs with blind OCR; layout/spec checks remain unchanged.
    sys.argv = [str(SCRIPTS / 'render_v2.py'), *remaining]
    code = 0
    try:
        renderer.main()
    except SystemExit as error:
        code = error.code or 0
    raise SystemExit(code)


if __name__ == '__main__':
    main()
