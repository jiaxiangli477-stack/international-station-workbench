"""Blind image transcription for the installed copy checker, never its expected text."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True

from PIL import Image
from project_paths import skill_root

RUN_PROCESS = subprocess.run
PROMPT = ('Transcribe every visible text line in the attached image exactly as drawn. This is blind OCR, '
          'not proofreading. Do not infer, correct, invent or omit text. Preserve capitalization, punctuation, '
          'spelling and repeated occurrences. Include small packaging text and headers. '
          'Return only the required JSON object with a lines array. Do not use tools, read other files or '
          'perform web searches. The only content evidence is the attached image.')
SCHEMA = {'type': 'object', 'properties': {'lines': {'type': 'array', 'items': {'type': 'string'}}},
          'required': ['lines'], 'additionalProperties': False}


def wrap_command(command, scripts, cache_root):
    sources = {(Path(scripts) / name).resolve() for name in ('check_copy_ocr.py', 'check_product_spec.py')}
    if (not isinstance(command, (list, tuple)) or len(command) < 2
            or Path(command[1]).resolve() not in sources):
        return command
    source = Path(command[1]).resolve()
    return [command[0], str(Path(__file__).resolve()), '--source', str(source),
            '--cache-root', str(cache_root), *command[2:]]


def pixel_hash(path):
    with Image.open(path) as image:
        image.load()
        return hashlib.sha256(str(image.size).encode() + image.convert('RGBA').tobytes()).hexdigest()


def valid_lines(data):
    if (not isinstance(data, dict) or set(data) != {'lines'} or not isinstance(data['lines'], list)
            or not data['lines'] or len(data['lines']) > 2000
            or any(not isinstance(line, str) or not line.strip() or len(line) > 4000 for line in data['lines'])):
        raise ValueError('Blind OCR returned invalid transcription')
    return data['lines']


def transcribe(image, cache_root, run_process=RUN_PROCESS):
    image = Path(image).resolve()
    cache_root = Path(cache_root).resolve()
    digest = pixel_hash(image)
    policy = hashlib.sha256(PROMPT.encode()).hexdigest()
    cache_root.mkdir(parents=True, exist_ok=True)
    cache = cache_root / (digest + '.json')
    if cache.is_file():
        saved = json.loads(cache.read_text(encoding='utf-8'))
        if saved.get('pixelHash') == digest and saved.get('promptHash') == policy:
            return valid_lines({'lines': saved.get('lines')})
    executable = shutil.which('codex')
    if not executable:
        raise RuntimeError('Blind OCR executor unavailable')
    attempt = cache_root / ('attempt-' + uuid.uuid4().hex)
    attempt.mkdir()
    # This directory contains only OCR evidence; no HTML, expected copy or product input.
    schema = attempt / 'schema.json'
    schema.write_text(json.dumps(SCHEMA), encoding='utf-8')
    output = attempt / 'transcription.json'
    command = [executable, 'exec', '--ephemeral', '--skip-git-repo-check', '--sandbox', 'read-only',
               '--json', '-C', str(attempt), '--image', str(image), '--output-schema', str(schema),
               '--output-last-message', str(output), '-']
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', TMP=str(attempt), TEMP=str(attempt))
    log = attempt / 'events.jsonl'
    with log.open('wb') as stream:
        result = run_process(command, input=PROMPT.encode('utf-8'), stdout=stream, stderr=stream,
                             env=env, timeout=180, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('Blind OCR request failed; private evidence retained')
    # Tools would invalidate the image-only evidence contract, even if the JSON looked valid.
    for line in log.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get('item') or {}
        if item and item.get('type') != 'agent_message':
            raise RuntimeError('Blind OCR used a tool; transcription rejected')
        if event.get('type') in ('turn.failed', 'error'):
            raise RuntimeError('Blind OCR turn failed')
    lines = valid_lines(json.loads(output.read_text(encoding='utf-8-sig')))
    if pixel_hash(image) != digest:
        raise RuntimeError('Blind OCR image changed during transcription')
    saved = {'provider': 'codex-blind-vision', 'pixelHash': digest, 'promptHash': policy,
             'lines': lines, 'evidence': str(attempt.relative_to(cache_root)), 'confidenceAvailable': False}
    temporary = cache.with_suffix('.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
    temporary.replace(cache)
    return lines


def run_spec_checker(source, cache_root, remaining):
    spec = importlib.util.spec_from_file_location('installed_product_spec', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def blind_lines(image, box, scale, tmpdir, min_conf, dump=None):
        # Preserve the original source behavior (box=None) and finished-product crop.
        # Confidence is unavailable, so a positive/nonzero threshold cannot be met.
        if min_conf != 0:
            raise module.NotRun('Blind OCR confidence unavailable; only min_conf=0 is supported')
        try:
            with Image.open(image) as opened:
                cropped = opened.convert('RGB')
            if box:
                x, y, w, h = box
                x0, y0 = max(0, int(x)), max(0, int(y))
                x1, y1 = min(cropped.width, int(x + w)), min(cropped.height, int(y + h))
                if x1 - x0 < 8 or y1 - y0 < 8:
                    raise module.NotRun('Empty finished-product crop')
                cropped = cropped.crop((x0, y0, x1, y1))
            cropped = cropped.resize((cropped.width * scale, cropped.height * scale), Image.Resampling.LANCZOS)
            evidence = Path(cache_root) / 'spec-crops'
            evidence.mkdir(parents=True, exist_ok=True)
            output = evidence / (uuid.uuid4().hex + '.png')
            cropped.save(output)
            if dump:
                cropped.save(dump)
            digest = pixel_hash(output)
            metadata = dict(provider='codex-blind-vision', confidenceAvailable=False, pixelHash=digest,
                            scale=scale, box=list(box) if box else None, size=list(cropped.size))
            output.with_suffix('.json').write_text(json.dumps(metadata), encoding='utf-8')
            lines = valid_lines({'lines': transcribe(output, cache_root)})
            if pixel_hash(output) != digest:
                raise module.NotRun('Blind OCR crop changed during transcription')
            return lines
        except module.NotRun:
            raise
        except Exception:
            raise module.NotRun('Blind specification OCR unavailable; private evidence retained') from None

    module.ocr_lines = blind_lines
    previous = sys.argv
    sys.argv = [str(source), *remaining]
    try:
        module.main()
    finally:
        sys.argv = previous


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--cache-root', required=True)
    args, remaining = parser.parse_known_args(argv)
    source = Path(args.source).resolve()
    scripts = skill_root('b2b-image-skill') / 'scripts'
    expected = {(scripts / name).resolve() for name in ('check_copy_ocr.py', 'check_product_spec.py')}
    if source not in expected or not source.is_file():
        raise ValueError('Only the installed copy/spec OCR checkers may be wrapped')
    sys.path.insert(0, str(source.parent))
    if source.name == 'check_product_spec.py':
        return run_spec_checker(source, args.cache_root, remaining)
    import verify_label
    old = verify_label.ocr
    verify_label.ocr = lambda path, *unused, **options: [(text, None) for text in transcribe(path, args.cache_root)]
    previous = sys.argv
    sys.argv = [str(source), *remaining]
    try:
        runpy.run_path(str(source), run_name='__main__')
    finally:
        verify_label.ocr = old
        sys.argv = previous


if __name__ == '__main__':
    main()
