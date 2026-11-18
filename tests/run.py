"""Run the host or isolated test profile."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from _environment import expected_environment, test_environment


def choose_environment(detected, expected):
    if expected in ('auto', detected):
        return detected
    print(f'Configured test environment: {expected}. Detected environment: {detected}.')
    while True:
        choice = input('Which test profile should run? Enter host or isolated: ').strip().lower()
        if choice in ('host', 'isolated'):
            return choice


def run_isolated(magen):
    from scripts import isolated

    if magen is None:
        path = input('Path to the reviewed MAGEN checkout for isolated acceptance tests: ').strip()
        if not path:
            raise ValueError('Supply a MAGEN checkout path to run isolated acceptance tests')
        magen = Path(path).expanduser()
    for name in ('detectors.py', 'types.py'):
        if not (magen / 'gateway' / name).is_file():
            raise ValueError(f'Missing reviewed MAGEN source: {magen / "gateway" / name}')
    isolated.start_machine()
    isolated.run_tests(magen, export=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--magen', type=Path, help='Reviewed MAGEN checkout for isolated acceptance tests')
    args = parser.parse_args()
    tests = Path(__file__).resolve().parent
    sys.path.insert(0, str(tests.parent))
    try:
        detected = test_environment()
        environment = choose_environment(detected, expected_environment())
        if environment == 'isolated' and detected == 'host':
            run_isolated(args.magen)
            return 0
    except EOFError:
        sys.exit('Input ended before a choice was supplied. Run interactively or pipe in your choice.')
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
    print(f'Test environment: {environment}', flush=True)
    os.environ['EVAL_TEST_ENVIRONMENT'] = environment
    tempfile.tempdir = str(Path(tempfile.gettempdir()).resolve())
    suite = unittest.defaultTestLoader.discover(str(tests))
    return not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()


if __name__ == '__main__':
    sys.exit(main())
