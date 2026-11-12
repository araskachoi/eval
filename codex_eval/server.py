from __future__ import annotations

from contextlib import ExitStack, closing
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
from .version import application

REQUEST_ERRORS = (ValueError, KeyError, TypeError, OSError, OverflowError, RecursionError, sqlite3.Error)
REQUEST_TIMEOUT = 3


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
        self.updating = False
        self.stop = None

    def control(self, request):
        if not isinstance(request, dict):
            raise ValueError('Expected an object')
        with self.lock:
            action = request.get('action')
            if action == 'version':
                return application()
            if action == 'cancel_update':
                self.updating = False
                return {'ready': False}
            if action == 'shutdown_for_update':
                if not self.updating or self.stop is None:
                    raise ValueError('Prepare update first')
                threading.Thread(target=self.stop, daemon=True).start()
                return {'stopping': True}
            if action == 'login':
                now = time.monotonic()
                self.codes = {key: expires for key, expires in self.codes.items() if expires > now}
                if len(self.codes) >= 8:
                    raise ValueError('Too many outstanding login codes')
                code = secrets.token_urlsafe(24)
                self.codes[code] = now + 60
                return {'code': code, 'expires_in': 60}
            if self.updating and (action == 'on' or action == 'record' and request.get('operation', 'start') == 'start'):
                raise ValueError('Update in progress; no new recording was opened')
            with closing(Store(self.state)) as store:
                if action == 'prepare_update':
                    if store.db.execute('SELECT 1 FROM recordings WHERE finished IS NULL').fetchone():
                        raise ValueError('Finish the recording before updating')
                    self.updating = True
                    return {'ready':True, 'application':application()}
                if action == 'record':
                    return record_control(store, request)
                if action == 'status':
                    recordings = store.list()
                    for record in recordings:
                        record.update(recording_details(record))
                    return {'recordings':recordings, 'desktop_capture':'unverified', 'local_resources':'unavailable', 'application':application(), 'updating':self.updating}
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
                raise ValueError('Unknown action')


def serve(state, port=8765):
    socket_path = state / 'control.sock'
    if os.path.lexists(socket_path):
        raise ValueError('Collector socket exists; do not overwrite an active collector')
    service = Service(state)
    bearer = f'Bearer {service.ingestion_token}'.encode()
    assets = Path(__file__).parent / 'web'

    class Handler(BaseHTTPRequestHandler):
        server_version = 'LocalEval'
        timeout = REQUEST_TIMEOUT

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
            return self.headers.get_all('Host') == [authority]

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
            if not self.host_ok():
                return self.send(403, {'error':'host_denied'})
            ingestion = self.path == '/ingest'
            if ingestion:
                if not hmac.compare_digest(self.headers.get('Authorization', '').encode(), bearer):
                    return self.send(401, {'error':'unauthorized'})
                if self.headers.get('Origin'):
                    return self.send(403, {'error':'browser_ingestion_denied'})
            elif self.headers.get('Origin') != origin or self.headers.get('X-Eval-Control') != '1':
                return self.send(403, {'error':'origin_denied'})
            if not ingestion and self.path != '/session' and not self.authorized():
                return self.send(401, {'error':'unauthorized'})
            try:
                lengths = self.headers.get_all('Content-Length', [])
                if len(lengths) != 1 or 'Content-Encoding' in self.headers or 'Transfer-Encoding' in self.headers:
                    raise ValueError('Invalid request framing')
                length = int(lengths[0])
                if not 0 < length <= LIMIT:
                    raise ValueError('Invalid request framing')
                if self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('Expected application/json')
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError('Incomplete request body')
                request = json.loads(raw)
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
            except REQUEST_ERRORS:
                # Error text may contain input or database paths; never return it.
                self.send(400, {'error':'invalid_request_or_state'})

    class Control(socketserver.StreamRequestHandler):
        timeout = REQUEST_TIMEOUT

        def handle(self):
            try:
                raw = self.rfile.readline(LIMIT + 1)
                if len(raw) > LIMIT or not raw.endswith(b'\n'):
                    raise ValueError('Invalid request framing')
                result = service.control(json.loads(raw))
                response = {'result':result}
            except REQUEST_ERRORS:
                response = {'error':'invalid_request_or_state'}
            self.wfile.write(json.dumps(response).encode() + b'\n')

    with HTTPServer(('127.0.0.1',port), Handler) as http:
        authority = f'127.0.0.1:{http.server_port}'
        origin = f'http://{authority}'
        service.stop = http.shutdown
        with ExitStack() as resources:
            control = socketserver.UnixStreamServer(str(socket_path), Control)
            resources.callback(socket_path.unlink, missing_ok=True)
            resources.enter_context(control)
            os.chmod(socket_path, 0o600)
            token = state / 'ingestion.token'
            private_file(token)
            resources.callback(token.unlink, missing_ok=True)
            token.write_text(service.ingestion_token)
            store = resources.enter_context(closing(Store(state)))
            store.interrupt()  # Close a recording left open by an interrupted collector.
            resources.callback(store.interrupt)
            threading.Thread(target=control.serve_forever, daemon=True).start()
            resources.callback(control.shutdown)
            print(f'Collector running at {origin}; desktop adapter unverified', flush=True)
            http.serve_forever(poll_interval=0.5)
