"""Explicit, file-based model regression commands."""
from itertools import islice
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from .filesystem_grader import grade_filesystem
from .regression_grader import digest, encode, grade_ledger

ROOT = Path(__file__).resolve().parents[1] / 'regression' / 'benchmarks'
SCHEMA = 1
MAX_TURNS = 5
MAX_RESULTS = 1000
METRICS = ('input_tokens', 'output_tokens', 'cached_input_tokens', 'elapsed_ms')


def read_file(path, limit):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Expected a regular file')
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Input exceeds size limit')
    return data


def write_result(path, result):
    # Publish a complete file atomically and let an existing result win a race.
    with tempfile.NamedTemporaryFile(dir=path.parent) as stream:
        stream.write(json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False).encode() + b'\n')
        stream.flush()
        os.fsync(stream.fileno())
        os.link(stream.name, path, follow_symlinks=False)


def label(value):
    return isinstance(value, str) and 0 < len(value) <= 160 and value.isprintable()


def trial_metadata(turn):
    if not isinstance(turn, dict) or not isinstance(turn.get('model'), dict) or not isinstance(turn.get('metrics', {}), dict):
        raise ValueError('Invalid trial metadata')
    model = turn['model']
    metrics = {key: turn.get('metrics', {}).get(key) for key in METRICS}
    if (type(turn['schema']) is not int or turn['schema'] != SCHEMA
            or not label(turn['trial_id']) or not label(turn['harness'])
            or type(turn['turn']) is not int or not 1 <= turn['turn'] <= MAX_TURNS
            or not all(label(model[key]) for key in ('provider', 'id', 'evidence'))
            or (model.get('revision') is not None and not label(model['revision']))
            or not isinstance(turn['settings'], dict)
            or any(value is not None and (type(value) is not int or not 0 <= value < 2**53)
                   for value in metrics.values())):
        raise ValueError('Invalid trial metadata')
    if (metrics['cached_input_tokens'] is not None and metrics['input_tokens'] is not None
            and metrics['cached_input_tokens'] > metrics['input_tokens']):
        raise ValueError('Cached input exceeds input tokens')
    return dict(schema=SCHEMA, trial_id=turn['trial_id'], turn=turn['turn'],
                model={key: model.get(key) for key in ('provider', 'id', 'evidence', 'revision')},
                harness=turn['harness'], settings=turn['settings'], metrics=metrics)


def benchmark_definition(benchmark_id, protocol):
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*-v[1-9][0-9]*', benchmark_id):
        raise ValueError('Unknown benchmark')
    benchmark_path = ROOT / benchmark_id
    assets = {name: read_file(benchmark_path / name, 65536)
              for name in ('benchmark.json', 'prompt.md')}
    benchmark = json.loads(assets['benchmark.json'])
    initial_prompt = assets['prompt.md'].decode()
    if benchmark['grader'] == 'ledger-cli-v1':
        assets['ledger.py'] = read_file(benchmark_path / 'ledger.py', 65536)
        initial_prompt = (initial_prompt.rstrip() + '\n\nOriginal ledger.py:\n\n'
                          + '```python\n' + assets['ledger.py'].decode().rstrip() + '\n```\n')
    identity = {key: digest(data) for key, data in assets.items()}
    protocols = benchmark.get('protocols')
    if protocols is not None:
        if protocol not in protocols:
            raise ValueError('Select a protocol defined by the benchmark')
        selected = protocols[protocol]
        if 'prompt_file' in selected:
            name = selected['prompt_file']
            if not re.fullmatch(r'[a-z0-9-]+\.md', name):
                raise ValueError('Invalid protocol prompt file')
            initial_prompt = read_file(benchmark_path / name, 65536).decode()
        identity['protocol'] = protocol
        identity['initial_prompt'] = digest(initial_prompt.encode())
    elif protocol is not None:
        raise ValueError('This benchmark has no selectable protocols')
    info = {'benchmark': benchmark_id, 'benchmark_digest': digest(encode(identity)),
            'initial_prompt': initial_prompt, 'max_turns': benchmark['max_turns']}
    if protocol is not None:
        info['protocol'] = protocol
    return benchmark, info


def protocol_info(benchmark_id, protocol):
    return benchmark_definition(benchmark_id, protocol)[1]


def submission_grader(name):
    graders = {'ledger-cli-v1': ('ledger.py', grade_ledger),
               'filesystem-organize-v1': ('organize.py', grade_filesystem)}
    if name not in graders:
        raise ValueError('Unknown benchmark grader')
    return graders[name]


def grade(run_path, output):
    if os.path.lexists(output):
        raise ValueError('Result already exists')
    turn = json.loads(read_file(run_path, 65536))
    result = trial_metadata(turn)
    protocol = turn.get('protocol')
    benchmark, info = benchmark_definition(turn['benchmark'], protocol)
    filename, grader = submission_grader(benchmark['grader'])
    if (type(benchmark['max_turns']) is not int
            or not result['turn'] <= benchmark['max_turns'] <= MAX_TURNS or not benchmark['checks']):
        raise ValueError('Invalid benchmark grader, checks, or turn limit')
    submission = read_file(run_path.parent / filename, 65536)
    if not submission:
        raise ValueError('Empty submission')
    encode(result)  # Reject nonfinite metadata before running any code.
    checks, profile, grading_ms = grader(benchmark['checks'], submission)
    result.update(benchmark=turn['benchmark'], max_turns=benchmark['max_turns'],
                  benchmark_digest=info['benchmark_digest'],
                  submission_digest=digest(submission), grading_profile=profile,
                  grading_ms=grading_ms, checks=checks)
    if protocol is not None:
        result['protocol'] = protocol
    failed = [name for name, status in checks.items() if status == 'failed']
    status = outcome(result)
    feedback = benchmark['repair_prompt'] if status == 'failed' and result['turn'] < result['max_turns'] else None
    if feedback and protocol is not None:
        hints = benchmark['protocols'][protocol].get('repair_hints', {})
        if hints:
            feedback += '\n' + '\n'.join(f'- {name}: {hints[name]}' for name in failed)
        else:
            feedback += '\nFailed checks: ' + ', '.join(failed) + '.'
    write_result(output, result)
    return {'result': str(output), 'status': status, 'failed_checks': failed, 'repair_prompt': feedback}


