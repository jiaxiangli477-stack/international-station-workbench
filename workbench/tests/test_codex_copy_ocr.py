"""Offline OCR contract tests: no model, network, platform or installed Skill writes."""
import json
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import codex_copy_ocr as ocr
from project_paths import skill_root


class CopyOcrTests(unittest.TestCase):
    def setUp(self):
        folder = ROOT.parent / 'docs/acceptance/OCR-sandbox'
        folder.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=folder)
        self.root = Path(self.temp.name)
        self.image = self.root / 'image.png'
        Image.new('RGB', (40, 40), 'blue').save(self.image)
        self.calls = []
        self.which = patch.object(ocr.shutil, 'which', return_value='codex');self.which.start()

    def tearDown(self):
        self.which.stop();self.temp.cleanup()

    def fake_run(self, command, **options):
        self.calls.append((command, options))
        Path(command[command.index('--output-last-message') + 1]).write_text(
            json.dumps({'lines': ['Visible text']}), encoding='utf-8')
        return SimpleNamespace(returncode=0)

    def test_pixel_cache_reuse_and_invalidation(self):
        cache = self.root / 'cache'
        self.assertEqual(ocr.transcribe(self.image, cache, self.fake_run), ['Visible text'])
        ocr.transcribe(self.image, cache, self.fake_run)
        self.assertEqual(len(self.calls), 1)
        Image.new('RGB', (40, 40), 'red').save(self.image)
        ocr.transcribe(self.image, cache, self.fake_run)
        self.assertEqual(len(self.calls), 2)

    def test_model_receives_only_image_and_fixed_blind_prompt(self):
        ocr.transcribe(self.image, self.root / 'cache', self.fake_run)
        command, options = self.calls[0]
        self.assertEqual(command[command.index('--image') + 1], str(self.image))
        self.assertEqual(options['input'], ocr.PROMPT.encode('utf-8'))
        self.assertIn('--ephemeral', command)
        self.assertEqual(command[command.index('--sandbox') + 1], 'read-only')
        self.assertNotIn('--model', command)
        files = {p.name for p in Path(command[command.index('-C') + 1]).iterdir()}
        self.assertEqual(files, {'schema.json', 'transcription.json', 'events.jsonl'})

    def test_timeout_never_caches_success(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            ocr.transcribe(self.image, self.root / 'cache',
                           lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired('codex', 180)))
        self.assertFalse(list((self.root / 'cache').glob('*.json')))

    def test_invalid_output_is_not_accepted(self):
        for value in ({'lines': []}, {'lines': ['text'], 'extra': True}, {'lines': [None]}):
            with self.assertRaises(ValueError):ocr.valid_lines(value)

    def test_tool_use_rejects_transcription(self):
        def tool_run(command, **options):
            result = self.fake_run(command, **options)
            options['stdout'].write(b'{"type":"item.completed","item":{"type":"command_execution"}}\n')
            options['stdout'].flush()
            return result
        with self.assertRaisesRegex(RuntimeError, 'used a tool'):
            ocr.transcribe(self.image, self.root / 'cache', tool_run)

    def test_only_exact_installed_copy_checker_is_intercepted(self):
        scripts = skill_root('b2b-image-skill') / 'scripts'
        args = ['python', str(scripts / 'check_copy_ocr.py'), 'build', 'm1', '--after', str(self.image)]
        wrapped = ocr.wrap_command(args, scripts, self.root)
        self.assertEqual(wrapped[-4:], args[-4:])
        for other in (scripts / 'check_layout.py', self.root / 'check_copy_ocr.py', self.root / 'check_product_spec.py'):
            command = ['python', str(other)]
            self.assertIs(ocr.wrap_command(command, scripts, self.root), command)
        with self.assertRaisesRegex(ValueError, 'Only the installed'):
            ocr.main(['--source', str(self.root / 'check_copy_ocr.py'), '--cache-root', str(self.root)])

    def test_original_judge_rejects_missing_or_changed_copy(self):
        sys.path.insert(0, str(skill_root('b2b-image-skill') / 'scripts'))
        import check_copy_ocr
        self.assertEqual(check_copy_ocr.judge_copy(['Protein Powder'], ['Protein Powder']), ([], []))
        missing, _ = check_copy_ocr.judge_copy(['Protein Powder'], ['Protein Drink'])
        self.assertEqual(missing, ['Protein Powder'])

    def test_wrapper_runs_original_checker_and_preserves_three_exit_states(self):
        source = skill_root('b2b-image-skill') / 'scripts/check_copy_ocr.py'
        (self.root / 'm1.html').write_text('<div>Protein Powder</div>', encoding='utf-8')
        args = ['--source', str(source), '--cache-root', str(self.root / 'cache'),
                str(self.root), 'm1', '--after', str(self.image)]
        for text, code in (['Protein Powder', 0], ['Protein Drink', 1]):
            with patch.object(ocr, 'transcribe', return_value=[text]), patch('platform.system', return_value='Windows'), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as stopped:ocr.main(args)
            self.assertEqual(stopped.exception.code, code)
        with patch.object(ocr, 'transcribe', side_effect=RuntimeError('unavailable')), patch('platform.system', return_value='Windows'), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as stopped:ocr.main(args)
        self.assertEqual(stopped.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
