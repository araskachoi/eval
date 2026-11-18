"""Text-only inference adapters for explicit benchmark runs."""
import http.client
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import tempfile

COUNTERS = {'prompt_eval_count': 'input_tokens', 'eval_count': 'output_tokens',
            'prompt_eval_cached_count': 'cached_input_tokens'}
DISABLED = ('apps', 'hooks', 'multi_agent', 'multi_agent_v2', 'plugins',
            'remote_plugin', 'shell_snapshot', 'shell_tool', 'skill_mcp_dependency_install')
CONFIG = [arg for feature in DISABLED for arg in ('--disable', feature)]
CONFIG += ['-c', 'web_search="disabled"', '-c', 'shell_environment_policy.inherit="none"']
OUTPUT_LIMIT = 2 * 1024 * 1024
KEYCHAIN_SERVICE = 'eval-codex-api-key'


def ollama_request(path, payload=None):
    conn = http.client.HTTPConnection('127.0.0.1', 11434, timeout=150)
    try:
        if payload is None:
            conn.request('GET', path)
        else:
            conn.request('POST', path, json.dumps(payload), {'Content-Type': 'application/json'})
        response = conn.getresponse()
        data = response.read(OUTPUT_LIMIT + 1)
        if response.status != 200 or len(data) > OUTPUT_LIMIT:
            raise ValueError('Local Ollama returned an error or oversized response')
        return json.loads(data)
    finally:
        conn.close()


def ollama_model(model):
    matches = [item for item in ollama_request('/api/tags')['models'] if item['name'] == model]
    if (len(matches) != 1 or matches[0]['details']['format'] != 'gguf' or matches[0]['size'] <= 0
            or not re.fullmatch('[0-9a-f]{64}', matches[0]['digest'])):
        raise ValueError('Select an installed local GGUF model')
    return {'provider': 'ollama', 'id': model, 'revision': matches[0]['digest'],
            'evidence': 'response.model and local Ollama tag digest'}


def ollama_chat(model, messages, settings, *, tools=None):
    options = {key: settings[key] for key in ('temperature', 'num_ctx', 'num_predict')}
    request = {'model': model['id'], 'messages': messages, 'stream': False,
               'keep_alive': settings['keep_alive'], 'think': settings['think'], 'options': options}
    if tools is not None:
        request['tools'] = tools
    reply = ollama_request('/api/chat', request)
    if reply.get('model') != model['id'] or reply.get('done') is not True:
        raise ValueError('Unexpected Ollama model or incomplete response')
    return reply['message'], {key: reply[field] for field, key in COUNTERS.items() if field in reply}


def ollama_turn(model, messages, settings):
    message, metrics = ollama_chat(model, messages, settings)
    return message['content'], metrics


def output_limit():
    resource.setrlimit(resource.RLIMIT_FSIZE, (OUTPUT_LIMIT, OUTPUT_LIMIT))


def codex_process(executable, work, args, prompt=None, *, api_key=None, home=None, capture_stderr=False):
    if home is None:
        home = work / 'codex-home'
        home.mkdir(mode=0o700, exist_ok=True)
    env = {'HOME': str(work), 'CODEX_HOME': str(home), 'PATH': os.defpath, 'LANG': 'C.UTF-8'}
    if api_key is not None:
        env['CODEX_API_KEY'] = api_key
    with tempfile.TemporaryFile() as output:
        result = subprocess.run([executable, *args], cwd=work, env=env,
                                input=prompt or b'', stdout=output,
                                stderr=subprocess.STDOUT if capture_stderr else subprocess.DEVNULL,
                                # The signed-in CLI also opens existing state files.
                                timeout=150, preexec_fn=output_limit if api_key is not None or 'exec' not in args else None)
        output.seek(0)
        data = output.read(OUTPUT_LIMIT + 1)
    if result.returncode or len(data) >= OUTPUT_LIMIT:
        raise ValueError('Codex invocation failed or exceeded its output limit')
    return data.decode()


def codex_preflight(executable):
    with tempfile.TemporaryDirectory(prefix='eval-codex-config-') as directory:
        work = Path(directory).resolve()
        version = codex_process(executable, work, ['--version']).strip()
        features = codex_process(executable, work, [*CONFIG, 'features', 'list'])
    disabled = {line.split()[0] for line in features.splitlines() if line.split() and line.endswith('false')}
    if not set(DISABLED) <= disabled:
        raise ValueError('Codex did not confirm the required tool settings')
    return version


