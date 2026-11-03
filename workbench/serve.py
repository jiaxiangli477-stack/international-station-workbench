"""Local read-only UI server. Exposes only the named dashboard assets/reports."""
from __future__ import annotations

import argparse
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import io
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit, parse_qs, quote
import shared_scan
import threading
import time
import bridge_catalog
import bridge_reads
import weekly_update
import operations_api
import dashboard_manual
import socket
import os
import uuid
import team_share
from project_paths import runtime_identity
TEAM = team_share.TeamGate()

CATALOG_JOB = threading.Lock()
TOPIC_JOBS = {}
SERVER_INSTANCE_ID = uuid.uuid4().hex

class WorkspaceServer(ThreadingHTTPServer):
    allow_reuse_address = False
    def server_bind(self):
        if os.name == 'nt' and hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()


def open_server(address,handler,attempts=240):
    """Windows exclusive sockets can outlive a stopped process in TIME_WAIT."""
    for attempt in range(attempts):
        try:
            return WorkspaceServer(address,handler)
        except OSError as error:
            if getattr(error,'winerror',None)!=10048 or attempt==attempts-1:
                raise
            if attempt==0:print('Waiting for the previous exclusive port to close; access controls unchanged',flush=True)
            time.sleep(0.5)

ROOT = Path(__file__).resolve().parent
DASHBOARD_ROOTS = {
    "lifeworthcn": ("lifeworthcn", Path(r"D:\work\boards\lifeworthcn\engine\workspace\dashboard")),
    "yh": ("YH", Path(r"D:\work\boards\YH\engine\workspace\dashboard")),
    "original": ("原始工作区（店铺身份待核验）", Path(r"D:\work\alibaba-growth-os\workspace\dashboard")),
}
REPORT_ROOT = Path(r"D:\work\alibaba-growth-os-share\inquiry")
DASHBOARD_FILES = {"index.html", "styles.css", "app.js", "chart.umd.min.js", "dashboard_data.js"}
PUBLIC_FILES = {
    'dashboard_manual_host.js', 'dashboard-manual.html', 'cloud_team_ui.js',
    "index.html", "app.js", "styles.css", "workflow.js", "workflow.css",
    "operations.js", "operations.css", "integrations.js", "integrations.css",
    "首页预览.jpg", "产品串联预览.jpg", "数据面板预览.jpg", "询盘板块预览.jpg",
    "本地看板接入预览.jpg", "本地询盘接入预览.jpg", "share.js", "share.css", "共享盘接入预览.jpg",
    'bridge_tools.js', 'bridge_tools.css', '桥接工具中心预览.jpg', '征品主题预览.jpg',
    'recruitment_ui.js','recruitment_ui.css','完整征品页面预览.jpg',
    'selection_embed.js','selection_embed.css','选品工作台接入预览.jpg',
    'execution_ui.js','execution_ui.css','任务中心接入预览.jpg','询盘执行接入预览.jpg',
    'rectification_ui.js','rectification_ui.css','征品整改工作区预览.jpg',
    'recruitment_images.js','recruitment_hub.js','recruitment_hub.css','征品制作中心预览.jpg','征品匹配中心预览.jpg',
    'team_ui.js','team_ui.css','局域网分享预览.jpg','最新询盘台账预览.jpg',
    'inquiry_views.js',
    'production_ui.js','production_ui.css',
}


def latest_report() -> Path | None:
    if not REPORT_ROOT.is_dir():
        return None
    candidates = [p for p in REPORT_ROOT.iterdir()
                  if re.fullmatch(r"询盘客户背调分析_\d{8}\.html", p.name)
                  and p.is_file() and not p.is_symlink()]
    return max(candidates, key=lambda p: p.name, default=None)


