from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from codex_eval import benchmark_harness, benchmark_run, regression
from codex_eval.__main__ import main
from scripts import isolated


class BenchmarkRunTests(unittest.TestCase):
    def test_diagnostics_count_recovered_checks_and_group_first_turn_cache_usage(self):
        def row(trial, turn, status, cached, elapsed):
            return {'trial_id': trial, 'turn': turn, 'checks': {'replay': status},
                    'metrics': {'cached_input_tokens': cached, 'elapsed_ms': elapsed},
                    'grading_ms': 10}

        report = benchmark_run.trial_diagnostics({
            'a': [row('a', 2, 'passed', 30, 700), row('a', 1, 'failed', 0, 300)],
            'b': [row('b', 1, 'passed', 20, 200)],
            'c': [row('c', 1, 'passed', None, 400)],
        })
        self.assertEqual(report['check_pass_rates']['first_turn']['replay']['passed'], 2)
        self.assertEqual(report['check_pass_rates']['final_turn']['replay']['passed'], 3)
        self.assertEqual(report['first_turn_latency_ms']['zero_cached_input'],
                         {'samples': 1, 'median': 300, 'min': 300, 'max': 300})
        self.assertEqual(report['first_turn_latency_ms']['cache_hit']['median'], 200)
        self.assertEqual(report['first_turn_latency_ms']['cache_unknown']['median'], 400)
        self.assertEqual(report['grading_ms'], 40)

    def test_codex_reuses_chatgpt_login_without_reading_api_key(self):
        with (patch.object(benchmark_harness.shutil, 'which', return_value='/dummy/codex'),
              patch.object(benchmark_harness, 'codex_preflight', return_value='test-cli'),
              patch.object(benchmark_harness, 'codex_process',
                           side_effect=['Logged in using ChatGPT\n', 'receipt']) as process,
              patch.object(benchmark_harness, 'codex_receipt', return_value=('submission', {})),
              patch.object(benchmark_harness, 'codex_key') as key):
            model, _, settings, infer = benchmark_harness.select_harness(
                {'harness': 'codex', 'model': 'test-model'})
            self.assertEqual(settings['authentication'], 'chatgpt')
            self.assertEqual(infer(model, [{'content': 'prompt'}], settings), ('submission', {}))
            key.assert_not_called()
            status, turn = process.call_args_list
            self.assertEqual(status.args[2], ['login', 'status'])
            self.assertEqual(status.kwargs['home'], turn.kwargs['home'])
            self.assertIsNone(turn.kwargs['api_key'])
            self.assertIn('--ignore-user-config', turn.args[2])

    def test_keychain_reports_missing_service(self):
        with patch.object(benchmark_harness.subprocess, 'run',
                          side_effect=subprocess.CalledProcessError(44, '/usr/bin/security')):
            with self.assertRaisesRegex(ValueError, 'No visible macOS Keychain item has service eval-codex-api-key'):
                benchmark_harness.codex_key(keychain=True)

    def test_inline_codex_run_reads_keychain_and_saves_effective_spec(self):
        fake_key = 'synthetic-key-for-test'
        command = ['codex-eval', 'regression', 'run', '--harness', 'codex',
                   '--model', 'test-model', '--keychain']
        events = [{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '# dummy'}},
                  {'type': 'turn.completed', 'usage': {'input_tokens': 12, 'output_tokens': 3}}]

        def process(args, **kwargs):
            if args[0] == '/usr/bin/security':
                self.assertEqual(args[1:], ['find-generic-password', '-s', 'eval-codex-api-key', '-w'])
                return subprocess.CompletedProcess(args, 0, fake_key + '\n')
            self.assertEqual(args[0], '/dummy/codex')
            if 'exec' in args:
                self.assertEqual(kwargs['env']['CODEX_API_KEY'], fake_key)
                self.assertNotIn(fake_key, kwargs['input'].decode())
                self.assertNotIn(fake_key, args)
                content = '\n'.join(map(json.dumps, events))
            else:
                self.assertNotIn('CODEX_API_KEY', kwargs['env'])
                content = ('codex-cli fixture' if '--version' in args else '\n'.join(
                    f'{feature} test false' for feature in benchmark_harness.DISABLED
                ))
            kwargs['stdout'].write(content.encode())
            return subprocess.CompletedProcess(args, 0)

        def grade(cases, _):
            return dict.fromkeys(cases, 'passed'), {'sandbox': 'dummy'}, 1

        with tempfile.TemporaryDirectory() as directory:
            stdout, stderr = io.StringIO(), io.StringIO()
            root = Path(directory)
            with (patch.object(sys, 'argv', command), patch.object(isolated, 'RUNTIME', root / '.runtime'),
                  patch.object(isolated, 'start_machine') as start,
                  patch.object(regression, 'grade_filesystem', side_effect=grade),
                  patch.object(benchmark_harness.shutil, 'which', return_value='/dummy/codex'),
                  patch.object(benchmark_harness.subprocess, 'run', side_effect=process),
                  redirect_stdout(stdout), redirect_stderr(stderr)):
                main()
            start.assert_called_once_with()
            output, = (root / 'regression' / 'results' / 'filesystem').iterdir()
            self.assertIn(str(output), stderr.getvalue())
            result = json.loads(stdout.getvalue())
            self.assertEqual(result['first_pass']['passed'], 1)
            self.assertEqual(result['metrics']['input_tokens'], 12)
            self.assertEqual(len(result['checks_by_trial']), 1)
            self.assertIn('first turn 1/1 | final 1/1', stderr.getvalue())
            run_spec = json.loads((output / 'run.json').read_text())['spec']
            self.assertEqual(run_spec, {'benchmark': 'filesystem-v1', 'protocol': 'independent',
                                        'trials': 1, 'harness': 'codex', 'model': 'test-model'})
            for path in output.rglob('*.json'):
                self.assertNotIn(fake_key, path.read_text())
            self.assertNotIn(fake_key, stdout.getvalue() + stderr.getvalue())

    def test_codex_accepts_completion_and_rejects_tool_events(self):
        events = [{'type': 'thread.started'}, {'type': 'turn.started'},
                  {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'print(1)'}},
                  {'type': 'turn.completed', 'usage': {'input_tokens': 12, 'output_tokens': 3}}]
        self.assertEqual(benchmark_harness.codex_receipt('\n'.join(map(json.dumps, events))),
                         ('print(1)', {'input_tokens': 12, 'output_tokens': 3}))
        events.insert(2, {'type': 'item.started', 'item': {'type': 'command_execution'}})
        with self.assertRaisesRegex(ValueError, 'unsupported event'):
            benchmark_harness.codex_receipt('\n'.join(map(json.dumps, events)))

    def test_resume_keeps_completed_trials_and_restarts_interrupted_trial(self):
        profile = {'sandbox': 'dummy'}
        model = {'provider': 'openai', 'id': 'test-model', 'revision': None, 'evidence': 'fixture'}
        calls = []
        settings = {'outer_code_fence': 'unwrap one complete block'}

        def fake_infer(*args):
            calls.append(1)
            if len(calls) == 2:
                raise KeyboardInterrupt
            return '# dummy', {'input_tokens': 12}

        def fake_grader(cases, _):
            return dict.fromkeys(cases, 'passed'), profile, 1

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec, output = root / 'spec.json', root / 'run'
            regression.write_result(spec, {'benchmark': 'filesystem-v1', 'protocol': 'independent',
                                           'harness': 'codex', 'model': 'test-model', 'trials': 2})
            with patch.object(regression, 'grade_filesystem', side_effect=fake_grader), patch.object(
                benchmark_run, 'select_harness',
                return_value=(model, 'codex-cli-text-v1', settings, fake_infer),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    benchmark_run.run(spec, output)
                first = (output / 'grades' / 'trial-01-turn-1.json').read_bytes()
                result = benchmark_run.run(spec, output, resume=True)
                self.assertEqual(result['final_pass']['passed'], 2)
                self.assertEqual(len(calls), 3)
                self.assertEqual((output / 'grades' / 'trial-01-turn-1.json').read_bytes(), first)
                self.assertEqual(benchmark_run.run(spec, output, resume=True), result)
                self.assertEqual(len(calls), 3)
                (output / 'grades').rename(root / 'saved-grades')
                (output / 'grades').symlink_to(root / 'saved-grades', target_is_directory=True)
                with self.assertRaisesRegex(ValueError, 'symlinks'):
                    benchmark_run.run(spec, output, resume=True)
                self.assertEqual(len(calls), 3)

                candidate, baseline = root / 'candidate', root / 'saved-grades'
                paired = benchmark_run.run(spec, candidate, baseline=baseline)
                self.assertEqual(len(paired['comparison']['paired_trials']), 2)
                self.assertEqual(paired['comparison']['verdict'], 'unchanged')
                self.assertEqual(benchmark_run.run(spec, candidate, baseline=baseline, resume=True), paired)
                self.assertEqual(len(calls), 5)
