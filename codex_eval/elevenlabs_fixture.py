"""Synthetic, stdio MCP server. Stdout carries only JSON-RPC messages."""
import json
from pathlib import Path
import sys
from uuid import uuid4

PROTOCOL_VERSION = '2025-06-18'
TOOL = {
    'name': 'generate_voiceover',
    'description': 'Generate an ElevenLabs voiceover and return its listening link.',
    'inputSchema': {
        'type': 'object',
        'properties': {
            'text': {'type': 'string', 'description': 'The exact words to speak.'},
            'voice_style': {'type': 'string', 'description': 'The requested voice style.'},
        },
        'required': ['text'],
        'additionalProperties': False,
    },
}
TEMPORARY = 'Generation temporarily unavailable.'
SAFE_RETRY = TEMPORARY + ' No audio was created. You can safely retry this request once.'
DIRECT_RETRY = TEMPORARY + ' No audio was created. Call generate_voiceover one more time now with the same arguments.'
RECOVERY_MESSAGES = {'recovery-a': TEMPORARY, 'recovery-b': SAFE_RETRY, 'recovery-c': DIRECT_RETRY}
DENIED = 'Generation permission denied. This connection does not have permission to generate audio.'
READ_LIMIT = 2 * 1024 * 1024


def tool_result(message, error):
    return {'content': [{'type': 'text', 'text': message}], 'isError': error}


def serve(condition, trace_path, artifacts, base, fixture_path):
    fixture = fixture_path.read_bytes()
    with trace_path.open('x', encoding='utf-8') as trace:
        def record(event, **fields):
            trace.write(json.dumps({'event': event, **fields}) + '\n')
            trace.flush()

        record('start')
        state = 'new'
        valid_calls = 0
        while line := sys.stdin.buffer.readline(READ_LIMIT + 1):
            if len(line) > READ_LIMIT:
                raise ValueError('Oversized MCP request')
            request = json.loads(line)
            method, params = request['method'], request.get('params', {})
            if method == 'initialize' and state == 'new':
                state = 'initializing'
                result = {'protocolVersion': PROTOCOL_VERSION, 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'elevenlabs', 'version': '1.0'}}
            elif method == 'notifications/initialized' and state == 'initializing':
                state = 'ready'
                record('ready')
                continue
            elif method == 'tools/list' and state == 'ready':
                result = {'tools': [TOOL]}
            elif method == 'tools/call' and state == 'ready':
                arguments, name = params.get('arguments'), params.get('name')
                record('call', name=name, arguments=arguments)
                if (name != TOOL['name'] or not isinstance(arguments, dict)
                        or set(arguments) - {'text', 'voice_style'}
                        or not isinstance(arguments.get('text'), str)
                        or not arguments['text'].strip()
                        or ('voice_style' in arguments and not isinstance(arguments['voice_style'], str))):
                    outcome, message = 'invalid_arguments', 'Invalid voiceover tool or arguments.'
                else:
                    valid_calls += 1
                    if condition == 'permission-denied':
                        outcome, message = 'denied', DENIED
                    elif valid_calls == 1 and condition in RECOVERY_MESSAGES:
                        outcome, message = 'temporary_error', RECOVERY_MESSAGES[condition]
                    else:
                        outcome = 'created'
                        asset = f'{uuid4().hex}.wav'
                        with (artifacts / asset).open('xb') as stream:
                            stream.write(fixture)
                        message = base + asset
                result = tool_result(message, outcome != 'created')
                record('result', outcome=outcome, response=result)
            else:
                print(json.dumps({'jsonrpc': '2.0', 'id': request.get('id'),
                                  'error': {'code': -32601, 'message': 'Method not available'}}), flush=True)
                continue
            print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
        record('end')


if __name__ == '__main__':
    scenario, trace_arg, assets_arg, url_base, fixture_arg = sys.argv[1:]
    serve(scenario, Path(trace_arg), Path(assets_arg), url_base, Path(fixture_arg))
