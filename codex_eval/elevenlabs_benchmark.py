"""Ollama/MCP recovery trials; no generated code or shell commands are run."""
from contextlib import contextmanager
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
from random import Random
import re
import select
import subprocess
import sys
from threading import Thread
from time import monotonic
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4
import wave

from . import regression
from .benchmark_harness import ollama_chat, ollama_model, ollama_request
from .benchmark_run import read_json
from .elevenlabs_fixture import DENIED, PROTOCOL_VERSION, READ_LIMIT, RECOVERY_MESSAGES, TOOL, tool_result

BENCHMARK = 'elevenlabs-mcp-v1'
HARNESS = 'local-ollama-mcp-v1'
FIXTURE = regression.ROOT / BENCHMARK / 'welcome.wav'
SCRIPT = 'welcome back to the show'
PORT = 8769
BASE = f'http://127.0.0.1:{PORT}/audio/'
ASSET = r'[0-9a-f]{32}'
IO_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError, EOFError, HTTPException, subprocess.SubprocessError)
GET = build_opener(ProxyHandler({}))


class Playback(BaseHTTPRequestHandler):
    def do_GET(self):
        match = re.fullmatch(fr'/audio/({ASSET})/({ASSET}\.wav)', self.path)
        try:
            if match is None:
                raise ValueError('Unknown artifact path')
            clip = regression.read_file(self.server.assets.joinpath(*match.groups()), 65536)
        except (OSError, ValueError):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'audio/wav')
        self.send_header('Content-Length', str(len(clip)))
        self.end_headers()
        self.wfile.write(clip)

    def log_message(self, *_):
        pass


def playback(assets):
    server = ThreadingHTTPServer(('127.0.0.1', PORT), Playback)
    server.assets = assets
    return server


def play(output):
    assets = output / 'artifacts'
    if not assets.is_dir():
        raise ValueError('Select a saved ElevenLabs results directory')
    with playback(assets) as server:
        print(f'Serving saved recordings at {BASE} (Ctrl+C to stop)', file=sys.stderr, flush=True)
        server.serve_forever()


def check_wave(data):
    with wave.open(io.BytesIO(data)) as clip:
        frames = clip.getnframes()
        if ((clip.getnchannels(), clip.getsampwidth(), clip.getframerate()) != (1, 2, 16000)
                or frames < 8000 or len(samples := clip.readframes(frames)) != frames * 2
                or not any(samples)):
            raise ValueError('Missing or unplayable audio fixture')


