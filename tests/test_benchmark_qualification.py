import unittest
from unittest.mock import patch

from codex_eval import benchmark_qualification, regression


class BenchmarkQualificationTests(unittest.TestCase):
    def test_rejects_false_credit_for_invalid_input(self):
        def gives_credit_for_everything(checks, submission):
            return dict.fromkeys(checks, 'passed'), {'image': 'dummy'}, 1

        with patch.object(regression, 'grade_ledger', side_effect=gives_credit_for_everything):
            with self.assertRaisesRegex(ValueError, 'reject_everything'):
                benchmark_qualification.qualify('ledger-v2', 'independent')
