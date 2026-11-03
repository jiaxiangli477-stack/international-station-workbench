"""Managed original selection application. No dependency on a separately started 8788."""
import atexit
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parent
ORIGINAL=Path(r'D:\Claude\product-selection-workspace-v2\opportunity-workbench')
RUNTIME=ROOT/'.state/runtime/selection'
_lock=threading.Lock()
_process=None
_port=None


def endpoint():
    global _process,_port
    with _lock:
        if _process is not None and _process.poll() is None and _port:
            return 'http://127.0.0.1:'+str(_port)
        if not (ORIGINAL/'server.py').is_file() or not (ORIGINAL/'dist/index.html').is_file():
            raise RuntimeError('原选品程序或前端构建不存在，未创建替代数据')
        RUNTIME.mkdir(parents=True,exist_ok=True)
        ready=RUNTIME/'ready.json'
        ready.unlink(missing_ok=True)
        python=Path(sys.executable)
        if python.name.lower()=='pythonw.exe':python=python.with_name('python.exe')
        env=dict(os.environ,PYTHONIOENCODING='utf-8')
        # Bind the canonical database, never a similarly named restored copy.
        env['WORKBENCH_DATA_DIR']=str(ORIGINAL/'data')
        with (RUNTIME/('host-'+str(os.getpid())+'.log')).open('ab') as log:
            _process=subprocess.Popen([str(python),str(ROOT/'selection_host.py'),'--root',str(ORIGINAL),'--ready',str(ready)],
                cwd=str(ORIGINAL),env=env,stdin=subprocess.PIPE,stdout=log,stderr=log,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            if _process.poll() is not None:break
            try:
                status=json.loads(ready.read_text(encoding='utf-8'))
                if status.get('pid')==_process.pid and status.get('parent')==os.getpid() and 0<int(status['port'])<65536:
                    _port=int(status['port'])
                    return 'http://127.0.0.1:'+str(_port)
            except (OSError,ValueError,KeyError):pass
            time.sleep(0.05)
        if _process.poll() is None:
            _process.stdin.close()
            try:_process.wait(timeout=2)
            except subprocess.TimeoutExpired:_process.terminate()
        raise RuntimeError('原选品程序未启动完成，请查看选品服务状态；研究数据未修改')


def write_allowed(path):
    if path in ('/api/selection','/api/runs','/api/enrich','/api/images/refresh','/api/profile',
                '/api/ai-engine','/api/ai-engine/test','/api/channel-data/collect','/api/datasets/import',
                '/api/datasets/research','/api/innovation/research'):
        return True
    return bool(re.fullmatch(r'/api/(?:runs/[a-f0-9]+/(?:resume|cancel|verify|analyze-api|continue-api-final)|'
        r'candidates/[a-f0-9]+-[0-9]+|channel-data/[a-f0-9]{16}/research|'
        r'datasets/[a-f0-9]{20}/(?:generate|hypotheses/[a-f0-9]{20}))',path))


def request(path,method='GET',body=None):
    url=urlsplit(path)
    if url.scheme or url.netloc or not path.startswith('/') or '..' in url.path or '\\' in path:
        raise ValueError('无效选品接口路径')
    if method not in ('GET','POST') or method=='POST' and not write_allowed(url.path):
        raise ValueError('未开放该选品操作')
    headers={'X-Workbench':'1','Content-Type':'application/json'} if method=='POST' else {}
    req=Request(endpoint()+path,data=body,headers=headers,method=method)
    try:
        with urlopen(req,timeout=30) as response:
            return response.read(),response.headers.get('Content-Type','application/octet-stream'),response.status
    except HTTPError as error:
        return error.read(),error.headers.get('Content-Type','application/json'),error.code


def bootstrap():
    raw,_,status=request('/api/bootstrap')
    if status!=200:raise RuntimeError('原选品资料暂时无法读取，未使用空候选替代')
    return json.loads(raw)


def close():
    global _process,_port
    with _lock:
        if _process is not None and _process.poll() is None and _process.stdin:
            _process.stdin.close()
        _process=None;_port=None


atexit.register(close)
