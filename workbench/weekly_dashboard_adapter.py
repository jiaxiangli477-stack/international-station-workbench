"""Executed in an isolated copied dashboard package by weekly_update.py."""
import argparse
import os
from pathlib import Path
import sys


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for key in ('bridge', 'expected', 'identity', 'workspace-code', 'as-of', 'label'):
        parser.add_argument('--' + key, required=True)
    args = parser.parse_args()
    package = Path(__file__).resolve().parent
    sys.path.insert(0, args.workspace_code)
    from weekly_update import require_identity
    import bridge_runtime
    sys.path.insert(0, str(package))
    import make_dashboard as dashboard
    from dashboard_calendar import install
    install(package,args.workspace_code,args.as_of)
    bridge, identity = Path(args.bridge), Path(args.identity)
    original = dashboard.run

    def guarded_run(*a, **kw):
        credential_keys=('ACCIO_GATEWAY_TOKEN','ACCIO_GATEWAY_USERNAME','ACCIO_LOCAL_GATEWAY_URL')
        previous={key:os.environ.get(key) for key in credential_keys}
        try:
            require_identity(bridge, identity, args.expected)
            current=bridge_runtime.child_environment(bridge/'workctl.cmd',dict(os.environ))
            for key in credential_keys:
                if key in current:os.environ[key]=current[key]
                else:os.environ.pop(key,None)
            command, *rest = a
            if len(command) > 1 and Path(command[1]).name == 'v6_fetch_imgs.py':
                command = [sys.executable, str(Path(args.workspace_code) / 'dashboard_product_images.py'),
                           '--workspace', str(rest[0] if rest else kw['cwd'])]
                a = (command, *rest)
            ok = original(*a, **kw)
            require_identity(bridge, identity, args.expected)
            return ok
        except Exception:
            return False
        finally:
            for key,value in previous.items():
                if value is None:os.environ.pop(key,None)
                else:os.environ[key]=value

    dashboard.run = guarded_run
    dashboard.ensure_deps = lambda: None  # Unencrypted dashboards do not need optional installation.
    dashboard.detect_accounts = lambda: [{'company': args.label, 'ali_id': args.expected, 'login_id': ''}]
    sys.argv = ['make_dashboard.py', '--reuse', '--as-of', args.as_of, '--no-open', '--store-name', args.label]
    result = dashboard.main()
    if result == 0:
        from dashboard_integrity import apply
        apply(package / 'engine' / 'workspace')
        from dashboard_export import export_single
        export_single(package / 'engine' / 'workspace' / 'dashboard',
                      package / 'engine' / 'workspace' / '经营数据面板.html')
    raise SystemExit(result)
