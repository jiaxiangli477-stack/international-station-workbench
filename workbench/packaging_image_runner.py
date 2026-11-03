"""Use the installed Skill; optional existing fallback requires explicit job choice."""
import sys
import json
import urllib.error
import re
from pathlib import Path
from project_paths import skill_root


def error_receipt(reason,http_status=None):
    """Persist categories only. SystemExit text may contain signed URLs or credentials."""
    record={'reason':reason,'retryAllowed':False,'recoveryRequired':reason=='GENERATED_DOWNLOAD_FAILED',
            'generated':reason=='GENERATED_DOWNLOAD_FAILED'}
    if http_status is not None:record['httpStatus']=http_status
    if '-o' in sys.argv:
        out=Path(sys.argv[sys.argv.index('-o')+1])
        (out.parent.parent/'image-error.json').write_text(json.dumps(record),encoding='utf-8')
    return record


def exit_category(error):
    raw=str(error.code)
    if '图已生成但下载失败' in raw or 'generated' in raw.lower() and 'download' in raw.lower():return 'GENERATED_DOWNLOAD_FAILED',None
    if '已被禁用' in raw or 'group disabled' in raw.lower():return 'GROUP_DISABLED',None
    if any(word in raw.lower() for word in ('insufficient_quota','insufficient balance','余额不足')):return 'INSUFFICIENT_QUOTA',None
    match=re.search(r'HTTP\s*(\d{3})',raw,re.I)
    status=int(match.group(1)) if match else None
    if status==429:return 'RATE_LIMITED',status
    if status in (500,502,503,504):return 'UPSTREAM_TEMPORARY',status
    if status==403:return 'HTTP_403',status
    return 'UNKNOWN',status


def main():
    provider = sys.argv.pop(1)
    scripts = skill_root('b2b-image-skill') / 'scripts'
    sys.path.insert(0, str(scripts))
    import gen_image
    if provider == 'tokenstation':
        values = gen_image.get_secret('TOKENSTATION_API_KEY', 'TOKENSTATION_BASE_URL')
        key = values.get('TOKENSTATION_API_KEY'); base = values.get('TOKENSTATION_BASE_URL')
        if not key or not base:
            raise SystemExit('Existing fallback credentials unavailable')
        # Both values belong to the same preconfigured group; no persistent config changes.
        gen_image._CREDS['image'] = (base.rstrip('/'), key, 'tokenstation')
        gen_image.os.environ.pop('GEN_IMAGE_MODEL', None)
    elif provider != 'configured':
        raise SystemExit('Unsupported image channel')
    try:
        gen_image.main()
    except urllib.error.HTTPError as error:
        # Retain only known failure categories, never raw provider bodies or credentials.
        raw = error.read(12000).decode('utf-8', errors='replace')
        reason = 'RATE_LIMITED' if error.code==429 else 'UPSTREAM_TEMPORARY' if error.code in (500,502,503,504) else 'HTTP_' + str(error.code)
        if '已被禁用' in raw or 'group disabled' in raw.lower():
            reason = 'GROUP_DISABLED'
        elif any(word in raw.lower() for word in ('insufficient_quota', 'insufficient balance', '余额不足')):
            reason = 'INSUFFICIENT_QUOTA'
        error_receipt(reason,error.code)
        raise SystemExit('Image service rejected request: ' + reason) from None
    except SystemExit as error:
        if error.code in (0,None):return
        reason,status=exit_category(error)
        error_receipt(reason,status)
        raise SystemExit('Image service did not complete: '+reason) from None


if __name__ == '__main__':
    main()
