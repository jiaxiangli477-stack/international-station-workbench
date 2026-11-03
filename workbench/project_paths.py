"""Read-only source identity and external Skill discovery; never installs a Skill."""
import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
DEFAULT_SKILLS_ROOT = Path('D:/Codex/skills')
INSTALLED_SKILLS_ROOT = Path.home() / '.codex/skills'
ATTRIBUTE_FILES = ('SKILL.md', 'scripts/run_all.cjs', 'scripts/browser_runner.cjs',
                   'scripts/route_category.cjs', 'scripts/upload_images.cjs',
                   'scripts/content_preflight.cjs', 'assets/_profile.json',
                   'subskills/price-filler/scripts/price_calc.cjs')


def skills_root():
    """Primary root; use skill_root(name) when installed Skills span both roots."""
    configured = os.environ.get('WORKBENCH_SKILLS_ROOT', '').strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_SKILLS_ROOT if DEFAULT_SKILLS_ROOT.is_dir() else INSTALLED_SKILLS_ROOT


def skill_root(name):
    if not name or Path(name).name != name or name in ('.', '..'):
        raise ValueError('Skill name must be one directory name')
    override = {'alibaba-attribute-filler': 'WORKBENCH_ATTRIBUTE_SKILL_ROOT',
                'b2b-image-skill': 'WORKBENCH_B2B_SKILL_ROOT'}.get(name)
    configured = os.environ.get(override, '').strip() if override else ''
    if configured:
        return Path(configured).expanduser().resolve()
    root = skills_root() / name
    if os.environ.get('WORKBENCH_SKILLS_ROOT', '').strip() or root.is_dir():
        return root
    installed = INSTALLED_SKILLS_ROOT / name
    return installed if installed.is_dir() else root


def skill_preflight(name):
    root = skill_root(name)
    required = (ATTRIBUTE_FILES if name == 'alibaba-attribute-filler'
                else ('SKILL.md', 'scripts/reference_sample.py') if name == 'b2b-image-skill'
                else ('SKILL.md',))
    missing = [item for item in required if not (root / item).is_file()]
    if name == 'alibaba-attribute-filler' and not any((root / 'categories').glob('*/config.json')):
        missing.append('categories/*/config.json')
    version = 'unverified'
    note = 'File presence only; original Skill hash contract and review still required.'
    if name == 'b2b-image-skill':
        try:
            source = json.loads((root.parent / 'b2b-image-skill.source.json').read_text(encoding='utf-8-sig'))
            commit = str(source.get('commit', '')).lower()
            commit_date = str(source.get('commit_date', ''))
            entry_hash = hashlib.sha256((root / 'SKILL.md').read_bytes()).hexdigest()
            base_hash = str(source.get('skill_md_sha256', '')).lower()
            valid_source = (source.get('skill_root') == str(root.resolve())
                            and re.fullmatch(r'[0-9a-f]{40}', commit)
                            and re.fullmatch(r'\d{4}-\d{2}-\d{2}', commit_date)
                            and re.fullmatch(r'[0-9a-f]{64}', base_hash))
            extension = source.get('local_extension') if valid_source else None
            if valid_source and entry_hash == base_hash:
                version = f'{commit[:7]}@{commit_date}'
                note = 'Pinned GitHub commit and SKILL.md hash match; execution binds template and script hashes per task.'
            elif (valid_source and isinstance(extension, dict)
                  and re.fullmatch(r'[a-z0-9-]{1,40}', str(extension.get('name', '')))
                  and re.fullmatch(r'[0-9a-f]{64}', str(extension.get('skill_md_sha256', '')).lower())
                  and extension.get('skill_md_sha256', '').lower() == entry_hash):
                extension_name = extension['name']
                version = f'{commit[:7]}+{extension_name}@{commit_date}'
                note = ('Upstream commit is recorded as the base; local extension hash matches. '
                        'Execution binds template and script hashes per task.')
        except (OSError, ValueError, TypeError):
            pass
    return {'name': name, 'root': str(root), 'available': not missing,
            'missing': missing, 'version': version, 'note': note}


def build_fingerprint(root=ROOT):
    """Fingerprint executable source/UI only, never private runtime state."""
    digest = hashlib.sha256()
    for source in sorted(Path(root).iterdir()):
        if source.is_file() and source.suffix in ('.py', '.js', '.cjs', '.html', '.css'):
            digest.update(source.name.encode('utf-8'))
            digest.update(b'\0')
            digest.update(hashlib.sha256(source.read_bytes()).digest())
    return digest.hexdigest()


# Capture once at process import. Re-hashing on each request would incorrectly
# claim a running process loaded code edited after it started.
_RUNTIME_IDENTITY = {'root': str(ROOT), 'build': build_fingerprint()}


def runtime_identity():
    return dict(_RUNTIME_IDENTITY)
