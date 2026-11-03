"""LAN view sessions. Loopback administration stays separate from colleague access."""
import base64
import hashlib
import hmac
from http.cookies import SimpleCookie
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import threading
import time

ROOT=Path(__file__).resolve().parent
STATE=ROOT/'.state'/'team'
LOCK=threading.Lock()

def private_ip():
    try:
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            sock.connect(('192.168.2.1',9))
            value=sock.getsockname()[0]
        if ipaddress.ip_address(value).is_private and not ipaddress.ip_address(value).is_loopback:
            return value
    except OSError:pass
    return '127.0.0.1'

class TeamGate:
    def __init__(self,enabled=False,state=None,ip=None,auth_required=True,viewer_networks=None):
        self.state=Path(state or STATE);self.enabled=enabled;self.ip=ip or private_ip();self.auth_required=auth_required
        self.state.mkdir(parents=True,exist_ok=True)
        path=self.state/'signing.key'
        if not path.exists():
            try:
                with path.open('xb') as file:file.write(secrets.token_bytes(32))
            except FileExistsError:pass
        self.key=path.read_bytes()
        self.subnet=ipaddress.ip_network(self.ip+'/24',strict=False)
        self.viewer_networks=[self.subnet]
        for value in viewer_networks or []:
            network=ipaddress.ip_network(value,strict=False)
            if (network.version!=4 or not any(network.subnet_of(office) for office in (
                    ipaddress.ip_network('10.0.0.0/8'),ipaddress.ip_network('172.16.0.0/12'),
                    ipaddress.ip_network('192.168.0.0/16')))
                    or network.is_loopback or network.is_link_local or network.is_multicast
                    or network.is_unspecified):
                raise ValueError('Viewer networks must be within private office IPv4 address ranges.')
            self.viewer_networks.append(network)
        self.hosts={'127.0.0.1','localhost'}|({self.ip,socket.gethostname().lower()} if enabled else set())
    def host_ok(self,host):return host.lower() in self.hosts
    def peer_ok(self,peer):
        try:
            address=ipaddress.ip_address(peer)
            return address.is_loopback or self.enabled and any(address in network for network in self.viewer_networks)
        except ValueError:return False
    def local_owner(self,peer,host):return peer in ('127.0.0.1','::1') and host=='127.0.0.1'
    def invite_config(self):
        try:return json.loads((self.state/'viewer.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):return {}
    def issue(self,port):
        if not self.enabled:raise ValueError('局域网查看尚未启用')
        if not self.auth_required:return {'url':f'http://{self.ip}:{port}/','role':'viewer','authRequired':False}
        code=secrets.token_urlsafe(24)
        with LOCK:
            old=self.invite_config()
            value={'hash':hashlib.sha256(code.encode()).hexdigest(),'generation':old.get('generation',0)+1,'expires':time.time()+7*86400}
            path=self.state/'viewer.json';tmp=path.with_suffix('.tmp')
            tmp.write_text(json.dumps(value),encoding='utf-8');tmp.replace(path)
        return {'url':f'http://{self.ip}:{port}/#invite={code}','expiresAt':value['expires'],'role':'viewer'}
    def login(self,code):
        value=self.invite_config()
        if not isinstance(code,str) or len(code)>150 or value.get('expires',0)<time.time() or not hmac.compare_digest(value.get('hash',''),hashlib.sha256(code.encode()).hexdigest()):
            raise ValueError('查看口令无效或已过期，请向管理员获取新分享链接')
        payload=base64.urlsafe_b64encode(json.dumps({'role':'viewer','generation':value['generation'],'exp':time.time()+8*3600,'nonce':secrets.token_hex(8)},separators=(',',':')).encode()).decode().rstrip('=')
        signature=hmac.new(self.key,payload.encode(),hashlib.sha256).hexdigest()
        return payload+'.'+signature
    def role(self,peer,host,cookie_header):
        if self.local_owner(peer,host):return 'owner'
        if peer in ('127.0.0.1','::1') and host=='localhost':return 'report'
        if not self.peer_ok(peer):return None
        if not self.enabled:return None
        if not self.auth_required:return 'viewer'
        try:
            cookies=SimpleCookie();cookies.load(cookie_header or '')
            token=cookies['jiaxiang_view_session'].value
            payload,signature=token.split('.',1)
            if not hmac.compare_digest(signature,hmac.new(self.key,payload.encode(),hashlib.sha256).hexdigest()):return None
            data=json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload)%4)))
            config=self.invite_config()
            if data['role']=='viewer' and data['exp']>time.time() and data['generation']==config.get('generation') and config.get('expires',0)>time.time():return 'viewer'
        except (ValueError,KeyError,TypeError,base64.binascii.Error):pass
        return None
    def status(self,role,port):
        return {'enabled':self.enabled,'role':role,'authRequired':self.auth_required,'permissions':{'view':role in ('owner','viewer'),'execute':role=='owner','share':role=='owner'},
                'url':f'http://{self.ip}:{port}/' if self.enabled else None,'message':'同事仅查看；采集、生图、上品和资料修改由本机管理员执行'}

