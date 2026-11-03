"""Open the local workspace; start its read-only server only when needed."""
import json
import locale
from pathlib import Path
import shlex
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser
from xml.etree import ElementTree
from project_paths import runtime_identity

ROOT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8796'
SERVICE_TASK = 'Jiaxiang-International-Workbench-8796'


def start_background_server():
    """Run a Windows task only after verifying its actual source/interpreter."""
    if sys.platform == 'win32':
        query = subprocess.run(['schtasks.exe', '/Query', '/TN', SERVICE_TASK, '/XML'],
                               capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
        if query.returncode != 0:
            raise RuntimeError('Cannot verify the Windows task. No task or fallback was started; check its Action before configuring this project.')
        validate_task_action(query.stdout)
        task = subprocess.run(['schtasks.exe', '/Run', '/TN', SERVICE_TASK],
                              capture_output=True,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        if task.returncode == 0:
            return
        raise RuntimeError('The verified current-project task could not start; check the task result.')
    executable = Path(sys.executable)
    windowless = executable.with_name('pythonw.exe')
    if sys.platform == 'win32' and windowless.is_file():
        executable = windowless
    subprocess.Popen([str(executable), str(ROOT / 'service_background.py'), '--port', '8796'],
                     cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL,
                     creationflags=(getattr(subprocess, 'DETACHED_PROCESS', 0)
                                    | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)),
                     start_new_session=sys.platform != 'win32')


def validate_task_action(raw):
    try:
        if isinstance(raw, bytes):
            # schtasks can keep a UTF-16 declaration while its pipe emits UTF-8.
            if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
                raw = raw.decode('utf-16')
            elif b'\x00' in raw[:80]:
                raw = raw.decode('utf-16-le' if raw.startswith(b'<\x00') else 'utf-16-be')
            else:
                try: raw = raw.decode('utf-8-sig')
                except UnicodeDecodeError: raw = raw.decode(locale.getencoding())
        task = ElementTree.fromstring(raw)
        actions = task.find('{*}Actions')
        if actions is None or len(actions) != 1 or actions[0].tag.split('}')[-1] != 'Exec':
            raise ValueError('Expected one Python Exec action')
        action = actions[0]
        command = (action.findtext('{*}Command') or '').strip().strip('"')
        working = (action.findtext('{*}WorkingDirectory') or '').strip().strip('"')
        arguments = shlex.split(action.findtext('{*}Arguments') or '', posix=False)
        arguments = [arg.strip('"') for arg in arguments]
        if arguments[:1] == ['-B']:
            arguments = arguments[1:]
        interpreter = Path(sys.executable).resolve()
        expected = ROOT / 'service_background.py'
        script = Path(arguments[0]) if arguments else Path('missing')
        if not script.is_absolute(): script = Path(working) / script
        if (not working or Path(working).resolve() != ROOT
                or Path(command).resolve() not in (interpreter, interpreter.with_name('pythonw.exe'))
                or script.resolve() != expected
                or arguments[1:] not in ([], ['--port', '8796'])):
            raise ValueError(f'Action command={command}, script={script}, directory={working}; expected {expected}')
    except (ElementTree.ParseError, ValueError, OSError) as error:
        raise RuntimeError(f'Windows task does not identify the current project: {error}. The old task was not started; switching services requires explicit approval.') from None


def server_ready():
    try:
        with urlopen(URL + '/api/integrations', timeout=2) as response:
            data = json.load(response)
            if not isinstance(data, dict) or data.get('mode') != 'LOCAL_READ_ONLY':
                raise RuntimeError('Port 8796 is occupied by a different service.')
            actual = data.get('runtime')
            expected = runtime_identity()
            if not isinstance(actual, dict) or actual != expected:
                raise RuntimeError(f'Workbench runtime identity differs: running={actual}, expected={expected}. No service was replaced; use the old instance explicitly or approve a service migration.')
        return True
    except URLError as error:
        # An HTTP response is an existing server, not permission to replace it.
        if hasattr(error, 'code'):
            raise RuntimeError('Port 8796 is occupied by a different service.') from None
        return False
    except (ValueError, TimeoutError):
        raise RuntimeError('An unexpected service is responding on port 8796.') from None


if __name__ == '__main__':
    try:
        if not server_ready():
            start_background_server()
            for _ in range(60):
                if server_ready():
                    break
                time.sleep(.25)
            else:
                raise RuntimeError('Server did not start. Check .state/runtime/server-*.log for the error.')
        webbrowser.open(URL + '/#analytics')
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
