"""Run an explicit benchmark and resume at completed trial boundaries."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

from . import regression
from .benchmark_harness import ollama_model, select_harness


@contextmanager
def locked(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('This run directory is in use') from exc
        yield
    finally:
        os.close(fd)


def read_json(path, limit=131072):
    return json.loads(regression.read_file(path, limit))


def baseline_rows(path):
    rows = regression.load_trials(path)
    if any(regression.trial_summary(trial)['final'] not in ('passed', 'failed') for trial in rows.values()):
        raise ValueError('Use a complete baseline')
    return rows


def publish_grades(trial, grades):
    for path in sorted(trial.glob('*.json')):
        target = grades / path.name
        record = read_json(path)
        if os.path.lexists(target):
            if read_json(target) != record:
                raise ValueError('Published grade differs from its completed trial')
        else:
            regression.write_result(target, record)


def run_trial(trial, attempt, manifest, protocol, filename, infer, profile):
    history = [{'role': 'user', 'content': protocol['initial_prompt']}]
    for turn in range(1, protocol['max_turns'] + 1):
        with tempfile.TemporaryDirectory(prefix='eval-submission-') as directory:
            work = Path(directory)
            start = time.monotonic()
            reply, metrics = infer(manifest['model'], history, manifest['settings'])
            code = reply.strip()
            fence = re.fullmatch(r'```(?:python|py)?\s*\n(.*?)\n```', code, re.DOTALL | re.IGNORECASE)
            if fence:
                code = fence.group(1)
            (work / filename).write_text(code + '\n', encoding='utf-8')
            elapsed = round((time.monotonic() - start) * 1000)
            run_file = work / 'turn.json'
            regression.write_result(run_file, manifest | {'turn': turn, 'trial_id': trial,
                                    'metrics': metrics | {'elapsed_ms': elapsed}})
            output = attempt / f'{trial}-turn-{turn}.json'
            feedback = regression.grade(run_file, output)
        grade = read_json(output)
        if (feedback['status'] == 'error' or grade['grading_profile'] != profile
                or grade['benchmark_digest'] != protocol['benchmark_digest']):
            raise ValueError('Grading failed or benchmark conditions changed')
        if feedback['repair_prompt'] is None:
            return
        repair = feedback['repair_prompt']
        if manifest['protocol'] is None:
            repair += '\nFailed checks: ' + ', '.join(feedback['failed_checks']) + '.'
        history.extend([{'role': 'assistant', 'content': reply}, {'role': 'user', 'content': repair}])


def run(spec_path, output, baseline=None, resume=False):
    spec = read_json(spec_path, 16384)
    if not isinstance(spec, dict) or set(spec) - {
        'benchmark', 'protocol', 'harness', 'model', 'revision', 'trials', 'reasoning_effort'
    }:
        raise ValueError('Invalid benchmark run spec')
    definition, protocol = regression.benchmark_definition(spec['benchmark'], spec.get('protocol'))
    count = spec.get('trials', 3)
    if type(count) is not int or not 1 <= count or count * protocol['max_turns'] > regression.MAX_RESULTS:
        raise ValueError('The planned run exceeds the grade-file limit')
    filename, grader = regression.submission_grader(definition['grader'])
    probe = next(iter(definition['checks']))
    checks, profile, _ = grader({probe: definition['checks'][probe]}, b'raise SystemExit(1)\n')
    if checks[probe] == 'error':
        raise ValueError('Verified grader preflight failed')
    model, harness, settings, infer = select_harness(spec)
    manifest = {'schema': 1, 'benchmark': protocol['benchmark'], 'protocol': spec.get('protocol'),
                'model': model, 'harness': harness, 'settings': settings}
    trials = [f'trial-{index:02}' for index in range(1, count + 1)]
    baseline_digest = None
    if baseline is not None:
        saved = baseline_rows(baseline)
        if sorted(saved) != trials:
            raise ValueError('Baseline trial IDs must match the planned run')
        for rows in saved.values():
            for row in rows:
                for key, expected in {'benchmark': manifest['benchmark'], 'protocol': manifest['protocol'],
                                      'benchmark_digest': protocol['benchmark_digest'], 'harness': harness,
                                      'settings': settings, 'grading_profile': profile}.items():
                    if row.get(key) != expected:
                        raise ValueError(f'Baseline differs in {key}')
        baseline_digest = regression.digest(regression.encode(saved))
    record = {'spec': spec, 'manifest': manifest, 'protocol': protocol, 'grading_profile': profile,
              'baseline_digest': baseline_digest, 'trials': trials}

    if not resume:
        output.mkdir(mode=0o700, parents=True)
    with locked(output):
        metadata = output / 'run.json'
        if resume:
            if read_json(metadata) != record:
                raise ValueError('Resume requires the same spec, model and benchmark conditions')
        else:
            regression.write_result(metadata, record)
        attempts, completed, grades = (output / name for name in ('attempts', 'completed', 'grades'))
        for directory in (attempts, completed, grades):
            if directory.is_symlink():
                raise ValueError('Run directories must not be symlinks')
            directory.mkdir(exist_ok=True, mode=0o700)
        for trial in trials:
            destination = completed / trial
            if destination.is_symlink():
                raise ValueError('Completed trial must not be a symlink')
            if not destination.is_dir():
                print(f'Running {trial}', file=sys.stderr, flush=True)
                attempt = Path(tempfile.mkdtemp(prefix=f'{trial}-', dir=attempts))
                run_trial(trial, attempt, manifest, protocol, filename, infer, profile)
                if harness == 'local-ollama-text-v1' and ollama_model(model['id']) != model:
                    raise ValueError('Ollama model revision changed during the trial')
                attempt.rename(destination)
            publish_grades(destination, grades)
        results = regression.load_trials(grades)
        summary = {trial: regression.trial_summary(rows) for trial, rows in results.items()}
        if sorted(summary) != trials or any(row['final'] not in ('passed', 'failed') for row in summary.values()):
            raise ValueError('Completed grades do not match the planned trials')
        report = {'benchmark': protocol['benchmark'], 'model': model, 'trials': summary,
                  'first_pass': regression.counts(summary, 'first'), 'final_pass': regression.counts(summary, 'final')}
        if baseline is not None:
            if regression.digest(regression.encode(baseline_rows(baseline))) != baseline_digest:
                raise ValueError('Baseline changed during the run')
            report['comparison'] = regression.compare(baseline, grades)
        summary_path = output / 'summary.json'
        if os.path.lexists(summary_path):
            if regression.encode(read_json(summary_path, 2 * 1024 * 1024)) != regression.encode(report):
                raise ValueError('Saved summary differs from completed grades')
        else:
            regression.write_result(summary_path, report)
        return report
