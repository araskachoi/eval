import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_eval import benchmark_harness, benchmark_run, regression


class BenchmarkRunTests(unittest.TestCase):
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
