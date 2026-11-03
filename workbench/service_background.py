"""Run the workbench without a console, retaining private startup/error logs."""
from datetime import datetime
import faulthandler
import json
import os
from pathlib import Path
import runpy
import sys
import traceback

ROOT = Path(__file__).resolve().parent


def main():
    runtime = ROOT / '.state' / 'runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    log_path = runtime / ('server-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.log')
    with log_path.open('a', encoding='utf-8', buffering=1) as log:
        sys.stdout = sys.stderr = log
        faulthandler.enable(file=log)
        os.chdir(ROOT)
        try:
            # Project-scoped paths only; never load arbitrary credentials or commands.
            env_path = runtime / 'project-env.json'
            if env_path.is_file():
                values=json.loads(env_path.read_text(encoding='utf-8-sig'))
                allowed={'WORKBENCH_ATTRIBUTE_SKILL_ROOT','WORKBENCH_B2B_SKILL_ROOT',
                         'WORKBENCH_LISTING_PYTHON','NODE_PATH','TMP','TEMP','PYTHONDONTWRITEBYTECODE',
                         'WORKBENCH_PYTHON','WORKBENCH_NODE_MODULES',
                         'HTTP_PROXY','HTTPS_PROXY','NO_PROXY'}
                if not isinstance(values,dict) or set(values)-allowed:
                    raise ValueError('Unsupported project runtime setting')
                for key,value in values.items():
                    if not isinstance(value,str) or not value or '\x00' in value:
                        raise ValueError('Invalid project runtime setting')
                    if key in ('HTTP_PROXY','HTTPS_PROXY'):
                        from urllib.parse import urlsplit
                        proxy=urlsplit(value)
                        if proxy.scheme!='http' or proxy.hostname not in ('127.0.0.1','localhost') or not proxy.port or proxy.username or proxy.password:
                            raise ValueError('Only the configured local proxy is allowed')
                    os.environ[key]=value
            config_path = runtime / 'executable-paths.json'
            if config_path.is_file():
                paths = json.loads(config_path.read_text(encoding='utf-8-sig'))
                directories = [str(Path(p).parent) for p in paths if Path(p).is_file()]
                os.environ['PATH'] = os.pathsep.join(directories + [os.environ.get('PATH', '')])
            print(f'Started {datetime.now().isoformat()} pid={os.getpid()}', flush=True)
            (runtime / 'server-process.json').write_text(json.dumps({
                'pid': os.getpid(), 'log': str(log_path),
                'startedAt': datetime.now().isoformat(),
            }), encoding='utf-8')
            runpy.run_path(str(ROOT / 'serve.py'), run_name='__main__')
        except BaseException:
            traceback.print_exc(file=log)
            raise
        finally:
            print(f'Exited {datetime.now().isoformat()}', flush=True)


if __name__ == '__main__':
    main()
