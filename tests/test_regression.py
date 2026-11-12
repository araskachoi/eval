import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_eval import regression
from codex_eval.regression_grader import apply_controls, digest, passed, payload_for


def metadata(turn=1):
    return {'schema': 1, 'trial_id': 'trial-01', 'turn': turn, 'benchmark': 'ledger-v1',
            'model': {'provider': 'example', 'id': 'baseline', 'evidence': 'receipt'},
            'harness': 'manual', 'settings': {'temperature': 0},
            'metrics': {'input_tokens': 10, 'output_tokens': 5, 'elapsed_ms': 30}}


class RegressionTests(unittest.TestCase):
    def test_protocols_have_distinct_identity_and_fixed_guided_repair(self):
        independent = regression.protocol_info('ledger-v2', 'independent')
        guided = regression.protocol_info('ledger-v2', 'guided')
        self.assertIn('LEDGER and BATCH are file paths', independent['initial_prompt'])
        self.assertNotIn('Implementation guidance', independent['initial_prompt'])
        self.assertIn('Implementation guidance', guided['initial_prompt'])
        self.assertNotEqual(independent['benchmark_digest'], guided['benchmark_digest'])
        self.assertEqual(regression.protocol_info('ledger-v1', None)['benchmark_digest'],
                         'f61dd96aac1787f8bf4afd53b9a94035b3d082ef9f5f453f85609e22d49ebe4a')
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            run = folder / 'turn.json'
            run.write_text(json.dumps(metadata(4) | {'benchmark': 'ledger-v2', 'protocol': 'guided'}))
            (folder / 'ledger.py').write_text('# submission')
            with patch.object(regression, 'grade_ledger',
                              return_value=({'malformed_row_rollback': 'failed'}, {}, 300)):
                feedback = regression.grade(run, folder / 'result.json')
            self.assertIn('Booleans are invalid', feedback['repair_prompt'])

    def test_rejection_checks_require_working_apply(self):
        benchmark, _ = regression.benchmark_definition('ledger-v2', 'guided')
        checks = benchmark['checks']
        self.assertEqual(sum('positive_control' in case for case in checks.values()), 4)
        for status in ('failed', 'passed', 'error'):
            outcomes = dict.fromkeys(checks, 'passed') | {'append_and_total': status}
            apply_controls(checks, outcomes)
            for name, case in checks.items():
                if 'positive_control' in case:
                    self.assertEqual(outcomes[name], status)

    def test_grade_saves_metrics_and_feedback_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            run, output = folder / 'turn.json', folder / 'result.json'
            run.write_text(json.dumps(metadata()))
            (folder / 'ledger.py').write_text('untrusted submission')
            with patch.object(regression, 'grade_ledger', return_value=({'replay': 'failed'}, {}, 300)):
                feedback = regression.grade(run, output)
            self.assertEqual(feedback['failed_checks'], ['replay'])
            self.assertIsNotNone(feedback['repair_prompt'])
            saved = json.loads(output.read_text())
            self.assertEqual(saved['metrics']['elapsed_ms'], 30)
            self.assertEqual(saved['grading_ms'], 300)
            self.assertEqual(saved['submission_digest'], digest(b'untrusted submission'))
            with patch.object(regression, 'grade_ledger') as grader:
                with self.assertRaises(ValueError):
                    regression.grade(run, output)
                grader.assert_not_called()

    def test_submission_symlink_refused_before_grading(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            run = folder / 'turn.json'
            run.write_text(json.dumps(metadata()))
            (folder / 'ledger.py').symlink_to(run)
            with patch.object(regression, 'grade_ledger') as grader:
                with self.assertRaises(OSError):
                    regression.grade(run, folder / 'result.json')
                grader.assert_not_called()

    def test_compare_reports_repair_cost_and_rejects_changed_conditions(self):
        with tempfile.TemporaryDirectory() as directory:
            baseline, candidate = (Path(directory) / name for name in ('baseline', 'candidate'))
            for folder in (baseline, candidate):
                folder.mkdir()

            def save(folder, turn, model, check):
                row = metadata(turn)
                row['model']['id'] = model
                row.update(max_turns=3, benchmark_digest='1' * 64, submission_digest='2' * 64,
                           grading_profile={'cpu': 1}, checks={'replay': check})
                regression.write_result(folder / f'{turn}.json', row)

            save(baseline, 1, 'a', 'passed')
            save(candidate, 1, 'b', 'failed')
            save(candidate, 2, 'b', 'passed')
            report = regression.compare(baseline, candidate)
            self.assertEqual(report['candidate']['first_pass']['rate'], 0)
            self.assertEqual(report['candidate']['final_pass']['rate'], 1)
            self.assertEqual(report['candidate']['trials']['trial-01']['turns_to_pass'], 2)
            pair = report['paired_trials']['trial-01']
            self.assertEqual(pair['check_changes_by_turn'][1], {'replay': ['passed', 'failed']})
            self.assertEqual(pair['successful_trial_delta']['elapsed_ms'], 30)
            self.assertIsNone(pair['successful_trial_delta']['cached_input_tokens'])
            path = candidate / '2.json'
            row = json.loads(path.read_text())
            row['settings']['temperature'] = 1
            path.write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError, 'settings'):
                regression.compare(baseline, candidate)

    def test_missing_exhausted_and_error_turns(self):
        def row(turn, check):
            return metadata(turn) | {'checks': {'check': check}, 'max_turns': 3}

        self.assertEqual(regression.trial_summary([row(2, 'passed')])['final'], 'incomplete')
        self.assertEqual(regression.trial_summary([row(1, 'failed')])['final'], 'incomplete')
        self.assertEqual(regression.trial_summary([row(n, 'failed') for n in (3, 1, 2)])['final'], 'failed')
        self.assertEqual(regression.trial_summary([row(1, 'error')])['final'], 'error')
        with self.assertRaises(ValueError):
            regression.trial_summary([row(1, 'passed'), row(2, 'passed')])

    def test_preflight_failure_stops_before_container(self):
        from scripts import isolated
        from codex_eval.regression_grader import grade_ledger

        with patch.object(isolated, 'verify_machine', side_effect=RuntimeError), patch.object(isolated, 'container') as container:
            checks, profile, _ = grade_ledger({'fixture': {}}, b'example')
        self.assertEqual(checks, {'fixture': 'error'})
        self.assertIsNone(profile)
        container.assert_not_called()

    def test_protected_fixture_change_fails_otherwise_correct_submission(self):
        from base64 import b64encode

        case = {'ledger': [], 'batch': [], 'final': [], 'steps': [{'command': 'apply', 'balances': {}}]}
        files, _ = payload_for(case, b'# submission')
        result = {'steps': [[0, '{}']], 'ledger': b64encode(b'[]').decode(),
                  'protected': {name: digest(files[name]) for name in ('ledger.py', 'batch.json')}}
        self.assertTrue(passed(case, files, result))
        result['protected']['batch.json'] = None
        self.assertFalse(passed(case, files, result))