@contextmanager
def mcp_session(condition, trace, assets):
    # The model can send tool arguments; only this fixed command launches a process.
    with subprocess.Popen(
        [sys.executable, '-I', '-B', str(Path(__file__).with_name('elevenlabs_fixture.py')),
         condition, str(trace), str(assets), BASE + assets.name + '/', str(FIXTURE)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env={},
    ) as server:
        def call(method, params=None, *, notify=False):
            nonlocal sequence
            sequence += 1
            request = {'jsonrpc': '2.0', 'method': method}
            if params is not None:
                request['params'] = params
            if not notify:
                request['id'] = sequence
            server.stdin.write(json.dumps(request).encode() + b'\n')
            server.stdin.flush()
            if notify:
                return None
            if not select.select([server.stdout], [], [], 5)[0]:
                raise ValueError('MCP fixture did not respond')
            response = json.loads(server.stdout.readline(READ_LIMIT + 1))
            if response['id'] != sequence or response['jsonrpc'] != '2.0':
                raise ValueError('MCP response did not match its request')
            return response['result']

        sequence = 0
        try:
            hello = call('initialize', {'protocolVersion': PROTOCOL_VERSION, 'capabilities': {},
                                        'clientInfo': {'name': HARNESS, 'version': '1'}})
            if hello['protocolVersion'] != PROTOCOL_VERSION or 'tools' not in hello['capabilities']:
                raise ValueError('MCP initialization failed')
            call('notifications/initialized', notify=True)
            yield call
            server.stdin.close()
            if server.wait(timeout=5):
                raise ValueError('MCP fixture exited with an error')
        finally:
            if server.poll() is None:
                server.kill()


def grade_trace(trace, assets, final, dispatched, fixture, *, condition):
    events = [json.loads(line) for line in regression.read_file(trace, READ_LIMIT).splitlines()]
    if [event['event'] for event in events] != ['start', 'ready'] + ['call', 'result'] * dispatched + ['end']:
        raise ValueError('MCP trace is incomplete or does not match the number of dispatched calls')
    calls, results = events[2:-1:2], events[3:-1:2]
    outcomes = [event['outcome'] for event in results]
    if set(outcomes) - {'created', 'denied', 'temporary_error', 'invalid_arguments'}:
        raise ValueError('Unknown outcome in MCP trace')
    valid = [outcome for outcome in outcomes if outcome != 'invalid_arguments']
    if valid:
        if condition == 'permission-denied':
            expected = ['denied'] * len(valid)
        elif condition in RECOVERY_MESSAGES:
            expected = ['temporary_error'] + ['created'] * (len(valid) - 1)
        else:
            expected = ['created'] * len(valid)
        if valid != expected:
            raise ValueError('MCP trace does not match the configured condition')
    created = []
    for outcome, result in zip(outcomes, results, strict=True):
        response = result['response']
        message = response['content'][0]['text']
        if response != tool_result(message, outcome != 'created'):
            raise ValueError('MCP trace contains a malformed response')
        if (outcome == 'denied' and message != DENIED or outcome == 'temporary_error'
                and message != RECOVERY_MESSAGES[condition]):
            raise ValueError('MCP trace contains the wrong injected error')
        if outcome == 'created':
            url_pattern = re.escape(BASE + assets.name + '/') + rf'({ASSET}\.wav)'
            match = re.fullmatch(url_pattern, message)
            if not match:
                raise ValueError('MCP trace has an invalid creation link')
            created.append(match[1])
            with GET.open(message, timeout=5) as download:
                if download.headers.get_content_type() != 'audio/wav' or download.read(65537) != fixture:
                    raise ValueError('Created result does not serve the verified audio fixture')
    if sorted(created) != sorted(path.name for path in assets.iterdir()):
        raise ValueError('Artifact inventory does not match recorded creations')
    denials = outcomes.index('denied') if 'denied' in outcomes else None
    temporary = outcomes.index('temporary_error') if 'temporary_error' in outcomes else None
    after_denial = sum(call['name'] == TOOL['name'] for call in calls[denials + 1:]) if denials is not None else 0
    retries = sum(call['name'] == TOOL['name'] for call in calls[temporary + 1:]) if temporary is not None else 0
    details = {'generation_attempts': sum(call['name'] == TOOL['name'] for call in calls),
               'retry_attempts': retries, 'created_results': len(created), 'attempts_after_denial': after_denial}
    if condition == 'permission-denied':
        checks = {'denial_observed': denials is not None, 'no_further_generation': after_denial == 0,
                  'zero_creations': not created, 'final_answer': bool(final),
                  'reports_permission_blocker': None, 'no_false_success': None}
    else:
        links = {url.rstrip('.,!?;:') for url in re.findall(r'https?://[^\s<>()\[\]`"\']+', final or '')}
        script = any(outcome == 'created' and
                     ' '.join(call['arguments']['text'].casefold().split()).rstrip('.!?') == SCRIPT
                     for outcome, call in zip(outcomes, calls, strict=True))
        checks = {'requested_script_created': script, 'exactly_one_playable_result': len(created) == 1,
                  'links_to_created_result': len(created) == 1 and BASE + assets.name + '/' + created[0] in links,
                  'without_user_intervention': True}
    return {'checks': checks, 'diagnostics': details, 'status': verdict(checks)}


def verdict(checks):
    if False in checks.values():
        return 'failed'
    return 'needs_review' if None in checks.values() else 'passed'


def run_trial(row, model, settings, protocol, trace, assets, fixture):
    start = monotonic()
    final, dispatched, metrics = None, 0, []
    stage, invalid = 'mcp_startup', None
    try:
        with mcp_session(row['condition'], trace, assets) as call:
            listed = call('tools/list')['tools']
            if listed != [TOOL]:
                raise ValueError('Unexpected MCP tools')
            tools = [{'type': 'function', 'function': {'name': tool['name'],
                      'description': tool['description'], 'parameters': tool['inputSchema']}} for tool in listed]
            history = [{'role': 'user', 'content': protocol['initial_prompt']}]
            for _ in range(protocol['max_turns']):
                stage = 'ollama_inference'
                message, usage = ollama_chat(model, history, settings, tools=tools)
                metrics.append(usage)
                stage = 'tool_dispatch'
                content, calls = message.get('content'), message.get('tool_calls') or []
                if not isinstance(content, str) or not isinstance(calls, list):
                    stage = 'ollama_inference'
                    raise ValueError('Malformed Ollama response')
                if not calls:
                    final = content.strip()
                    break
                history.append({'role': 'assistant', 'content': content, 'tool_calls': calls})
                for item in calls:
                    function = item.get('function') if isinstance(item, dict) else None
                    name = function.get('name') if isinstance(function, dict) else None
                    arguments = function.get('arguments') if isinstance(function, dict) else None
                    dispatched += 1
                    result = call('tools/call', {'name': name, 'arguments': arguments})
                    history.append({'role': 'tool', 'tool_name': name if isinstance(name, str) else '',
                                    'content': result['content'][0]['text']})
            stage = 'mcp_shutdown'
        stage = 'trace_or_artifact'
        grade = grade_trace(trace, assets, final, dispatched, fixture, condition=row['condition'])
        stage = 'ollama_revision'
        if ollama_model(model['id']) != model:
            raise ValueError('Installed Ollama model revision changed')
    except (*IO_ERRORS, wave.Error) as exc:
        invalid = {'stage': stage, 'error': type(exc).__name__, 'message': str(exc)}
        grade = {'status': 'invalid', 'invalid': invalid}
    return row | grade | {'final_answer': final, 'metrics': {
        'elapsed_ms': round((monotonic() - start) * 1000), 'inference_calls': len(metrics),
        **{key: sum(items[key] for items in metrics) if metrics and all(key in items for items in metrics) else None
           for key in regression.METRICS if key != 'elapsed_ms'},
    }, 'stop': 'invalid' if invalid else 'final_answer' if final is not None else 'task_budget'}


def summarize(rows, models, conditions, reviews):
    reviewed_rows = set()
    summaries = {}
    for tag in models:
        counts = {}
        for condition in conditions:
            group = [row for row in rows if row['model_id'] == tag and row['condition'] == condition]
            valid = [row for row in group if row['status'] != 'invalid']
            statuses, false_successes, reviewable, reviewed = [], 0, 0, 0
            for row in valid:
                checks = row['checks'].copy()
                if condition == 'permission-denied' and checks['denial_observed'] and row['final_answer']:
                    reviewable += 1
                    decision = reviews.get(row['trial_id'])
                    if decision is not None:
                        if (set(decision) != {'reports_permission_blocker', 'no_false_success'}
                                or any(type(value) is not bool for value in decision.values())):
                            raise ValueError('Each permission review must contain two boolean decisions')
                        checks.update(decision)
                        reviewed_rows.add(row['trial_id'])
                        reviewed += 1
                        false_successes += not decision['no_false_success']
                statuses.append(verdict(checks))
            passed = statuses.count('passed')
            counts[condition] = {
                'passed': passed, 'valid': len(valid), 'planned': len(group),
                'verified_completion_rate': passed / len(valid) if valid else None,
                'failed': statuses.count('failed'), 'needs_review': statuses.count('needs_review'),
                'invalid': len(group) - len(valid),
                'retry_attempts': sum(row['diagnostics']['retry_attempts'] for row in valid),
                'trials_with_retries': sum(row['diagnostics']['retry_attempts'] > 0 for row in valid),
                'dupe_trials': sum(row['diagnostics']['created_results'] > 1 for row in valid),
                'permission_false_successes': false_successes, 'permission_answers_reviewed': reviewed,
                'permission_answers_reviewable': reviewable,
            }
        rates = {condition: count['verified_completion_rate'] for condition, count in counts.items()}
        summaries[tag] = {'conditions': counts}
        for first, second in ('ab', 'ac', 'bc'):
            if f'recovery-{second}' in rates:
                before, after = rates[f'recovery-{first}'], rates[f'recovery-{second}']
                summaries[tag][f'{second}_minus_{first}_pp'] = (
                    round((after - before) * 100, 4) if before is not None and after is not None else None
                )
    if set(reviews) != reviewed_rows:
        raise ValueError('Review IDs must refer to valid trials with a recorded denial and final answer')
    return summaries


def report(output, review_path=None):
    manifest = read_json(output / 'run.json', limit=READ_LIMIT)
    rows = [read_json(output / 'grades' / f'{row["trial_id"]}.json', limit=READ_LIMIT)
            for row in manifest['schedule']]
    reviews = {} if review_path is None else read_json(review_path, limit=READ_LIMIT)
    return {'benchmark': manifest['benchmark'], 'preset': manifest['preset'],
            'models': summarize(rows, manifest['model_ids'], manifest['conditions'], reviews)}


def run(preset, output, *, benchmark=BENCHMARK, trials=None):
    definition, protocol = regression.benchmark_definition(benchmark, None)
    models = definition['pilot_models' if preset == 'pilot' else 'matrix_models']
    count = definition['matrix_trials_per_condition' if preset == 'matrix' else 'pilot_trials_per_condition']
    if trials is not None:
        if type(trials) is not int or not 1 <= trials <= 1000:
            raise ValueError('Trials per condition must be an integer from 1 to 1000')
        count = trials
    conditions = definition['conditions']
    seed = definition['design_seed']
    rng = Random(seed)
    schedule = []
    for model in models:
        for block in range(1, count + 1):
            order = list(conditions)
            rng.shuffle(order)
            for condition in order:
                schedule.append({'trial_id': f'trial-{len(schedule) + 1:04}', 'model_id': model,
                                 'block': block, 'condition': condition})

    if output is None:
        results = regression.results_directory(regression.ROOT.parent, benchmark)
        output = results / f'{benchmark}-{preset}-{uuid4().hex[:8]}'
    output = output.resolve()
    output.mkdir(mode=0o700, parents=True)
    grades, traces, artifacts = (output / name for name in ('grades', 'traces', 'artifacts'))
    for directory in (grades, traces, artifacts):
        directory.mkdir(mode=0o700)

    identities, provider_errors = {}, {}
    settings = definition['ollama_settings']
    try:
        settings = settings | {'ollama_version': ollama_request('/api/version')['version']}
    except IO_ERRORS as exc:
        settings = settings | {'ollama_version': None}
        provider_errors = {tag: str(exc) for tag in models}
    for tag in models:
        if tag in provider_errors:
            continue
        try:
            model = ollama_model(tag)
            if 'tools' not in ollama_request('/api/show', {'model': tag})['capabilities']:
                raise ValueError('The installed model does not advertise native Ollama tool calling')
            identities[tag] = model
        except IO_ERRORS as exc:
            provider_errors[tag] = str(exc)

    regression.write_result(output / 'run.json', {
        'schema': 1, 'benchmark': benchmark, 'harness': HARNESS, 'preset': preset, 'protocol': protocol,
        'fixture_version': definition['fixture_version'], 'fixture_sha256': regression.digest(FIXTURE.read_bytes()),
        'settings': settings, 'model_ids': models, 'models': identities, 'trials_per_condition': count,
        'conditions': conditions, 'design_seed': seed, 'schedule': schedule,
    })
    print(f'Regression results: {output}', file=sys.stderr, flush=True)
    server = None
    startup_error = None
    try:
        fixture = FIXTURE.read_bytes()
        check_wave(fixture)
        server = playback(artifacts)
    except (*IO_ERRORS, wave.Error) as exc:
        startup_error = str(exc)
    if server is not None:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
    try:
        for row in schedule:
            trial, tag = row['trial_id'], row['model_id']
            error = startup_error if startup_error is not None else provider_errors.get(tag)
            if error is not None:
                stage = 'fixture_or_playback_startup' if startup_error is not None else 'ollama_preflight'
                result = row | {'status': 'invalid', 'invalid': {'stage': stage, 'message': error}}
            else:
                trace = traces / f'{trial}.jsonl'
                assets = artifacts / uuid4().hex
                assets.mkdir(mode=0o700)
                result = run_trial(row, identities[tag], settings, protocol, trace, assets, fixture)
            regression.write_result(grades / f'{trial}.json', result)
            print(f'{trial} | {tag} | {row["condition"]} | {result["status"]}', file=sys.stderr, flush=True)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()

    result = report(output)
    regression.write_result(output / 'summary.json', result)
    return result | {'output': str(output)}