def codex_receipt(stream):
    submission, usage = None, None
    for line in stream.splitlines():
        event = json.loads(line)
        kind = event['type']
        if kind in ('thread.started', 'turn.started'):
            continue
        if kind in ('item.started', 'item.updated', 'item.completed'):
            item = event['item']
            if item['type'] == 'reasoning':
                continue
            if item['type'] == 'agent_message':
                if kind == 'item.completed':
                    submission = item['text']
                continue
        if kind == 'turn.completed' and usage is None:
            usage = event['usage']
            continue
        raise ValueError('Codex emitted a tool, routing, or unsupported event')
    if submission is None or usage is None:
        raise ValueError('Codex did not produce a completed submission and usage receipt')
    return submission, {key: usage[key] for key in ('input_tokens', 'output_tokens', 'cached_input_tokens') if key in usage}


def codex_turn(executable, model, messages, settings, *, api_key, home):
    # Each invocation is ephemeral. The runner carries only synthetic turn history.
    if len(messages) == 1:
        prompt = messages[0]['content']
    else:
        prompt = 'Continue the synthetic benchmark using the transcript below.\n\n' + '\n\n'.join(
            f"{message['role']}:\n{message['content']}" for message in messages
        )
    with tempfile.TemporaryDirectory(prefix='eval-codex-turn-') as directory:
        work = Path(directory).resolve()
        stream = codex_process(executable, work, [
            *CONFIG, '-c', f'model_reasoning_effort={json.dumps(settings["reasoning_effort"])}',
            '-c', f'log_dir={json.dumps(str(work / "logs"))}',
            '-c', f'sqlite_home={json.dumps(str(work / "state"))}',
            '-a', 'never', 'exec', '--ignore-user-config', '--skip-git-repo-check',
            '--sandbox', 'read-only', '--ephemeral', '--json', '--model', model['id'], '-',
        ], prompt.encode(), api_key=api_key, home=home)
    return codex_receipt(stream)


def codex_key(keychain):
    if not keychain:
        key = os.environ.get('CODEX_API_KEY')
        if not key:
            raise ValueError('No accessible ChatGPT CLI login. Supply CODEX_API_KEY or use --keychain')
        return key
    error = f'Could not read the {KEYCHAIN_SERVICE} item from macOS Keychain'
    try:
        result = subprocess.run(['/usr/bin/security', 'find-generic-password', '-s', KEYCHAIN_SERVICE, '-w'],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, timeout=30, check=True)
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 44:  # macOS security exit status for errSecItemNotFound.
            raise ValueError(f'No visible macOS Keychain item has service {KEYCHAIN_SERVICE}. '
                             'Check the service name in Keychain Access') from None
        raise ValueError(error) from None
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise ValueError(error) from None
    key = result.stdout.rstrip('\r\n')
    if not key or '\n' in key or '\r' in key:
        raise ValueError(error)
    return key


def select_harness(spec, *, keychain=False):
    harness, model = spec['harness'], spec['model']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', model):
        raise ValueError('Select an explicit model ID')
    if harness == 'ollama':
        identity = ollama_model(model)
        if spec.get('revision', identity['revision']) != identity['revision']:
            raise ValueError('Installed Ollama revision differs from the requested revision')
        settings = {'temperature': 0.2, 'num_ctx': 8192, 'num_predict': 2048, 'keep_alive': 0,
                    'think': False, 'ollama_version': ollama_request('/api/version')['version'],
                    'outer_code_fence': 'unwrap one complete block'}
        return identity, 'local-ollama-text-v1', settings, ollama_turn
    if harness != 'codex':
        raise ValueError('Select ollama or codex')
    if spec.get('revision') is not None:
        raise ValueError('Codex CLI does not verify a hosted model revision')
    effort = spec.get('reasoning_effort', 'medium')
    if effort not in ('low', 'medium', 'high', 'xhigh'):
        raise ValueError('Unsupported Codex reasoning effort')
    executable = shutil.which('codex')
    if executable is None:
        raise ValueError('Codex CLI is unavailable')
    home = None
    if not keychain:
        existing_home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser().resolve()
        with tempfile.TemporaryDirectory(prefix='eval-codex-login-') as directory:
            try:
                status = codex_process(executable, Path(directory).resolve(), ['login', 'status'],
                                       home=existing_home, capture_stderr=True)
            except (ValueError, OSError, subprocess.SubprocessError):
                status = ''
        if 'Logged in using ChatGPT' in status.splitlines():
            home = existing_home
    api_key = codex_key(keychain) if home is None else None
    version = codex_preflight(executable)
    identity = {'provider': 'openai', 'id': model, 'revision': None,
                'evidence': 'requested via Codex CLI; served model unverified'}
    settings = {'codex_version': version, 'reasoning_effort': effort,
                'outer_code_fence': 'unwrap one complete block'}
    if home is not None:
        settings['authentication'] = 'chatgpt'
    return identity, 'codex-cli-text-v1', settings, lambda identity, history, options: codex_turn(
        executable, identity, history, options, api_key=api_key, home=home
    )
