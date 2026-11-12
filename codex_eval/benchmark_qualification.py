"""Verify known-good and deliberately incorrect synthetic submissions."""
from . import regression


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('Qualification mutation no longer matches the reference')
    return source.replace(old, new, 1)


def qualify(benchmark, protocol):
    definition, info = regression.benchmark_definition(benchmark, protocol)
    _, grade = regression.submission_grader(definition['grader'])
    checks = definition['checks']
    if benchmark not in ('ledger-v2', 'filesystem-v1'):
        raise ValueError('Qualification is available for ledger-v2 and filesystem-v1')
    reference = regression.read_file(regression.ROOT / benchmark / 'reference.py', 65536)
    probes = {
        'reference': (reference, set()),
        'reject_everything': (b'raise SystemExit(1)\n', set(checks)),
    }
    if benchmark == 'ledger-v2':
        probes['accept_boolean_amount'] = (
            replace_once(reference, b"type(row['amount_cents']) is not int",
                         b"not isinstance(row['amount_cents'], int)"),
            {'malformed_row_rollback'},
        )
    else:
        probes['overwrite_collision'] = (
            replace_once(reference, b'while target.exists() or target.is_symlink():', b'while False:'),
            {'collisions_keep_every_file'},
        )
        probes['delete_protected_file'] = (
            reference + b"\n    for file in (Path(sys.argv[1]) / 'protected').iterdir():\n        file.unlink()\n",
            set(checks),
        )
    results, profiles = {}, []
    for name, (submission, failures) in probes.items():
        outcomes, profile, grading_ms = grade(checks, submission)
        expected = {key: 'failed' if key in failures else 'passed' for key in checks}
        if outcomes != expected:
            raise ValueError(f'Qualification failed for {name}: {outcomes}')
        profiles.append(profile)
        results[name] = {'checks': outcomes, 'submission_digest': regression.digest(submission),
                         'grading_ms': grading_ms}
    regression.same(profiles, 'qualification grading profile')
    return {'benchmark': benchmark, 'protocol': protocol, 'benchmark_digest': info['benchmark_digest'],
            'grading_profile': profiles[0], 'probes': results}
