"""Run an explicit benchmark and resume at completed trial boundaries."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
from statistics import median
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

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


def trial_diagnostics(results):
    first = [min(rows, key=lambda row: row['turn']) for rows in results.values()]
    final = [max(rows, key=lambda row: row['turn']) for rows in results.values()]
    checks = {
        phase: {name: regression.counts(
            {row['trial_id']: row['checks'] for row in rows}, name)
            for name in rows[0]['checks']}
        for phase, rows in (('first_turn', first), ('final_turn', final))
    }
    timings = {'zero_cached_input': [], 'cache_hit': [], 'cache_unknown': []}
    for row in first:
        metrics = row['metrics']
        cached, elapsed = metrics['cached_input_tokens'], metrics['elapsed_ms']
        if elapsed is None:
            continue
        if cached is None:
            group = 'cache_unknown'
        elif cached == 0:
            group = 'zero_cached_input'
        else:
            group = 'cache_hit'
        timings[group].append(elapsed)
    return {
        'check_pass_rates': checks,
        'first_turn_latency_ms': {
            group: {'samples': len(samples), 'median': median(samples) if samples else None,
                    'min': min(samples, default=None), 'max': max(samples, default=None)}
            for group, samples in timings.items()
        },
        'grading_ms': sum(row['grading_ms'] for rows in results.values() for row in rows),
    }


def run_trial(trial, attempt, manifest, protocol, filename, infer, profile):
    history = [{'role': 'user', 'content': protocol['initial_prompt']}]
    for turn in range(1, protocol['max_turns'] + 1):
        with tempfile.TemporaryDirectory(prefix='eval-submission-') as directory:
            work = Path(directory)
            start = time.monotonic()
            reply, metrics = infer(manifest['model'], history, manifest['settings'])
            elapsed = round((time.monotonic() - start) * 1000)
            code = reply.strip()
            fence = re.fullmatch(r'```(?:python|py)?\s*\n(.*?)\n```', code, re.DOTALL | re.IGNORECASE)
            if fence:
                code = fence.group(1)
            (work / filename).write_text(code + '\n', encoding='utf-8')
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


def run(spec_path, output, baseline=None, resume=False, *, keychain=False, start_sandbox=False):
    from scripts import isolated

    spec = spec_path if isinstance(spec_path, dict) else read_json(spec_path, 16384)
    if not isinstance(spec, dict) or set(spec) - {
        'benchmark', 'protocol', 'harness', 'model', 'revision', 'trials', 'reasoning_effort'
    }:
        raise ValueError('Invalid benchmark run spec')
    if resume and output is None:
        raise ValueError('Supply --output with the existing run directory when resuming')
    if keychain and spec['harness'] != 'codex':
        raise ValueError('--keychain requires the Codex harness')
    definition, protocol = regression.benchmark_definition(spec['benchmark'], spec.get('protocol'))
    count = spec.get('trials', 3)
    if type(count) is not int or not 1 <= count or count * protocol['max_turns'] > regression.MAX_RESULTS:
        raise ValueError('The planned run exceeds the grade-file limit')
    if start_sandbox:
        try:
            isolated.start_machine()
        except FileNotFoundError as exc:
            raise ValueError('Dedicated eval-sandbox setup is missing. See docs/regression-setup.md') from exc
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            raise ValueError(f'Dedicated eval-sandbox could not start. See docs/regression-setup.md.\n{exc}') from exc
    filename, grader = regression.submission_grader(definition['grader'])
    probe = next(iter(definition['checks']))
    checks, profile, _ = grader({probe: definition['checks'][probe]}, b'raise SystemExit(1)\n')
    if checks[probe] == 'error':
        raise ValueError('Verified grader preflight failed. Check the staged image and sandbox setup')
    model, harness, settings, infer = select_harness(spec, keychain=keychain)
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

    if output is None:
        results = regression.results_directory(isolated.RUNTIME.parent / 'regression', protocol['benchmark'])
        output = results / f'{protocol["benchmark"]}-{uuid4().hex[:12]}'
    if not resume:
        output.mkdir(mode=0o700, parents=True)
    with locked(output):
        metadata = output / 'run.json'
        if resume:
            if read_json(metadata) != record:
                raise ValueError('Resume requires the same spec, model and benchmark conditions')
        else:
            regression.write_result(metadata, record)
        print(f'Regression results: {output.absolute()}', file=sys.stderr, flush=True)
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
        all_rows = [row for rows in results.values() for row in rows]
        report['metrics'] = {metric: regression.metric_total(all_rows, metric)
                             for metric in regression.METRICS}
        report['checks_by_trial'] = {
            trial: {str(row['turn']): row['checks'] for row in sorted(rows, key=lambda row: row['turn'])}
            for trial, rows in results.items()
        }
        report['diagnostics'] = trial_diagnostics(results)
        if baseline is not None:
            if regression.digest(regression.encode(baseline_rows(baseline))) != baseline_digest:
                raise ValueError('Baseline changed during the run')
            report['comparison'] = regression.compare(baseline, grades)
        summary_path = output / 'summary.json'
        if os.path.lexists(summary_path):
            saved = read_json(summary_path, 2 * 1024 * 1024)
            expected = report.copy()
            for field in ('metrics', 'checks_by_trial', 'diagnostics'):
                if field not in saved:
                    expected.pop(field)
            if 'comparison' in expected and 'verdict' not in saved.get('comparison', {}):
                expected['comparison'] = {key: value for key, value in report['comparison'].items()
                                          if key != 'verdict'}
            if regression.encode(saved) != regression.encode(expected):
                raise ValueError('Saved summary differs from completed grades')
        else:
            regression.write_result(summary_path, report)
        first, final = report['first_pass'], report['final_pass']
        print(f'{protocol["benchmark"]} | first turn {first["passed"]}/{count} | '
              f'final {final["passed"]}/{count}', file=sys.stderr)
        metrics = report['metrics']
        elapsed = metrics['elapsed_ms']
        timing = f'{elapsed / 1000:.1f} s' if elapsed is not None else 'unavailable'
        cached, inputs = metrics['cached_input_tokens'], metrics['input_tokens']
        cache_usage = 'unavailable' if cached is None else str(cached)
        if cached is not None and inputs:
            cache_usage += f' ({cached / inputs:.1%})'
        print(f'Inference across all turns | {timing} | '
              f'input tokens {metrics["input_tokens"] if metrics["input_tokens"] is not None else "unavailable"} | '
              f'cached input tokens {cache_usage} | '
              f'output tokens {metrics["output_tokens"] if metrics["output_tokens"] is not None else "unavailable"}',
              file=sys.stderr)
        if 'comparison' in report:
            comparison = report['comparison']
            previous = comparison['baseline']
            print(f'Baseline verdict | {comparison["verdict"]} | '
                  f'baseline first turn {previous["first_pass"]["passed"]}/{count} | '
                  f'baseline final {previous["final_pass"]["passed"]}/{count}', file=sys.stderr, flush=True)
        else:
            print('Baseline verdict | no baseline supplied', file=sys.stderr, flush=True)
        return report
