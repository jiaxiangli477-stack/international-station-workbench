import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError, HTTPError

import open_workbench as launcher


class LauncherIdentityTests(unittest.TestCase):
    identity = {'root': str(launcher.ROOT), 'build': 'current-build'}

    def response(self, **changes):
        data = {'mode': 'LOCAL_READ_ONLY', 'runtime': dict(self.identity)}
        data.update(changes)
        return io.BytesIO(json.dumps(data).encode())

    def test_healthy_current_workbench_never_requires_8788(self):
        with patch.object(launcher, 'runtime_identity', return_value=self.identity, create=True), \
                patch.object(launcher, 'ensure_selection_service', side_effect=RuntimeError('8788 occupied'), create=True) as selection, \
                patch.object(launcher, 'urlopen', return_value=self.response()) as opened:
            self.assertTrue(launcher.server_ready())
        selection.assert_not_called()
        self.assertEqual(opened.call_args.args[0], launcher.URL + '/api/integrations')

    def test_old_root_or_build_or_missing_identity_is_rejected(self):
        for identity in ({'root': 'D:/old-copy', 'build': 'current-build'},
                         {'root': str(launcher.ROOT), 'build': 'obsolete'}, {}):
            with self.subTest(identity=identity), \
                    patch.object(launcher, 'runtime_identity', return_value=self.identity, create=True), \
                    patch.object(launcher, 'ensure_selection_service', return_value=None, create=True), \
                    patch.object(launcher, 'urlopen', return_value=self.response(runtime=identity)):
                with self.assertRaisesRegex(RuntimeError, 'identity|身份|目录|构建'):
                    launcher.server_ready()

    def test_absent_server_returns_false_and_http_error_refuses_replacement(self):
        with patch.object(launcher, 'ensure_selection_service', return_value=None, create=True), \
                patch.object(launcher, 'urlopen', side_effect=URLError('refused')):
            self.assertFalse(launcher.server_ready())
        with patch.object(launcher, 'ensure_selection_service', return_value=None, create=True), \
                patch.object(launcher, 'urlopen', side_effect=HTTPError(launcher.URL, 404, 'other', {}, None)):
            with self.assertRaises(RuntimeError): launcher.server_ready()

    def task_xml(self, root=None):
        root = root or launcher.ROOT
        return f'<Task><Actions><Exec><Command>{sys.executable}</Command><Arguments>"{root / "service_background.py"}" --port 8796</Arguments><WorkingDirectory>{root}</WorkingDirectory></Exec></Actions></Task>'.encode()

    def test_old_windows_task_is_queried_but_never_run_or_fallback_spawned(self):
        result = type('Result', (), {'returncode': 0, 'stdout': self.task_xml(Path('D:/old-copy'))})()
        with patch.object(launcher.sys, 'platform', 'win32'), \
                patch.object(launcher.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                patch.object(launcher.subprocess, 'run', return_value=result) as run, \
                patch.object(launcher.subprocess, 'Popen') as spawn:
            with self.assertRaises(RuntimeError): launcher.start_background_server()
        self.assertEqual(run.call_count, 1)
        self.assertIn('/Query', run.call_args.args[0])
        spawn.assert_not_called()

    def test_current_task_can_run_only_after_xml_validation(self):
        query = type('Result', (), {'returncode': 0, 'stdout': self.task_xml()})()
        started = type('Result', (), {'returncode': 0})()
        with patch.object(launcher.sys, 'platform', 'win32'), \
                patch.object(launcher.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
                patch.object(launcher.subprocess, 'run', side_effect=[query, started]) as run, \
                patch.object(launcher.subprocess, 'Popen') as spawn:
            launcher.start_background_server()
        self.assertEqual(run.call_count, 2)
        self.assertIn('/Query', run.call_args_list[0].args[0])
        self.assertIn('/Run', run.call_args_list[1].args[0])
        spawn.assert_not_called()

    def test_task_xml_console_encoding_and_no_bytecode_flag_are_supported(self):
        xml=self.task_xml().decode('utf-8').replace('<Arguments>','<Arguments>-B ')
        for raw in (( '<?xml version="1.0" encoding="UTF-16"?>'+xml).encode('utf-8'),
                    ('<?xml version="1.0" encoding="UTF-16"?>'+xml).encode('utf-16')):
            with self.subTest(prefix=raw[:8]):launcher.validate_task_action(raw)

    def test_other_interpreter_flags_cannot_replace_the_bound_script(self):
        for flag in ('-c', '-m', '-B -c'):
            xml=self.task_xml().decode('utf-8').replace('<Arguments>','<Arguments>'+flag+' ')
            with self.assertRaises(RuntimeError):launcher.validate_task_action(xml.encode())


class ProjectPathsTests(unittest.TestCase):
    def setUp(self):
        self.environment=patch.dict(os.environ,{'WORKBENCH_SKILLS_ROOT':'','WORKBENCH_ATTRIBUTE_SKILL_ROOT':'','WORKBENCH_B2B_SKILL_ROOT':''})
        self.environment.start()
        self.addCleanup(self.environment.stop)
    def test_individual_attribute_override_does_not_hide_other_installed_skills(self):
        import project_paths as paths
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); installed = root / 'installed'
            (installed / 'b2b-image-skill').mkdir(parents=True)
            with patch.dict(os.environ, {'WORKBENCH_ATTRIBUTE_SKILL_ROOT': str(root / 'selected-attribute')}, clear=True), \
                    patch.object(paths, 'DEFAULT_SKILLS_ROOT', root / 'absent'), \
                    patch.object(paths, 'INSTALLED_SKILLS_ROOT', installed):
                self.assertEqual(paths.skill_root('alibaba-attribute-filler'), root / 'selected-attribute')
                self.assertEqual(paths.skill_root('b2b-image-skill'), installed / 'b2b-image-skill')

    def test_explicit_skill_root_never_silently_falls_back(self):
        import project_paths as paths
        with patch.dict(os.environ, {'WORKBENCH_SKILLS_ROOT': 'D:/missing-explicit'}):
            self.assertEqual(paths.skill_root('alibaba-attribute-filler'), Path('D:/missing-explicit/alibaba-attribute-filler').resolve())

    def test_default_skill_lookup_preserves_mixed_root_read_fallback(self):
        import project_paths as paths
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); preferred = root / 'd'; installed = root / 'installed'
            preferred.mkdir(); (installed / 'b2b-image-skill').mkdir(parents=True)
            with patch.dict(os.environ, {}, clear=True), patch.object(paths, 'DEFAULT_SKILLS_ROOT', preferred), \
                    patch.object(paths, 'INSTALLED_SKILLS_ROOT', installed):
                self.assertEqual(paths.skills_root(), preferred)
                self.assertEqual(paths.skill_root('b2b-image-skill'), installed / 'b2b-image-skill')
                self.assertEqual(paths.skill_root('alibaba-attribute-filler'), preferred / 'alibaba-attribute-filler')

    def test_missing_dependency_preflight_lists_exact_files_and_category_config(self):
        import project_paths as paths
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'WORKBENCH_SKILLS_ROOT': tmp}):
            result = paths.skill_preflight('alibaba-attribute-filler')
            self.assertFalse(result['available'])
            self.assertIn('scripts/route_category.cjs', result['missing'])
            self.assertIn('categories/*/config.json', result['missing'])
            self.assertEqual(result['version'], 'unverified')

    def test_b2b_preflight_reports_pinned_commit_only_while_skill_entry_matches(self):
        import hashlib
        import project_paths as paths
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'skills'/'b2b-image-skill';root.mkdir(parents=True)
            entry=root/'SKILL.md';entry.write_text('# Image skill\n',encoding='utf-8')
            source={'skill_root':str(root.resolve()),'commit':'505dca197860dddaec37458b2f0e70cf15f840d6',
                    'commit_date':'2026-10-13','skill_md_sha256':hashlib.sha256(entry.read_bytes()).hexdigest()}
            (root.parent/'b2b-image-skill.source.json').write_text(json.dumps(source),encoding='utf-8')
            with patch.dict(os.environ,{'WORKBENCH_B2B_SKILL_ROOT':str(root)}):
                result=paths.skill_preflight('b2b-image-skill')
                self.assertEqual(result['version'],'505dca1@2026-10-13')
                self.assertIn('pinned github commit',result['note'].lower())
                entry.write_text('# changed\n',encoding='utf-8')
                self.assertEqual(paths.skill_preflight('b2b-image-skill')['version'],'unverified')

    def test_build_identity_changes_with_source_but_ignores_state(self):
        import project_paths as paths
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'serve.py'; source.write_text('first')
            before = paths.build_fingerprint(root)
            state = root / '.state'; state.mkdir(); (state / 'secret.py').write_text('private')
            self.assertEqual(paths.build_fingerprint(root), before)
            source.write_text('second')
            self.assertNotEqual(paths.build_fingerprint(root), before)


if __name__ == '__main__': unittest.main()