def file_info(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {"available": False, "modified": None}
    stat = path.stat()
    return {"available": True,
            "modified": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
            "bytes": stat.st_size}


def registry() -> dict:
    dashboards = []
    for key, (label, folder) in DASHBOARD_ROOTS.items():
        complete = all((folder / name).is_file() for name in DASHBOARD_FILES)
        dashboards.append({"id": key, "label": label,
                           "url": f"/linked/{key}/index.html",
                           **file_info(folder / "index.html"),
                           "available": complete,
                           "dataModified": file_info(folder / "dashboard_data.js")["modified"]})
    report = latest_report()
    shared = shared_scan.public_index()
    shared['bindings'] = [{'id': key, 'label': cfg['label']} for key, cfg in weekly_update.STORES.items()]
    return {"runtime": runtime_identity(), "mode": "LOCAL_READ_ONLY", "dashboards": dashboards,
            "inquiry": {"label": "已有询盘背调报告", "url": "/linked/inquiry/report.html",
                        "fileName": report.name if report else None,
                        "storeIdentity": "lifeworthcn（用户确认；本机历史快照）",
                        **file_info(report)},
            "collectionEnabled": False, "sharingEnabled": TEAM.enabled,
            "shared": shared}


def resolve_public_path(raw_url: str) -> Path | None:
    path = unquote(urlsplit(raw_url).path)
    if "\\" in path or "\x00" in path or any(p in {".", ".."} for p in path.split("/")):
        return None
    if path == "/":
        return ROOT / "index.html"
    if path.startswith('/shared/'):
        parts = path.split('/', 3)
        return shared_scan.resolve_cached(parts[2], parts[3]) if len(parts) == 4 else None
    if path.startswith("/linked/"):
        parts = path.split("/")
        if len(parts) != 4:
            return None
        _, _, key, name = parts
        if key == "inquiry" and name == "report.html":
            return latest_report()
        if key in DASHBOARD_ROOTS and name in DASHBOARD_FILES:
            folder = DASHBOARD_ROOTS[key][1]
            target = folder / name
            if target.resolve().parent == folder.resolve() and not target.is_symlink():
                return target
        return None
    name = path.removeprefix("/")
    return ROOT / name if name in PUBLIC_FILES else None


def storage_namespace_script(key: str) -> str:
    prefix = json.dumps("jiaxiang-linked:" + key + ":")
    # Runs in the iframe's JS realm only. Parent workspace storage is untouched.
    return """<script>(function(){try{
      var p=%s,s=window.localStorage,P=Storage.prototype;
      var get=P.getItem,set=P.setItem,remove=P.removeItem,key=P.key;
      var length=Object.getOwnPropertyDescriptor(P,'length').get;
      function ownKeys(t){var a=[];for(var i=0;i<length.call(t);i++){
        var k=key.call(t,i);if(k&&k.indexOf(p)===0)a.push(k);}return a;}
      P.getItem=function(k){return get.call(this,this===s?p+String(k):k)};
      P.setItem=function(k,v){return set.call(this,this===s?p+String(k):k,v)};
      P.removeItem=function(k){return remove.call(this,this===s?p+String(k):k)};
      var clear=P.clear;P.clear=function(){if(this!==s)return clear.call(this);
        ownKeys(this).forEach(function(k){remove.call(s,k)})};
      P.key=function(i){return this===s?(ownKeys(this)[i]||'').slice(p.length)||null:key.call(this,i)};
      Object.defineProperty(P,'length',{get:function(){return this===s?ownKeys(this).length:length.call(this)}});
    }catch(e){}})();</script>""" % prefix


def viewer_storage_script():
    return '''<script>(function(){function mem(){var d={};return {get length(){return Object.keys(d).length},getItem:function(k){return Object.prototype.hasOwnProperty.call(d,k)?d[k]:null},setItem:function(k,v){d[k]=String(v)},removeItem:function(k){delete d[k]},clear:function(){d={}},key:function(i){return Object.keys(d)[i]||null}}}try{Object.defineProperty(window,'localStorage',{value:mem(),configurable:true});Object.defineProperty(window,'sessionStorage',{value:mem(),configurable:true})}catch(e){}})();</script>'''


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Do not log private report URLs or query strings.

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if unquote(urlsplit(self.path).path).startswith(('/shared/', '/linked/')):
            port = self.server.server_port
            policy = f'frame-ancestors http://127.0.0.1:{port} http://localhost:{port}'+(f' http://{TEAM.ip}:{port}' if TEAM.enabled else '')
            if self.access_role() == 'viewer':
                policy += '; sandbox allow-scripts allow-downloads allow-forms allow-popups'
            self.send_header('Content-Security-Policy', policy)
        else:
            self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def allowed_host(self):
        return TEAM.host_ok(self.headers.get('Host','').split(':')[0].lower()) and TEAM.peer_ok(self.client_address[0])

    def access_role(self):
        return TEAM.role(self.client_address[0],self.headers.get('Host','').split(':')[0].lower(),self.headers.get('Cookie'))

    def json_reply(self,data,status=200,headers=None):
        body=json.dumps(data,ensure_ascii=False).encode('utf-8')
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        for key,value in (headers or {}).items():self.send_header(key,value)
        self.end_headers()
        if self.command!='HEAD':self.wfile.write(body)

    def html_reply(self,html):
        body=html.encode('utf-8');self.send_response(200)
        self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        if self.command!='HEAD':self.wfile.write(body)

    def send_head(self):
        if not self.allowed_host():
            self.send_error(403, "Local access only")
            return None
        host = self.headers.get('Host', '').split(':')[0].lower()
        report_path = unquote(urlsplit(self.path).path).startswith(('/shared/', '/linked/'))
        # HTML and its supporting JS must both stay outside the owner origin.
        if host == '127.0.0.1' and report_path:
            self.send_response(302)
            self.send_header('Location', f'http://localhost:{self.server.server_port}' + self.path)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return None
        if host == 'localhost' and not report_path:
            self.send_error(403, 'Report origin only')
            return None
        api_path = urlsplit(self.path).path
        if api_path=='/api/team/status':
            self.json_reply(TEAM.status(self.access_role(),self.server.server_port));return None
        role=self.access_role()
        if role not in ('owner','viewer','report'):
            if api_path in ('/','/index.html'):
                self.html_reply(team_share.login_page())
            else:self.json_reply({'error':'需要管理员提供的查看链接'},401)
            return None
        if api_path=='/team/selection':
            try:self.html_reply(team_share.readonly_selection())
            except Exception:self.html_reply('<p>选品服务暂不可访问，请稍后重试。</p>')
            return None
        if api_path=='/api/cloud-team':
            if role!='owner':
                self.json_reply({'error':'本机管理员专用'},403);return None
            import cloud_team
            try:health=json.loads((cloud_team.STATE/'health.json').read_text(encoding='utf-8'))
            except (OSError,ValueError):health={}
            self.json_reply({'requests':cloud_team.rows(),'health':health});return None
        if api_path=='/api/dashboard/manual':
            params={k:v[0] for k,v in parse_qs(urlsplit(self.path).query).items()}
            params['action']='load'
            try:self.json_reply(dashboard_manual.command(params))
            except ValueError as error:self.json_reply({'error':str(error)},400)
            except (OSError,dashboard_manual.sqlite3.Error):self.json_reply({'error':'录入档案暂不可读，请保留本机备份'},503)
            return None
        if api_path.startswith('/selection-app/'):
            try:
                import selection_readonly
                payload,mime=selection_readonly.resource(self.path,role=role)
            except ValueError:
                self.json_reply({'error':'共享选品仅开放已授权只读页面'},403);return None
            except Exception:
                self.json_reply({'error':'内嵌选品程序暂未就绪，原资料保留，请重新载入'},503);return None
            self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(payload)))
            self.end_headers()
            if self.command!='HEAD':self.wfile.write(payload)
            return None
        if api_path=='/api/recruitment/matches':
            params=parse_qs(urlsplit(self.path).query)
            import recruitment_board
            data=recruitment_board.read(params.get('store',['youhealth'])[0],params.get('businessType',['HOT_PRODUCT'])[0],params.get('page',[1])[0],params.get('state',[''])[0],params.get('title',[''])[0][:150])
            body=json.dumps(data,ensure_ascii=False).encode('utf-8')
            self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(body)));self.end_headers()
            if self.command!='HEAD':self.wfile.write(body)
            return None
        if api_path == '/api/operations/selection':
            try:
                data=operations_api.selection_choices(); status=200
            except Exception:
                data={'candidates':[],'error':'选品服务暂不可访问，请运行打开工作台.cmd'}; status=503
            body=json.dumps(data,ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(body))); self.end_headers()
            if self.command!='HEAD': self.wfile.write(body)
            return None
        if api_path == '/api/operations':
            body = json.dumps(operations_api.overview(), ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            if self.command != 'HEAD': self.wfile.write(body)
            return None
        if api_path == '/api/product-quality':
            try:
                self.json_reply(operations_api.quality_reports())
            except Exception:
                self.json_reply({'error':'本地产品诊断结果暂不可读'},503)
            return None
        quality_parts = unquote(api_path).split('/')
        if len(quality_parts) == 6 and quality_parts[:4] == ['', 'api', 'product-quality', 'report']:
            try:
                self.json_reply(operations_api.quality_report(quality_parts[4], quality_parts[5]))
            except ValueError:
                self.json_reply({'error':'诊断报告不存在'},404)
            except Exception:
                self.json_reply({'error':'本地产品诊断报告暂不可读'},503)
            return None
        if api_path.startswith('/task-assets/') or api_path.startswith('/task-template-assets/'):
            try:
                parts=unquote(api_path).split('/',3)
                target=(operations_api.template_file if api_path.startswith('/task-template-assets/') else operations_api.artifact_file)(parts[2],parts[3])
                file=target.open('rb')
            except (ValueError, OSError, IndexError):
                self.send_error(404,'Artifact not found'); return None
            self.send_response(200)
            self.send_header('Content-Type',self.guess_type(str(target)))
            self.send_header('Content-Length',str(target.stat().st_size))
            self.end_headers()
            return file
        if api_path in ("/api/integrations", '/api/shared/status', '/api/bridge/catalog',
                        '/api/bridge/catalog/discovery-status', '/api/bridge/topics'):
            if api_path == '/api/bridge/catalog':
                data = bridge_catalog.read_catalog()
            elif api_path == '/api/bridge/catalog/discovery-status':
                params = parse_qs(urlsplit(self.path).query)
                job_id = params.get('jobId', [''])[0]
                data = bridge_catalog.read_discovery_status(job_id or None,server_id=SERVER_INSTANCE_ID)
            elif api_path == '/api/bridge/topics':
                params = parse_qs(urlsplit(self.path).query)
                store = params.get('store', ['youhealth'])[0]
                query = {k:params[k][0][:180] for k in ('businessType','page','tag','category','country','title','recent','sort') if k in params}
                data = bridge_reads.read_topics(store,query)
                if store in weekly_update.STORES and isinstance(data, dict):
                    data['refreshJob'] = bridge_reads.read_topic_refresh_status(store,server_id=SERVER_INSTANCE_ID)
            elif api_path == '/api/shared/status':
                data = {}
                for key, p in [('index', shared_scan.INDEX), ('weekly', shared_scan.STATE / 'weekly' / 'status.json'), ('progress', shared_scan.STATE / 'weekly' / 'progress.json')]:
                    try:
                        data[key] = p.stat().st_mtime_ns
                    except OSError:
                        data[key] = None
            else:
                data = registry()
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return None
        target = resolve_public_path(self.path)
        if target is None or not target.is_file():
            self.send_error(404, "Not found")
            return None
        try:
            file = target.open("rb")
        except OSError:
            self.send_error(404, "Not found")
            return None
        if urlsplit(self.path).path.startswith(("/linked/", '/shared/')) and target.suffix.lower() in (".html", '.htm'):
            key = urlsplit(self.path).path.split("/")[2]
            if urlsplit(self.path).path.startswith('/shared/'):
                record = next((r for r in shared_scan.read_index().get('records', []) if r['id'] == key), {})
                key = 'shared-' + record.get('store', key)
            source = file.read().decode("utf-8-sig")
            file.close()
            injection = viewer_storage_script() if role=='viewer' else storage_namespace_script(key)
            if "<head>" in source:
                source = source.replace("<head>", "<head>" + injection, 1)
            else:
                source = injection + source
            file = io.BytesIO(source.encode("utf-8"))
            size = len(file.getbuffer())
        else:
            size = target.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(str(target)))
        if target.suffix.lower()=='.xlsx':
            self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(target.name))
        self.send_header("Content-Length", str(size))
        self.end_headers()
        return file

    def do_POST(self):
        expected_origin = 'http://'+self.headers.get('Host','')
        if not self.allowed_host() or self.headers.get('Origin', expected_origin) != expected_origin:
            self.send_error(403, 'Local workspace only')
            return
        if urlsplit(self.path).path.startswith('/api/team/'):
            if self.headers.get('X-Workbench')!='1' or self.headers.get('Content-Type','').split(';')[0]!='application/json':
                self.json_reply({'error':'Explicit JSON request required'},403);return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=1024:raise ValueError('Invalid request')
                data=json.loads(self.rfile.read(length))
                if self.path=='/api/team/session':
                    if not TEAM.auth_required:self.json_reply({'role':'viewer','authRequired':False})
                    else:
                        token=TEAM.login(data.get('code'))
                        self.json_reply({'role':'viewer'},headers={'Set-Cookie':f'jiaxiang_view_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=28800'})
                elif self.path=='/api/team/logout':
                    self.json_reply({'ok':True},headers={'Set-Cookie':'jiaxiang_view_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0'})
                elif self.path=='/api/team/invite' and self.access_role()=='owner':
                    self.json_reply(TEAM.issue(self.server.server_port))
                else:self.json_reply({'error':'仅本机管理员可生成分享链接'},403)
            except (ValueError,AttributeError):self.json_reply({'error':'查看口令无效或请求格式不正确'},400)
            return
        if self.access_role()!='owner':
            self.json_reply({'error':'同事查看模式不能执行采集、生图、上品或修改资料'},403);return
        if self.path == '/api/product-quality/diagnose':
            if self.headers.get('X-Workbench') != '1' or self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                self.json_reply({'error':'Explicit workspace JSON request required'},403);return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 4096: raise ValueError('诊断请求大小无效')
                payload=json.loads(self.rfile.read(length))
                if not isinstance(payload,dict): raise ValueError('诊断请求格式无效')
                self.json_reply(operations_api.quality_diagnose(payload))
            except ValueError as error:
                self.json_reply({'error':str(error)[:240]},400)
            except Exception:
                self.json_reply({'error':'本地产品诊断未完成；未触发远程视觉服务'},503)
            return
        if self.path=='/api/dashboard/manual':
            if self.headers.get('X-Workbench')!='1' or self.headers.get('Content-Type','').split(';')[0]!='application/json':
                self.json_reply({'error':'Explicit workspace JSON request required'},403);return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=1048576:raise ValueError('录入请求大小无效')
                payload=json.loads(self.rfile.read(size))
                self.json_reply(dashboard_manual.command(payload))
            except dashboard_manual.Conflict as error:self.json_reply({'error':str(error),'current':error.current},409)
            except ValueError as error:self.json_reply({'error':str(error)},400)
            except (OSError,dashboard_manual.sqlite3.Error):self.json_reply({'error':'录入保存失败，保留本机数据并可导出备份'},503)
            return
        if urlsplit(self.path).path.startswith('/selection-app/api/'):
            import selection_service,selection_readonly
            route=urlsplit(self.path).path.removeprefix('/selection-app')
            if not selection_service.write_allowed(route):
                self.json_reply({'error':'未开放该选品操作'},403);return
            if self.headers.get('X-Workbench')!='1' or self.headers.get('Content-Type','').split(';')[0]!='application/json':
                self.json_reply({'error':'Explicit JSON request required'},403);return
            try:
                size=int(self.headers.get('Content-Length','0'))
                limit=12*1024*1024 if route=='/api/datasets/import' else 300000
                if not 0<size<=limit:raise ValueError('请求大小无效')
                raw=self.rfile.read(size)
                if not isinstance(json.loads(raw),dict):raise ValueError('请求必须为JSON对象')
                payload,mime,status=selection_service.request(route,method='POST',body=raw)
                if 'json' in mime:self.json_reply(selection_readonly.scrub(json.loads(payload)),status)
                else:self.json_reply({'error':'原选品接口未交回JSON结果'},502)
            except ValueError as error:self.json_reply({'error':str(error)[:180]},400)
            except Exception:self.json_reply({'error':'内嵌选品程序暂时无法处理，原资料保留'},503)
            return
        if self.path not in ('/api/operations', '/api/shared/scan', '/api/bridge/catalog/discover', '/api/bridge/topics/refresh'):
            self.send_error(501, 'Unsupported action')
            return
        try:
            length = int(self.headers.get('Content-Length', 0))
        except ValueError:
            self.send_error(400, 'Invalid request'); return
        if length < 0 or length > (32768 if self.path == '/api/operations' else 1024):
            self.send_error(413, 'Body too large')
            return
        raw = self.rfile.read(length)
        if self.path == '/api/operations':
            if self.headers.get('X-Workbench') != '1' or self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                self.send_error(403,'Explicit workspace JSON request required'); return
            try:
                payload=json.loads(raw)
                if not isinstance(payload,dict): raise ValueError('无效操作')
                result=operations_api.command(payload)
            except ValueError as error:
                result={'error':str(error)[:300]}; status=400
            except Exception:
                result={'error':'操作未成功，请检查服务或数据源连接；未公开原始错误'}; status=503
            else:
                status=200
                operations_api.kick()
            body=json.dumps(result,ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers(); self.wfile.write(body)
            return
        if self.path == '/api/bridge/catalog/discover':
            catalog_lock=CATALOG_JOB
            if catalog_lock.acquire(blocking=False):
                job_id = uuid.uuid4().hex
                def discover(current_job):
                    try:
                        result = bridge_catalog.discover()
                        bridge_catalog.record_discovery_status(
                            current_job, result.get('status', 'FAILED'), result.get('message', '接口发现已结束'),
                            tools=len(result.get('tools') or []), groups=len(result.get('groups') or []),
                            failedSchemas=result.get('failedSchemas') or [],server_id=SERVER_INSTANCE_ID)
                    except Exception as error:
                        failure_type=type(error).__name__
                        bridge_catalog.record_discovery_status(current_job, 'FAILED',
                            f'接口发现未完成，原目录保留（{failure_type}）',server_id=SERVER_INSTANCE_ID)
                    finally:
                        catalog_lock.release()
                try:
                    bridge_catalog.record_discovery_status(job_id, 'RUNNING', '正在读取接口目录与 schema',server_id=SERVER_INSTANCE_ID)
                    threading.Thread(target=discover, args=(job_id,), daemon=True).start()
                except Exception:
                    try:
                        bridge_catalog.record_discovery_status(job_id, 'FAILED', '接口发现未能启动，原目录保留',server_id=SERVER_INSTANCE_ID)
                    finally:
                        catalog_lock.release()
                    self.json_reply({'jobId':job_id,'status':'FAILED','message':'接口发现未能启动，原目录保留'},503);return
                reply = bridge_catalog.read_discovery_status(job_id,server_id=SERVER_INSTANCE_ID)
            else:
                reply = bridge_catalog.read_discovery_status(server_id=SERVER_INSTANCE_ID)
                reply.setdefault('message', '接口发现任务正在执行')
            body = json.dumps(reply, ensure_ascii=False).encode('utf-8')
            self.send_response(202)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
            return
        elif self.path == '/api/bridge/topics/refresh':
            try:
                store = json.loads(raw).get('store')
            except (ValueError, AttributeError):
                self.send_error(400, 'Invalid store'); return
            if store not in weekly_update.STORES:
                self.send_error(400, 'Store not bound'); return
            lock = TOPIC_JOBS.setdefault(store, threading.Lock())
            import recruitment
            if recruitment.status(store).get('status') == 'RUNNING' or not lock.acquire(blocking=False):
                self.json_reply({'status':'ALREADY_RUNNING','message':'此店铺已有主题采集任务，本次未启动新任务'},409);return
            job_id = uuid.uuid4().hex
            try:
                bridge_reads.write_topic_refresh_status(store,job_id,'RUNNING','正在只读查询当前店铺主题',server_id=SERVER_INSTANCE_ID)
            except Exception:
                lock.release()
                self.json_reply({'status':'FAILED','message':'主题任务状态无法保存，未启动查询'},503);return
            def topics():
                try:
                    result = bridge_reads.refresh_topics(store)
                    status = result.get('status') if isinstance(result,dict) else None
                    if status == 'RUNNING':
                        final_status='ALREADY_RUNNING';message=result.get('message','已有采集任务，本次未重复启动')
                    elif status in ('SUCCESS','FAILED'):
                        final_status=status;message=result.get('message','主题采集已结束')
                    else:
                        final_status='FAILED';message='主题采集未返回有效状态，旧缓存保留'
                except Exception:
                    final_status='FAILED';message='主题采集未完成，旧缓存保留'
                    try:
                        previous = recruitment.status(store)
                        previous.update(status='FAILED',message=message,finished=shared_scan.now())
                        recruitment.common.atomic_json(recruitment.STATE/store/'status.json',previous)
                    except Exception:
                        pass
                try:
                    bridge_reads.write_topic_refresh_status(store,job_id,final_status,message,server_id=SERVER_INSTANCE_ID)
                finally:
                    lock.release()
            try:
                threading.Thread(target=topics, daemon=True).start()
            except Exception:
                bridge_reads.write_topic_refresh_status(store,job_id,'FAILED','主题查询启动失败，未覆盖旧缓存',server_id=SERVER_INSTANCE_ID)
                lock.release()
                self.json_reply({'status':'FAILED','message':'主题查询未能启动，旧缓存保留'},503);return
            body = json.dumps({'jobId':job_id,'status':'RUNNING','message':'主题只读查询已启动'},ensure_ascii=False).encode('utf-8')
            self.send_response(202)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)
            return
        else:
            state = shared_scan.read_index()
            if state.get('status') != 'SCANNING':
                threading.Thread(target=shared_scan.scan, daemon=True).start()
        body = json.dumps({'status': 'PROCESSING', 'message': '请求已接收，正在处理'}, ensure_ascii=False).encode()
        self.send_response(202)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8796)
    parser.add_argument('--share',action='store_true',help='Enable authenticated LAN viewing')
    args = parser.parse_args()
    try:network=json.loads((team_share.STATE/'network.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):network={}
    enabled=args.share or network.get('enabled') is True
    TEAM=team_share.TeamGate(enabled=enabled,auth_required=network.get('auth_required',False) is True,
                             viewer_networks=network.get('viewer_networks',[]))
    if args.share:shared_scan.atomic_json(team_share.STATE/'network.json',{**network,'enabled':True,'mode':'viewer_only','auth_required':TEAM.auth_required})
    server = open_server(("0.0.0.0" if enabled else "127.0.0.1", args.port), partial(Handler, directory=str(ROOT)))
    # Reconcile lost execution before resuming authorized queued stages; never blind-retry RUNNING.
    import production_flow
    production_flow.reconcile()
    operations_api.kick()
    import cloud_team
    cloud_team.start()
    import listing_publication
    listing_publication.start_polling()
    print(f"Workspace admin: http://127.0.0.1:{server.server_port}/"+(f" ; LAN viewing: http://{TEAM.ip}:{server.server_port}/" if TEAM.enabled else ''),flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
