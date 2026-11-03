"""Original Skill browser transport and explicit local launch; never copies login state."""
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

import task_store as store

PORT = 9322  # Original Windows colleague Skill port.


def ready():
    try:
        with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{PORT}/json/version', timeout=2) as response:
            info = json.loads(response.read(65536))
        endpoint = urlsplit(info.get('webSocketDebuggerUrl', ''))
        return (any(name in str(info.get('Browser', '')).lower() for name in ('chrome/', 'edg/'))
                and endpoint.scheme == 'ws' and endpoint.hostname in ('127.0.0.1', 'localhost', '::1')
                and endpoint.port == PORT and not endpoint.username and not endpoint.password)
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def require_ready():
    if not ready():
        raise ValueError('原上品Skill浏览器尚未连接：请在工作台点击“打开上品浏览器”，在该窗口准备目标店铺后继续；未开始上传或保存草稿')
    try:
        with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{PORT}/json/list', timeout=2) as response:
            tabs = json.loads(response.read(262144))
        backend = any(urlsplit(str(tab.get('url', ''))).hostname in ('post.alibaba.com', 'i.alibaba.com')
                      and 'login' not in urlsplit(str(tab.get('url', ''))).path.lower()
                      for tab in tabs if isinstance(tab, dict) and tab.get('type') == 'page') if isinstance(tabs, list) else False
    except (OSError, ValueError, TypeError, AttributeError):
        backend = False
    if not backend:
        raise ValueError('原上品Skill浏览器尚未打开目标店铺后台：请在该窗口完成登录并打开阿里后台后继续；未开始上传或保存草稿')
    # A backend tab is readiness only. listing_runner still verifies the actual account before every write.


def status():
    """Probe the dedicated transport only; never reports authenticated shop identity."""
    state={'status':'DISCONNECTED','transportConnected':False,'backendOpen':False,
           'loginOpen':False,'accountVerified':False,'checkedAt':store.now(),
           'message':'原上品浏览器未连接；执行上品时会尝试恢复专用窗口'}
    if not ready():return state
    state.update(status='CONNECTING',transportConnected=True,
                 message='专用浏览器已连接，正在等待后台页；尚未核验店铺身份')
    try:
        with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{PORT}/json/list',timeout=2) as response:
            tabs=json.loads(response.read(262144))
        if not isinstance(tabs,list):return state
        urls=[urlsplit(str(tab.get('url',''))) for tab in tabs if isinstance(tab,dict) and tab.get('type')=='page']
        backend=any(url.hostname in ('post.alibaba.com','i.alibaba.com') and 'login' not in url.path.lower() for url in urls)
        login=any(url.hostname=='login.alibaba.com' for url in urls)
        state.update(backendOpen=backend,loginOpen=login)
        if backend:state.update(status='READY',message='上品连接就绪；实际执行仍会核验目标店铺')
        elif login:state.update(status='LOGIN_REQUIRED',message='专用窗口停在登录页，请在该窗口完成目标店铺登录')
    except (OSError,ValueError,TypeError,AttributeError):
        state.update(message='专用浏览器传输已连接，后台页面暂不可读取；尚未核验店铺身份')
    return state


def ensure_ready(product, timeout=20):
    """One recovery during an explicitly authorized task, before any save attempt."""
    state=status()
    if state['status']=='READY':return state
    if state['status']=='DISCONNECTED':open_browser(product)
    deadline=time.monotonic()+min(max(timeout,0),20)
    while True:
        state=status()
        if state['status']=='READY':return state
        if state['status']=='LOGIN_REQUIRED':
            raise ValueError('原上品专用浏览器需要登录目标店铺，请完成登录后继续；未开始上传或保存草稿')
        if time.monotonic()>=deadline:
            raise ValueError('原上品专用浏览器后台尚未就绪，请检查专用窗口后继续；未开始上传或保存草稿')
        time.sleep(0.4)


def open_browser(product):
    if ready():
        return {'status': 'READY', 'message': '原上品Skill浏览器已连接。请在该窗口确认目标店铺；实际填写时仍会核验账号，当前未保存草稿。'}
    folders = [os.environ.get('PROGRAMFILES(X86)', ''), os.environ.get('PROGRAMFILES', '')]
    candidates = [Path(folder) / relative for folder in folders if folder
                  for relative in ('Microsoft/Edge/Application/msedge.exe', 'Google/Chrome/Application/chrome.exe')]
    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None:
        raise ValueError('未找到原上品Skill支持的Edge/Chrome浏览器；未安装新程序或修改系统设置')
    profile = store.STATE / 'listing-browser-profile'
    profile.mkdir(parents=True, exist_ok=True)
    category = str((product.get('listingSkill') or {}).get('category_id') or '')
    url = 'https://post.alibaba.com/product/publish.htm'
    if category.isdigit():
        url += '?catId=' + category
    # Same isolated-profile launch mechanism as colleague_start.cjs; project D drive only.
    subprocess.Popen([str(executable), f'--remote-debugging-port={PORT}',
        '--remote-debugging-address=127.0.0.1', '--user-data-dir=' + str(profile),
        '--no-startup-boost', '--no-first-run', '--no-default-browser-check', '--new-window', url],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=(getattr(subprocess, 'DETACHED_PROCESS', 0)
                       | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
                       | getattr(subprocess, 'CREATE_NO_WINDOW', 0)))
    return {'status': 'OPENING', 'message': '已打开原上品Skill专用浏览器。请在这个窗口准备目标店铺，再回工作台继续至草稿；未复制其它浏览器登录资料、未填写或保存商品。'}
