from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sqlite3
import subprocess
from pathlib import Path

from .core import LIMIT, Store, identifier, private_directory
from .report import render
from . import summary
from .version import application


def current_thread(explicit=None):
    runtime = os.environ.get('CODEX_THREAD_ID')
    if runtime is not None:
        runtime = identifier(runtime)
    if explicit is not None:
        return identifier(explicit)
    if runtime is None:
        raise ValueError('No current chat context; supply --thread explicitly')
    return runtime


def control(state, request):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(5)
        client.connect(str(state / 'control.sock'))
        client.sendall(json.dumps(request).encode() + b'\n')
        with client.makefile('rb') as stream:
            result = json.loads(stream.readline(LIMIT * 8))
    if 'error' in result:
        raise ValueError('Collector rejected the request; check identifiers and recording state')
    return result['result']


def main():
    parser = argparse.ArgumentParser(description='Local metrics and Finish reports; no model calls')
    build = application()
    parser.add_argument('--version', action='version', version=f"Local Eval {build['version']} ({build['release_id']})")
    parser.add_argument('--state', type=Path, default=Path.home() / 'Library/Application Support/codex-eval')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor')
    collector = commands.add_parser('collector')
    collector.add_argument('operation', choices=['start'])
    collector.add_argument('--port',type=int,default=8765)
    start = commands.add_parser('on')
    start.add_argument('--thread')
    start.add_argument('--task')
    stop = commands.add_parser('off')
    stop.add_argument('--thread')
    commands.add_parser('status')
    commands.add_parser('panel')
    report = commands.add_parser('report')
    report.add_argument('recording_id')
    report.add_argument('--output',type=Path)
    compact = commands.add_parser('summary', help='Summary of this chat; uses CODEX_THREAD_ID when invoked by Codex')
    compact.add_argument('--thread')
    compact.add_argument('--format', choices=['text', 'inline'], default='text')
    compact.add_argument('--output', type=Path)
    record = commands.add_parser('record', help='Current-chat recording controls for the record skill')
    record.add_argument('operation', nargs='?', choices=['start', 'stop', 'status', 'report'], default='start')
    record.add_argument('--format', choices=['text', 'inline'], default='text')
    record.add_argument('--output', type=Path)
    commands.add_parser('purge')
    commands.add_parser('cleanup')
    commands.add_parser('acceptance')
    args = parser.parse_args()
    os.umask(0o077)
    thread = None
    try:
        if args.command == 'doctor':
            executable = shutil.which('codex')
            version = subprocess.run([executable,'--version'],capture_output=True,text=True,timeout=5).stdout.strip() if executable else 'not found'
            print(json.dumps({'codex':version,'desktop_capture':'unverified — no telemetry configured or private history read', 'live_benchmarks':'disabled pending isolated authentication design','resources':'unavailable; no attribution is fabricated','test_command':'python3 scripts/isolated.py test --magen /absolute/path/to/magen','dependencies':'standard library only'},indent=2))
            return
        if args.command == 'acceptance':
            raise ValueError('Acceptance fixtures must run inside isolation: python3 scripts/isolated.py test')
        thread = current_thread() if args.command == 'record' else current_thread(args.thread) if args.command in ('on', 'off', 'summary') else None
        if args.command == 'record' and args.operation in ('start', 'status') and (args.output or args.format != 'text'):
            raise ValueError('Only stop/report can export a summary')
        state = private_directory(args.state)
        if args.command == 'collector':
            if (state / 'control.sock').exists():
                raise ValueError('Collector socket exists; run cleanup only if its collector has stopped')
            # A previous interrupted recording never resumes automatically.
            store = Store(state)
            store.interrupt()
            store.close()
            from .server import serve
            serve(state,args.port)
            return
        if args.command == 'cleanup':
            path = state / 'control.sock'
            if path.exists():
                with socket.socket(socket.AF_UNIX) as probe:
                    probe.settimeout(1)
                    try:
                        probe.connect(str(path))
                    except ConnectionRefusedError:
                        path.unlink()
                    else:
                        raise ValueError('Collector is active; cleanup refused')
            return
        if args.command == 'purge':
            store = Store(state)
            store.purge()
            store.close()
            return
        request = {'action':args.command}
        if args.command == 'record':
            request.update(thread_id=thread, operation=args.operation)
        elif args.command == 'on':
            request.update(thread_id=thread,task_id=args.task)
        elif args.command in ('off', 'summary'):
            request['thread_id'] = thread
        elif args.command == 'panel':
            request['action'] = 'login'
        elif args.command == 'report':
            request['recording_id'] = args.recording_id
        result = control(state, request)
        if args.command == 'record':
            if result['state'] == 'other_chat_active':
                parser.exit(1, 'Another chat has an open recording. Stop it from that chat first; no recording was changed.\n')
            if 'report' in result:
                content = summary.inline(result['report']) if args.format == 'inline' else summary.text(result['report'])
            else:
                content = {'armed':'Measurement window armed for this chat.', 'finished':'Recording is stopped for this chat.', 'idle':'No recording exists for this chat.'}[result['state']]
                content += '\nLive capture is unavailable; Codex activity is not automatically collected.\n'
            if args.operation in ('stop', 'report') and 'report' not in result and args.output:
                parser.exit(1, 'No recording exists for this chat; no report file was created.\n')
        elif args.command == 'summary':
            content = summary.inline(result) if args.format == 'inline' else summary.text(result)
        elif args.command == 'report' and args.output:
            content = render(result)
        else:
            content = None
        if content is not None and args.output:
            descriptor = os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(descriptor,'w') as output:
                output.write(content)
            print(str(args.output.absolute()))
        elif content is not None:
            print(content, end='')
        else:
            print(json.dumps(result,indent=2))
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        if args.command == 'record' and isinstance(exc, (FileNotFoundError, ConnectionRefusedError, TimeoutError)):
            parser.exit(1, 'Collector unavailable. Start the configured collector first; no recording was changed.\n')
        if args.command == 'record' and thread is None:
            parser.exit(1, 'Current chat identity is unavailable or invalid. Invoke record from Codex in the intended chat; no recording was changed.\n')
        parser.exit(1, f'Unable to complete operation ({type(exc).__name__}); no model work was launched.\n')


if __name__ == '__main__':
    main()
