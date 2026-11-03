"""Host the original selection handler on a private, parent-owned loopback socket."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
from http.server import ThreadingHTTPServer


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True)
    parser.add_argument('--ready',required=True)
    args=parser.parse_args()
    root=Path(args.root).resolve()
    if not (root/'server.py').is_file() or not (root/'dist/index.html').is_file():
        raise ValueError('Original selection application or build is missing')
    # Resolve original imports in this isolated process, never in the workbench namespace.
    sys.path.insert(0,str(root))
    spec=importlib.util.spec_from_file_location('server',root/'server.py')
    original=importlib.util.module_from_spec(spec)
    sys.modules['server']=original
    spec.loader.exec_module(original)
    if not (original.DATA/'workbench.sqlite').is_file():
        raise ValueError('Original selection database is missing; no empty replacement was created')
    original.get_database_pool()
    # Do NOT call original.main/initialize/recover: opening the embed must not rewrite runs.
    server=ThreadingHTTPServer(('127.0.0.1',0),original.Handler)
    ready=Path(args.ready)
    ready.parent.mkdir(parents=True,exist_ok=True)
    temporary=ready.with_suffix('.tmp')
    temporary.write_text(json.dumps({'pid':os.getpid(),'parent':os.getppid(),
                                    'port':server.server_port,'root':str(root)}),encoding='utf-8')
    temporary.replace(ready)
    def parent_closed():
        try:sys.stdin.buffer.read()
        finally:server.shutdown()
    threading.Thread(target=parent_closed,daemon=True).start()
    try:server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        with original.LOCK:
            for process in list(original.PROCESSES.values())+list(original.VERIFICATION_PROCESSES.values()):
                original.stop_process(process)
        original.close_database_pools()


if __name__=='__main__':main()
