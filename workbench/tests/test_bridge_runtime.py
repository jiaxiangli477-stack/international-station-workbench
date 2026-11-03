"""No real gateway calls or credentials: subprocess injection and fail-closed checks."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge_runtime
import weekly_update


class BridgeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.cli = bridge_runtime.ROOT / '.state/yh-check/bridge/bin/workctl.cmd'
        self.credentials = dict(note='pid=123 匹配监听进程', token='fixture-current',
                                user='fixture-user', url='http://localhost:4097')

    def test_explicit_environment_preserved_without_discovery(self):
        env = {'ACCIO_GATEWAY_TOKEN': 'fixture-explicit', 'ACCIO_LOCAL_GATEWAY_URL': 'http://localhost:1234'}
        with patch.object(bridge_runtime, 'current_credentials', side_effect=AssertionError('no discovery')):
            self.assertEqual(bridge_runtime.child_environment(self.cli, env), env)

    def test_active_pid_match_injects_only_child_and_both_cli_names(self):
        for name in ('workctl.cmd', 'accio-mcp-cli.cmd'):
            env = {'TMP': 'D:/fixture'}
            with patch.object(bridge_runtime, 'current_credentials', return_value=self.credentials):
                child = bridge_runtime.child_environment(self.cli.with_name(name), env)
            self.assertNotIn('ACCIO_GATEWAY_TOKEN', env)
            self.assertEqual(child['ACCIO_GATEWAY_TOKEN'], 'fixture-current')
            self.assertEqual(child['ACCIO_LOCAL_GATEWAY_URL'], 'http://localhost:4097')
            self.assertEqual(child['TMP'], 'D:/fixture')

    def test_stale_inherited_local_gateway_token_is_refreshed_from_active_pid(self):
        env={'ACCIO_GATEWAY_TOKEN':'fixture-stale','ACCIO_GATEWAY_USERNAME':'old-user',
             'ACCIO_LOCAL_GATEWAY_URL':'http://localhost:4097'}
        with patch.object(bridge_runtime,'current_credentials',return_value=self.credentials) as read:
            child=bridge_runtime.child_environment(self.cli,env)
        read.assert_called_once()
        self.assertEqual(child['ACCIO_GATEWAY_TOKEN'],'fixture-current')
        self.assertEqual(child['ACCIO_GATEWAY_USERNAME'],'fixture-user')
        self.assertEqual(env['ACCIO_GATEWAY_TOKEN'],'fixture-stale')

    def test_no_pid_match_or_nonlocal_gateway_never_falls_back(self):
        cases = [dict(note='按 pid 未匹配，回退到最近修改的文件'), dict(token=''),
                 dict(url='http://example.test:4097'), dict(url='http://localhost:4098')]
        for updates in cases:
            with patch.object(bridge_runtime, 'current_credentials', return_value={**self.credentials, **updates}):
                with self.assertRaisesRegex(ValueError, '未回退到旧账号配置'):
                    bridge_runtime.child_environment(self.cli, {})

    def test_untrusted_paths_cannot_load_setup(self):
        for cli in ('D:/other/bridge/bin/workctl.cmd', bridge_runtime.ROOT / 'other/workctl.cmd',
                    self.cli.with_name('other.cmd')):
            with patch.object(bridge_runtime, 'current_credentials', side_effect=AssertionError('no discovery')):
                self.assertEqual(bridge_runtime.child_environment(cli, {'TMP': 'D:/fixture'}), {'TMP': 'D:/fixture'})

    def test_isolated_project_run_bridges_share_the_same_guard(self):
        for area in ('weekly', 'operations'):
            cli = bridge_runtime.ROOT / f'.state/{area}/runs/fixture/bridge/bin/workctl.cmd'
            with patch.object(bridge_runtime, 'current_credentials', return_value=self.credentials):
                child = bridge_runtime.child_environment(cli, {})
            self.assertEqual(child['ACCIO_GATEWAY_TOKEN'], 'fixture-current')

    def test_discovery_failure_is_sanitized_without_fallback(self):
        with patch.object(bridge_runtime, 'current_credentials', side_effect=RuntimeError('fixture-secret')):
            with self.assertRaises(ValueError) as caught:
                bridge_runtime.child_environment(self.cli, {})
        self.assertNotIn('fixture-secret', str(caught.exception))
        self.assertIn('未回退', str(caught.exception))

    def test_run_passes_current_credentials_and_stops_before_cli_on_missing_match(self):
        with patch.object(bridge_runtime, 'current_credentials', return_value=self.credentials), \
                patch.object(weekly_update.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='{}')) as run:
            self.assertEqual(weekly_update.run([self.cli, 'schema'], bridge_runtime.ROOT, env={}), '{}')
            self.assertEqual(run.call_args.kwargs['env']['ACCIO_GATEWAY_TOKEN'], 'fixture-current')
        with patch.object(bridge_runtime, 'current_credentials', return_value={}), \
                patch.object(weekly_update.subprocess, 'run') as run:
            with self.assertRaises(weekly_update.SyncError):
                weekly_update.run([self.cli, 'schema'], bridge_runtime.ROOT, env={})
            run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
