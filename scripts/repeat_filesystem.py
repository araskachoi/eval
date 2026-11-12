#!/usr/bin/env python3
"""Repeat a filesystem benchmark against the same local Ollama model revision."""
import argparse
import http.client
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from codex_eval import regression
from codex_eval.filesystem_grader import grade_filesystem

METRICS = {'prompt_eval_count': 'input_tokens', 'eval_count': 'output_tokens',
           'prompt_eval_cached_count': 'cached_input_tokens'}
RECEIPT_FIELDS = (*METRICS, 'model', 'created_at', 'done_reason', 'total_duration',
                  'load_duration', 'prompt_eval_duration', 'eval_duration')


def local_request(path, payload=None):
    connection = http.client.HTTPConnection('127.0.0.1', 11434, timeout=150)
    try:
        if payload is None:
            connection.request('GET', path)
        else:
            connection.request('POST', path, json.dumps(payload), {'Content-Type': 'application/json'})
        response = connection.getresponse()
        data = response.read(1024 * 1024 + 1)
        if response.status != 200 or len(data) > 1024 * 1024:
            raise ValueError(f'Unexpected local Ollama response (HTTP {response.status})')
        return json.loads(data)
    finally:
        connection.close()


def verify_model(model, settings):
    if model['provider'] != 'ollama' or not re.fullmatch(r'[0-9a-f]{64}', model['revision'] or ''):
        raise ValueError('A resolved local Ollama model is required')
    installed = [item for item in local_request('/api/tags')['models'] if item['name'] == model['id']]
    if (len(installed) != 1 or installed[0]['digest'] != model['revision']
            or installed[0]['details']['format'] != 'gguf' or installed[0]['size'] <= 0):
        raise ValueError('Installed model does not match the baseline revision')
    if local_request('/api/version')['version'] != settings['ollama_version']:
        raise ValueError('Ollama version differs from the baseline')


def run_trial(trial, base, protocol, output):
    settings = base['settings']
    options = {key: settings[key] for key in ('temperature', 'num_ctx', 'num_predict')}
    messages = [{'role': 'user', 'content': protocol['initial_prompt']}]
    for turn in range(1, protocol['max_turns'] + 1):
        name = f'{trial}-{turn}'
        print(f'{trial}, turn {turn}: requesting local inference', flush=True)
        with tempfile.TemporaryDirectory(prefix='eval-filesystem-turn-') as work:
            work = Path(work)
            start = time.monotonic()
            response = local_request('/api/chat', {'model': base['model']['id'], 'messages': messages,
                                     'stream': False, 'keep_alive': settings['keep_alive'],
                                     'think': settings['think'], 'options': options})
            if response['model'] != base['model']['id'] or response['done'] is not True:
                raise ValueError('Unexpected model identity or incomplete response')
            reply = response['message']['content']
            code = reply.strip()
            fence = re.fullmatch(r'```(?:python|py)?\s*\n(.*?)\n```', code, re.DOTALL | re.IGNORECASE)
            if fence:
                code = fence.group(1)
            (work / 'organize.py').write_text(code + '\n', encoding='utf-8')
            elapsed = round((time.monotonic() - start) * 1000)
            metrics = {key: response[field] for field, key in METRICS.items() if field in response}
            metrics['elapsed_ms'] = elapsed
            manifest = {key: base[key] for key in ('schema', 'benchmark', 'protocol', 'model', 'harness', 'settings')}
            manifest.update(trial_id=trial, turn=turn, metrics=metrics)
            run_path = work / 'turn.json'
            regression.write_result(run_path, manifest)
            receipt = {key: response[key] for key in RECEIPT_FIELDS if key in response}
            receipt.update(elapsed_ms=elapsed, outer_fence_removed=bool(fence))
            regression.write_result(output / 'receipts' / (name + '.json'), receipt)
            result_path = output / 'grades' / (name + '.json')
            grade = regression.grade(run_path, result_path)
        result = json.loads(regression.read_file(result_path, 131072))
        if grade['status'] == 'error' or result['grading_profile'] != base['grading_profile']:
            raise ValueError('Grading failed or the verified sandbox profile changed')
        print(f'{trial}, turn {turn}: {grade["status"]}, '
              f'{metrics.get("input_tokens")} input / {metrics.get("output_tokens")} output, '
              f'{elapsed / 1000:.2f}s; failed={grade["failed_checks"]}', flush=True)
        if grade['repair_prompt'] is None:
            return
        messages.extend([{'role': 'assistant', 'content': reply},
                         {'role': 'user', 'content': grade['repair_prompt']}])


def repeat(baseline, output):
    if os.path.lexists(output):
        raise ValueError('Choose a new output directory')
    trials = regression.load_trials(baseline)
    rows = [row for trial in trials.values() for row in trial]
    base = rows[0]
    for key in ('benchmark', 'benchmark_digest', 'protocol', 'model', 'harness', 'settings', 'grading_profile'):
        regression.same([row[key] for row in rows], key)
    if (base['benchmark'], base['protocol'], base['harness'], base['settings']['outer_code_fence']) != (
        'filesystem-v1', 'independent', 'local-ollama-text-v1', 'unwrap one complete block'
    ):
        raise ValueError('Expected a filesystem-v1 local Ollama text baseline')
    for trial, results in trials.items():
        if (not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', trial)
                or regression.trial_summary(results)['final'] not in ('passed', 'failed')):
            raise ValueError('Baseline contains an invalid trial ID or unfinished trial')
    benchmark, protocol = regression.benchmark_definition(base['benchmark'], base['protocol'])
    if protocol['benchmark_digest'] != base['benchmark_digest']:
        raise ValueError('Benchmark digest differs from the baseline')
    verify_model(base['model'], base['settings'])

    # Exercise the actual workload boundary before sending any model prompt.
    probe = 'unrecognized_and_nested_unchanged'
    checks, profile, _ = grade_filesystem({probe: benchmark['checks'][probe]}, b'raise SystemExit(0)\n')
    if checks[probe] != 'passed' or profile != base['grading_profile']:
        raise ValueError('Filesystem sandbox preflight failed or differs from the baseline')

    output.mkdir(mode=0o700, parents=True)
    (output / 'grades').mkdir()
    (output / 'receipts').mkdir()
    regression.write_result(output / 'protocol.json', protocol | {'model': base['model'],
                            'harness': base['harness'], 'settings': base['settings']})
    for trial in sorted(trials):
        run_trial(trial, base, protocol, output)
    verify_model(base['model'], base['settings'])
    report = regression.compare(baseline, output / 'grades')
    regression.write_result(output / 'comparison.json', report)
    print(output / 'comparison.json', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True, help='Directory of saved turn-grade JSON files')
    parser.add_argument('--output', type=Path, required=True, help='New directory for grades, receipts, and comparison')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        repeat(args.baseline, args.output)
    except (ValueError, OSError, TypeError, KeyError, http.client.HTTPException) as exc:
        parser.exit(1, f'Filesystem repeat stopped: {exc}\n')


if __name__ == '__main__':
    main()