def outcome(result):
    statuses = set(result['checks'].values())
    return 'error' if 'error' in statuses else 'failed' if 'failed' in statuses else 'passed'


def same(values, field):
    if len({encode(value) for value in values}) != 1:
        raise ValueError(f'Inconsistent {field}')


def load_trials(directory):
    if not directory.is_dir():
        raise ValueError('Expected a result directory')
    with os.scandir(directory) as entries:
        names = (entry.name for entry in entries if entry.name.endswith('.json'))
        names = sorted(islice(names, MAX_RESULTS + 1))
    if not names or len(names) > MAX_RESULTS:
        raise ValueError('Expected between 1 and 1,000 result files in each directory')
    trials = {}
    for name in names:
        row = json.loads(read_file(directory / name, 131072))
        row.update(trial_metadata(row))
        if (type(row['max_turns']) is not int or not row['turn'] <= row['max_turns'] <= MAX_TURNS
                or not label(row['benchmark']) or not isinstance(row['checks'], dict) or not row['checks']
                or not all(re.fullmatch('[0-9a-f]{64}', row[field])
                           for field in ('submission_digest', 'benchmark_digest'))
                or not set(row['checks'].values()) <= {'passed', 'failed', 'error'}
                or (row['grading_profile'] is None and outcome(row) != 'error')
                or (row['grading_profile'] is not None and not isinstance(row['grading_profile'], dict))):
            raise ValueError('Invalid result')
        trials.setdefault(row['trial_id'], []).append(row)
    return trials


def trial_summary(rows):
    rows = sorted(rows, key=lambda row: row['turn'])
    if (len({row['turn'] for row in rows}) != len(rows)
            or any(outcome(row) != 'failed' for row in rows[:-1])):
        raise ValueError('Duplicate turns or submissions after trial stopped')
    if [row['turn'] for row in rows] != list(range(1, len(rows) + 1)):
        return {'first': None, 'final': 'incomplete', 'turns_to_pass': None}
    last = rows[-1]
    final = outcome(last)
    if final == 'failed' and last['turn'] < last['max_turns']:
        final = 'incomplete'
    return {'first': outcome(rows[0]), 'final': final,
            'turns_to_pass': last['turn'] if final == 'passed' else None}


def compare(baseline_dir, candidate_dir):
    sides = [load_trials(directory) for directory in (baseline_dir, candidate_dir)]
    all_rows = [row for side in sides for rows in side.values() for row in rows]
    for key in ('benchmark', 'benchmark_digest', 'max_turns', 'harness', 'settings'):
        same([row[key] for row in all_rows], key)
    same([row.get('protocol') for row in all_rows], 'protocol')
    same([sorted(row['checks']) for row in all_rows], 'required checks')
    profiles = [row['grading_profile'] for row in all_rows if row['grading_profile'] is not None]
    if profiles:
        same(profiles, 'grading profile')
    paired = sorted(sides[0].keys() & sides[1].keys())
    summaries = []
    for side in sides:
        models = [row['model'] for rows in side.values() for row in rows]
        same([tuple(model[key] for key in ('provider', 'id', 'revision')) for model in models], 'model on one side')
        trials = {trial: trial_summary(rows) for trial, rows in side.items()}
        matched = {trial: trials[trial] for trial in paired}
        summaries.append({'model': models[0], 'revision_unresolved': models[0]['revision'] is None,
                          'trials': trials, 'first_pass': counts(matched, 'first'),
                          'final_pass': counts(matched, 'final')})
    pairs = {}
    for trial in paired:
        turns = [{row['turn']: row for row in side[trial]} for side in sides]
        checks = {turn: check_changes(turns[0][turn], turns[1][turn])
                  for turn in sorted(turns[0].keys() & turns[1].keys())}
        delta = None
        if all(side['trials'][trial]['final'] == 'passed' for side in summaries):
            totals = [{metric: metric_total(rows.values(), metric) for metric in METRICS}
                      for rows in turns]
            delta = {metric: totals[1][metric] - totals[0][metric]
                     if all(total[metric] is not None for total in totals) else None
                     for metric in METRICS}
        pairs[trial] = {'check_changes_by_turn': checks, 'successful_trial_delta': delta}
    report = {'benchmark': all_rows[0]['benchmark'], 'benchmark_digest': all_rows[0]['benchmark_digest'],
            'baseline': summaries[0],
            'candidate': summaries[1], 'paired_trials': pairs,
            'baseline_only': sorted(sides[0].keys() - sides[1].keys()),
            'candidate_only': sorted(sides[1].keys() - sides[0].keys())}
    if all_rows[0].get('protocol') is not None:
        report['protocol'] = all_rows[0]['protocol']
    return report


def counts(trials, key):
    values = [trial[key] for trial in trials.values()]
    passed = values.count('passed')
    graded = passed + values.count('failed')
    return {'passed': passed, 'graded': graded, 'trials': len(values),
            'rate': passed / graded if graded else None}


def check_changes(left, right):
    return {name: [status, right['checks'][name]] for name, status in left['checks'].items()
            if right['checks'][name] != status}


def metric_total(rows, metric):
    values = [row.get('metrics', {}).get(metric) for row in rows]
    return sum(values) if all(value is not None for value in values) else None
