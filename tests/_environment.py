"""Select the test profile from the running environment or an explicit expectation."""
import os
from pathlib import Path
import sys
import unittest


def expected_environment():
    expected = os.environ.get('EVAL_TEST_ENVIRONMENT', 'auto')
    if expected not in {'auto', 'host', 'isolated'}:
        raise ValueError('EVAL_TEST_ENVIRONMENT must be auto, host, or isolated')
    return expected


def test_environment():
    staged = Path(__file__).resolve().parent == Path('/work/tests')
    if sys.platform == 'linux' and staged and Path('/run/.containerenv').is_file():
        return 'isolated'
    return 'host'


def isolated_only(test):
    return unittest.skipUnless(test_environment() == 'isolated' and expected_environment() != 'host',
                               'requires the dedicated isolated test runner')(test)