def login_page():
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>嘉祥 · 团队查看</title><style>body{margin:0;background:#f3f6f2;color:#25483c;font:15px system-ui;display:grid;place-items:center;min-height:100vh}.card{background:white;padding:38px;border:1px solid #dbe5dd;border-radius:16px;width:min(380px,80vw)}small,p{color:#7c8d82;line-height:1.8}input,button{box-sizing:border-box;width:100%;padding:13px;border:1px solid #d3e1d6;border-radius:7px;margin-top:12px}button{background:#235e4d;color:white;cursor:pointer}#error{color:#a35132}</style><div class="card"><small>JIAXIANG OPERATIONS</small><h1>团队查看工作台</h1><p>使用管理员发来的完整查看链接，或输入查看口令。此入口只供查看报告和进度。</p><form id="login"><input id="code" type="password" autocomplete="off" aria-label="查看口令" placeholder="查看口令" required><button id="submit">进入工作台</button></form><p id="error" role="alert"></p></div><script>
const form=document.getElementById('login'),input=document.getElementById('code'),button=document.getElementById('submit');
async function enter(code){button.disabled=true;const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);try{const r=await fetch('/api/team/session',{method:'POST',headers:{'Content-Type':'application/json','X-Workbench':'1'},body:JSON.stringify({code}),signal:controller.signal});const data=await r.json();if(!r.ok)throw Error(data.error||'无法进入');location.replace('/#overview')}catch(e){document.getElementById('error').textContent=e.name==='AbortError'?'连接超时，请用系统浏览器打开完整查看链接，并确认连接同一办公室网络。':e.message;button.disabled=false}finally{clearTimeout(timer)}}
form.onsubmit=e=>{e.preventDefault();enter(input.value)};
if(location.hash.startsWith('#invite=')){let code=location.hash.slice(8);history.replaceState(null,'','/');enter(code)}
</script></html>'''

def readonly_selection():
    import selection_service
    from html import escape
    from urllib.parse import urlsplit
    data=selection_service.bootstrap()
    def safe(value):
        try:return value if urlsplit(str(value)).scheme in ('http','https') else ''
        except ValueError:return ''
    cards=[]
    for c in data.get('candidates',[]):
        refs=c.get('product_references') or []
        image=next((safe(r.get('image_url')) for r in refs if safe(r.get('image_url'))),'')
        links=' '.join('<a target="_blank" rel="noopener noreferrer" href="'+escape(safe(r.get('url')) or '#',quote=True)+'">'+escape(str(r.get('name') or '参考来源'))+'</a>' for r in refs)
        cards.append('<article>'+('<img referrerpolicy="no-referrer" src="'+escape(image,quote=True)+'">' if image else '')+'<h2>'+escape(str(c.get('title') or ''))+'</h2><p>'+escape(str(c.get('differentiation') or ''))+'</p><small>研究线索 · 待核验 · '+escape(str(c.get('gate') or ''))+'</small><p>'+links+'</p></article>')
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font:14px system-ui;color:#28483c;background:#f6f8f4;padding:22px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px}article{background:white;border:1px solid #dfe8df;padding:20px;border-radius:12px}img{width:100%;height:170px;object-fit:contain}h2{font-size:18px}p{line-height:1.8}small{color:#738575}a{color:#286450}</style><h1>选品研究 · 共享查看</h1><p>保留当前候选及来源。外部参考不代表我方产品事实；任务执行由管理员操作。</p><main>'+''.join(cards)+'</main></html>'
