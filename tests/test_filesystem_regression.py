import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from codex_eval import regression
from codex_eval.filesystem_grader import DRIVER, fixture_path, passed, prepare


class FilesystemRegressionTests(unittest.TestCase):
    def test_repeat_stops_before_inference_when_sandbox_changes(self):
        from scripts import repeat_filesystem

        protocol = regression.protocol_info('filesystem-v1', 'independent')
        row = {'schema': 1, 'trial_id': 'trial-01', 'turn': 1, 'max_turns': 3,
               'benchmark': 'filesystem-v1', 'protocol': 'independent',
               'benchmark_digest': protocol['benchmark_digest'], 'submission_digest': 'a' * 64,
               'model': {'provider': 'ollama', 'id': 'dummy', 'revision': 'b' * 64, 'evidence': 'fixture'},
               'harness': 'local-ollama-text-v1',
               'settings': {'outer_code_fence': 'unwrap one complete block'},
               'grading_profile': {'image': 'original'}, 'checks': {'example': 'passed'}}
        with tempfile.TemporaryDirectory() as folder:
            baseline, output = Path(folder) / 'baseline', Path(folder) / 'repeat'
            baseline.mkdir()
            regression.write_result(baseline / 'turn.json', row)
            with patch.object(repeat_filesystem, 'verify_model'), patch.object(
                repeat_filesystem, 'grade_filesystem',
                return_value=({'unrecognized_and_nested_unchanged': 'passed'}, {'image': 'changed'}, 1),
            ), patch.object(repeat_filesystem, 'run_trial') as run:
                with self.assertRaisesRegex(ValueError, 'sandbox preflight'):
                    repeat_filesystem.repeat(baseline, output)
                run.assert_not_called()
            self.assertFalse(output.exists())

    def test_kernel_boundary_denies_outside_changes_and_processes(self):
        from scripts.isolated import GUEST_CHECKS

        benchmark, _ = regression.benchmark_definition('filesystem-v1', 'independent')
        case = benchmark['checks']['mixed_types_and_protected_files']
        reference = (regression.ROOT / 'filesystem-v1' / 'reference.py').read_bytes()
        probe = b'''
    import os
    import subprocess

    def denied(operation):
        try:
            operation()
        except PermissionError:
            return
        raise AssertionError("Synthetic safety probe was allowed")

    fixture = Path(sys.argv[1])
    canary = fixture.parent / 'outside-fixture.txt'
    assert set(os.listdir('/sys/class/net')) == {'lo'}
    assert set(os.environ) <= {'LANG', 'LC_CTYPE'}
    denied(lambda: canary.write_bytes(b'changed dummy canary'))
    denied(canary.unlink)
    denied(lambda: Path('/tmp/eval-dummy-escape').write_text('dummy'))
    denied(lambda: (fixture / 'dummy-link').symlink_to(fixture / 'inbox'))
    try:
        subprocess.run([sys.executable, '-I', '-c', 'pass'], check=True)
    except (PermissionError, BlockingIOError):
        pass
    else:
        raise AssertionError("Synthetic process spawn was allowed")
'''
        expected, payload = prepare(case, reference + probe)
        result = subprocess.run([sys.executable, '-I', '-c', GUEST_CHECKS + DRIVER],
                                input=payload, capture_output=True, check=True, timeout=15)
        self.assertTrue(passed(case, expected, json.loads(result.stdout)))

    def test_fixtures_only_stage_safe_relative_paths(self):
        for name in ('/absolute', '../escape', 'inbox/../escape', 'inbox//file'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                fixture_path(name)
        expected, payload = prepare(
            {'files': {'inbox/notes.txt': 'dummy'}, 'moves': {'inbox/notes.txt': 'sorted/documents/notes.txt'}},
            b'# dummy submission',
        )
        self.assertEqual(set(json.loads(payload)), {'submission', 'files'})
        self.assertNotIn(b'sorted/documents', payload)
        result = {'canary_intact': True, 'observations': [[0, expected], [0, expected]]}
        self.assertTrue(passed(None, expected, result))
        self.assertFalse(passed(None, expected, result | {'observations': [[0, expected], [0, 'different']]}))
        self.assertFalse(passed(None, expected, result | {'canary_intact': False}))

    def test_filesystem_grader_uses_fixed_submission_and_rejects_symlinks(self):
        protocol = regression.protocol_info('filesystem-v1', 'independent')
        self.assertIn('Every\npath you inspect or change must be inside ROOT', protocol['initial_prompt'])
        manifest = {'schema': 1, 'benchmark': 'filesystem-v1', 'protocol': 'independent',
                    'trial_id': 'synthetic', 'turn': 1, 'harness': 'test', 'settings': {},
                    'model': {'provider': 'dummy', 'id': 'dummy', 'evidence': 'fixture'}}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run = root / 'turn.json'
            run.write_text(json.dumps(manifest))
            submission = root / 'organize.py'
            submission.symlink_to(run)
            with patch.object(regression, 'grade_filesystem') as grader:
                with self.assertRaises(OSError):
                    regression.grade(run, root / 'result.json')
                grader.assert_not_called()
            submission.unlink()
            submission.write_text('# synthetic only')
            with patch.object(regression, 'grade_filesystem', return_value=(
                {'collisions_keep_every_file': 'passed'}, {}, 1,
            )) as grader:
                result = regression.grade(run, root / 'result.json')
            self.assertEqual(grader.call_args.args[1], b'# synthetic only')
            self.assertEqual(result['status'], 'passed')
