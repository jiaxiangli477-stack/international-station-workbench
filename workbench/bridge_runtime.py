"""Current Accio gateway credentials stay in the child environment only."""
import importlib.util
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


def trusted_setup(executable):
    try:
        relative = Path(executable).resolve().relative_to(ROOT)
    except (ValueError, OSError):
        return None
    parts = relative.parts
    if parts[-1:] not in [('workctl.cmd',), ('accio-mcp-cli.cmd',)]:
        return None
    fixed = parts[:-1] == ('.state', 'yh-check', 'bridge', 'bin')
    run = (len(parts) == 7 and parts[:3] in
           (('.state', 'weekly', 'runs'), ('.state', 'operations', 'runs'))
           and parts[-3:-1] == ('bridge', 'bin'))
    if not (fixed or run):
        return None
    source = ROOT / relative.parent.parent / 'setup_env.py'
    # Also reject a setup script symlink escaping the trusted bridge directory.
    if source.resolve().parent != source.parent:
        raise ValueError('项目网关脚本路径不可信；未读取或回退旧配置')
    return source


def current_credentials(source):
    spec = importlib.util.spec_from_file_location('workbench_existing_bridge_setup', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.find_credentials()


def child_environment(executable, env):
    child = dict(env)
    source = trusted_setup(executable)
    if source is None:
        return child
    # A parent process can outlive an Accio restart and keep an expired token.
    # Refresh only when this trusted shim targets the managed local gateway;
    # preserve explicitly configured nonlocal gateways.
    if child.get('ACCIO_GATEWAY_TOKEN'):
        configured_url = urlsplit(child.get('ACCIO_LOCAL_GATEWAY_URL') or 'http://localhost:4097')
        if (configured_url.scheme != 'http'
                or configured_url.hostname not in ('localhost', '127.0.0.1', '::1')
                or configured_url.port not in (None, 4097)
                or configured_url.username or configured_url.password):
            return child
    try:
        credentials = current_credentials(source)
        url = urlsplit(credentials.get('url', ''))
        if (not credentials.get('note', '').startswith('pid=') or not credentials.get('token')
                or url.scheme != 'http' or url.hostname not in ('localhost', '127.0.0.1', '::1')
                or url.port != 4097 or url.username or url.password):
            raise ValueError('No current gateway')
        child.update(ACCIO_GATEWAY_TOKEN=credentials['token'],
                     ACCIO_GATEWAY_USERNAME=credentials.get('user') or 'phoenix',
                     ACCIO_LOCAL_GATEWAY_URL=credentials['url'])
    except Exception:
        raise ValueError('当前 Accio 网关未匹配活动进程；未回退到旧账号配置') from None
    return child
