"""Exercise the installed spec judge with mocked blind OCR, never a model."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import codex_copy_ocr as ocr
from project_paths import skill_root


class SpecOCRTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir='D:/Codex', prefix='spec-ocr-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = skill_root('b2b-image-skill') / 'scripts/check_product_spec.py'
        self.src = self.root / 'source.png'
        self.final = self.root / 'final.png'
        Image.new('RGB', (20, 30), 'red').save(self.src)
        Image.new('RGB', (100, 100), 'blue').save(self.final)

    def invoke(self, transcribe, extra=()):
        args = ['--source', str(self.source), '--cache-root', str(self.root / 'cache'),
                str(self.final), '--src', str(self.src), '--box', '10,20,40,50', *extra]
        with patch.object(ocr, 'transcribe', side_effect=transcribe), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as stopped:
                ocr.main(args)
        return stopped.exception.code

    def test_exact_spec_command_intercepted(self):
        command = ['python', str(self.source), 'final.png']
        self.assertIsNot(ocr.wrap_command(command, self.source.parent, self.root), command)

    def test_original_judge_preserves_pass_bad_and_unchecked(self):
        for final_text, code in (('22G', 0), ('33G', 1), ('NO SPEC', 2)):
            calls = []
            def read(path, cache):
                with Image.open(path) as image:
                    calls.append(image.size)
                return ['22G' if len(calls) % 2 else final_text]
            self.assertEqual(self.invoke(read), code)
            self.assertEqual(calls, [(60, 90), (120, 150), (80, 120), (160, 200)])

    def test_original_cross_scale_disagreement_stays_unchecked(self):
        lines = iter((['22G'], ['33G'], ['22G'], ['44G']))
        self.assertEqual(self.invoke(lambda *_: next(lines)), 2)

    def test_original_missing_source_spec_stays_unchecked(self):
        self.assertEqual(self.invoke(lambda *_: ['NO SPEC']), 2)

    def test_missing_product_box_never_transcribes_finished_full_image(self):
        args = ['--source', str(self.source), '--cache-root', str(self.root / 'cache'),
                str(self.final), '--src', str(self.src)]
        with patch.object(ocr, 'transcribe', side_effect=AssertionError('no full-image fallback')), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as stopped:
                ocr.main(args)
        self.assertEqual(stopped.exception.code, 2)

    def test_positive_confidence_threshold_never_calls_provider(self):
        self.assertEqual(self.invoke(lambda *_: self.fail('provider must not run'), ['--min-conf', '0.1']), 2)

    def test_provider_failure_remains_unchecked(self):
        def fail(*_):
            raise RuntimeError('fixture unavailable')
        self.assertEqual(self.invoke(fail), 2)

    def test_crop_evidence_has_real_pixel_hash_and_no_fake_confidence(self):
        self.assertEqual(self.invoke(lambda *_: ['22G']), 0)
        records = list((self.root / 'cache/spec-crops').glob('*.json'))
        self.assertEqual(len(records), 4)
        for record in records:
            value = json.loads(record.read_text(encoding='utf-8'))
            self.assertEqual(value['provider'], 'codex-blind-vision')
            self.assertIs(value['confidenceAvailable'], False)
            self.assertNotIn('confidence', value)
            self.assertEqual(value['pixelHash'], ocr.pixel_hash(record.with_suffix('.png')))


if __name__ == '__main__':
    unittest.main()
