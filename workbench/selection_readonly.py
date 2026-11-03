"""Full selection SPA for viewers: named GET routes only, no credential forwarding."""
import json
import re
from urllib.parse import urlsplit, parse_qs, urlencode
from urllib.request import urlopen

PREFIX='/selection-app'
SENSITIVE=re.compile(r'(^|[_-])(api[_-]?key|token|secret|password|cookie|credential|authorization)([_-]|$)',re.I)


def scrub(value):
    if isinstance(value,dict):
        return {k:scrub(v) for k,v in value.items() if not SENSITIVE.search(k) and not any(part in re.sub('[^a-z]','',k.lower()) for part in ('apikey','secret','password','cookie','credential','authorization','accesstoken','refreshtoken'))}
    if isinstance(value,list):return [scrub(v) for v in value]
    return value


def fetch(path):
    import selection_service
    payload,mime,status=selection_service.request(path)
    if status!=200:raise OSError('原选品接口未正常返回')
    return payload,mime


def resource(raw,role='viewer'):
    url=urlsplit(raw);path=url.path.removeprefix(PREFIX)
    if not url.path.startswith(PREFIX+'/') or '..' in path or '\\' in path or '%' in path:raise ValueError('不支持的选品资源')
    if path in ('/','/index.html'):
        payload,mime=fetch('/')
        html=payload.decode('utf-8').replace('/assets/',PREFIX+'/assets/')
        return html.encode('utf-8'),mime
    if re.fullmatch(r'/assets/[A-Za-z0-9_.-]+\.(js|css|woff2?|svg|png|jpe?g|webp)',path):
        payload,mime=fetch(path)
        if path.endswith(('.js','.css')):
            payload=payload.decode('utf-8').replace('/api/',PREFIX+'/api/').replace('/assets/',PREFIX+'/assets/').encode('utf-8')
        return payload,mime
    allowed=(path in ('/api/bootstrap','/api/datasets','/api/channel-data') or
             role=='owner' and path in ('/api/ai-engine','/api/health') or
             re.fullmatch(r'/api/datasets/[a-f0-9]{20}(?:/(?:voices|export))?',path) or
             re.fullmatch(r'/api/channel-data/[a-f0-9]{16}(?:/export)?',path) or
             re.fullmatch(r'/api/export/[a-f0-9]{16,32}',path))
    if not allowed:raise ValueError('共享选品仅允许读取已授权研究资料')
    query=parse_qs(url.query);safe={}
    if path=='/api/bootstrap' and query.get('run_id'):
        value=query['run_id'][0]
        if not re.fullmatch(r'[a-f0-9]{16,32}',value):raise ValueError('批次编号无效')
        safe['run_id']=value
    if path.endswith('/voices') and query.get('ids'):
        value=query['ids'][0]
        if len(value)>4000 or not re.fullmatch(r'[A-Za-z0-9_,-]*',value):raise ValueError('参考编号无效')
        safe['ids']=value
    payload,mime=fetch(path+('?'+urlencode(safe) if safe else ''))
    if 'json' in mime:
        data=scrub(json.loads(payload))
        if path=='/api/bootstrap' and role!='owner':
            data['sharing']={'enabled':True,'auth_required':False,'role':'viewer','url':None,
                             'permissions':{'research':False,'settings':False,'review':False,'view':True}}
        payload=json.dumps(data,ensure_ascii=False).encode('utf-8')
    return payload,mime
