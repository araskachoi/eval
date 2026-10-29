from __future__ import annotations

import hmac
import json
import os
import secrets
import sqlite3
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from .core import LIMIT, Store, identifier, private_file
from .report import render
from .summary import agent_labels, fields, recording_details


def record_control(store, request):
    thread = identifier(request['thread_id'])
    operation = request.get('operation', 'start')
    if operation not in {'start', 'stop', 'status', 'report'}:
        raise ValueError('Unknown recording operation')
    active = store.db.execute('SELECT id,thread_id FROM recordings WHERE finished IS NULL').fetchone()
    if active and active['thread_id'] != thread and operation in {'start', 'stop'}:
        return {'state':'other_chat_active', 'capture':'unavailable'}
    if operation == 'start':
        record = store.start(thread)
        return {'state':'armed', 'recording_id':record['id'], 'capture':'unavailable'}
    if operation == 'stop' and active:
        report = store.finish(thread_id=thread)
        return {'state':'finished', 'report':report, 'capture':'unavailable'}
    row = store.db.execute('SELECT id,finished FROM recordings WHERE thread_id=? ORDER BY started DESC,rowid DESC LIMIT 1', (thread,)).fetchone()
    if not row:
        return {'state':'idle', 'capture':'unavailable'}
    result = {'state':'armed' if row['finished'] is None else 'finished', 'recording_id':row['id'], 'capture':'unavailable'}
    if operation in {'stop', 'report'}:
        result['report'] = store.report(row['id'])
    return result


class Service:
    def __init__(self, state):
        self.state = state
        self.ingestion_token = secrets.token_urlsafe(32)
        self.codes, self.sessions = {}, {}
        self.lock = threading.Lock()
        token = state / 'ingestion.token'
        private_file(token)
        token.write_text(self.ingestion_token)

    def control(self, request):
        with self.lock:
            store = Store(self.state)
            try:
                action = request.get('action')
                if action == 'record':
                    return record_control(store, request)
                if action == 'status':
                    recordings = store.list()
                    for record in recordings:
                        record.update(recording_details(record))
                    return {'recordings':recordings, 'desktop_capture':'unverified', 'local_resources':'unavailable'}
                if action == 'on':
                    return store.start(request['thread_id'], request.get('task_id'))
                if action == 'off':
                    return store.finish(thread_id=request.get('thread_id'))
                if action == 'summary':
                    return store.latest_report(request['thread_id'])
                if action == 'report':
                    report = store.report(request['recording_id'])
                    report['presentation'] = dict(**recording_details(report['recording']), metrics=fields(report), agents=agent_labels(report))
                    return report
                if action == 'ingest':
                    return {'accepted':store.ingest(request)}
                if action == 'login':
                    now = time.monotonic()
                    self.codes = {k:v for k,v in self.codes.items() if v > now}
                    if len(self.codes) >= 8:
                        raise ValueError('Too many outstanding login codes')
                    code = secrets.token_urlsafe(24)
                    self.codes[code] = now + 60
                    return {'code':code, 'expires_in':60}
                raise ValueError('Unknown action')
            finally:
                store.close()


def serve(state, port=8765):
    if (state / 'control.sock').exists():
        raise ValueError('Collector socket exists; do not overwrite an active collector')
    service = Service(state)
    origin = f'http://127.0.0.1:{port}'
    assets = Path(__file__).parent / 'web'

    class Handler(BaseHTTPRequestHandler):
        server_version = 'LocalEval'

        def log_message(self, *args):
            pass

        def send(self, status, body, content_type='application/json', cookie=None):
            body = json.dumps(body).encode() if content_type == 'application/json' else body.encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            if cookie:
                self.send_header('Set-Cookie', cookie)
            self.end_headers()
            self.wfile.write(body)

        def host_ok(self):
            return self.headers.get('Host') == f'127.0.0.1:{port}'

        def authorized(self):
            cookies = dict(piece.strip().split('=',1) for piece in self.headers.get('Cookie','').split(';') if '=' in piece)
            now = time.monotonic()
            with service.lock:
                service.sessions = {k:v for k,v in service.sessions.items() if v > now}
                return cookies.get('eval_session') in service.sessions

        def do_GET(self):
            if not self.host_ok():
                return self.send(403, {'error':'host_denied'})
            routes = {'/':('index.html','text/html; charset=utf-8'), '/app.js':('app.js','text/javascript; charset=utf-8'), '/app.css':('app.css','text/css; charset=utf-8')}
            if self.path in routes:
                name, mime = routes[self.path]
                return self.send(200, (assets / name).read_text(), mime)
            self.send(404, {'error':'not_found'})

        def do_POST(self):
            self.connection.settimeout(3)
            if not self.host_ok():
                return self.send(403, {'error':'host_denied'})
            ingestion = self.path == '/ingest'
            if ingestion:
                if not hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer ' + service.ingestion_token):
                    return self.send(401, {'error':'unauthorized'})
                if self.headers.get('Origin'):
                    return self.send(403, {'error':'browser_ingestion_denied'})
            elif self.headers.get('Origin') != origin or self.headers.get('X-Eval-Control') != '1':
                return self.send(403, {'error':'origin_denied'})
            if not ingestion and self.path != '/session' and not self.authorized():
                return self.send(401, {'error':'unauthorized'})
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= LIMIT or self.headers.get('Content-Encoding') or self.headers.get('Transfer-Encoding'):
                    raise ValueError('Invalid request framing')
                if self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('Expected application/json')
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError('Expected an object')
                if self.path == '/session':
                    code = request.get('code', '')
                    with service.lock:
                        expires = service.codes.pop(code, 0)
                        if expires < time.monotonic():
                            return self.send(401, {'error':'invalid_or_expired_code'})
                        token = secrets.token_urlsafe(32)
                        service.sessions[token] = time.monotonic() + 3600
                    return self.send(200, {'ok':True}, cookie=f'eval_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=3600')
                if ingestion:
                    request['action'] = 'ingest'
                elif self.path != '/control' or request.get('action') not in {'status','on','off','report'}:
                    raise ValueError('Unsupported control')
                self.send(200, service.control(request))
            except (ValueError, KeyError, TypeError, OSError, sqlite3.Error):
                # Error text may contain input or database paths; never return it.
                self.send(400, {'error':'invalid_request_or_state'})

    class Control(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(3)
            try:
                raw = self.rfile.readline(LIMIT + 1)
                if len(raw) > LIMIT:
                    raise ValueError('Too large')
                result = service.control(json.loads(raw))
                response = {'result':result}
            except (ValueError, KeyError, TypeError, OSError, sqlite3.Error):
                response = {'error':'invalid_request_or_state'}
            self.wfile.write(json.dumps(response).encode() + b'\n')

    # Never unlink an existing socket: another collector may still own it.
    socket_path = state / 'control.sock'
    with HTTPServer(('127.0.0.1',port), Handler) as http:
        with socketserver.UnixStreamServer(str(socket_path), Control) as control:
            os.chmod(socket_path,0o600)
            threading.Thread(target=control.serve_forever, daemon=True).start()
            try:
                print(f'Collector running at {origin}; desktop adapter unverified', flush=True)
                http.serve_forever(poll_interval=0.5)
            finally:
                control.shutdown()
                socket_path.unlink(missing_ok=True)
                (state / 'ingestion.token').unlink(missing_ok=True)
                store = Store(state)
                try:
                    store.interrupt()
                finally:
                    store.close()
