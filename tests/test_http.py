import http.client
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from codex_eval.__main__ import control
from codex_eval.core import Store, new_id


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.state=Path(cls.tmp.name)/'state'
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0))
            cls.port=probe.getsockname()[1]
        cls.process=subprocess.Popen([sys.executable,'-m','codex_eval','--state',str(cls.state),'collector','start','--port',str(cls.port)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for _ in range(100):
            if (cls.state/'control.sock').exists(): break
            if cls.process.poll() is not None: raise RuntimeError('Collector exited during startup')
            time.sleep(.02)

    @classmethod
    def tearDownClass(cls):
        cls.process.send_signal(2)
        cls.process.wait(timeout=5)
        cls.tmp.cleanup()

    def request(self,path,body,**headers):
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=3)
        connection.request('POST',path,json.dumps(body),headers={'Content-Type':'application/json',**headers})
        response=connection.getresponse()
        result=(response.status,response.getheader('Set-Cookie'),response.read())
        connection.close()
        return result

    def test_browser_controls_require_origin_and_session(self):
        status,_,_=self.request('/control',{'action':'status'})
        self.assertEqual(status,403)
        status,_,_=self.request('/control',{'action':'status'},Origin=f'http://127.0.0.1:{self.port}',**{'X-Eval-Control':'1'})
        self.assertEqual(status,401)

    def test_one_time_login_and_cookie(self):
        code=control(self.state,{'action':'login'})['code']
        headers={'Origin':f'http://127.0.0.1:{self.port}','X-Eval-Control':'1'}
        status,cookie,_=self.request('/session',{'code':code},**headers)
        self.assertEqual(status,200)
        self.assertIn('HttpOnly',cookie)
        self.assertEqual(self.request('/session',{'code':code},**headers)[0],401)
        self.assertEqual(self.request('/control',{'action':'status'},Cookie=cookie.split(';')[0],**headers)[0],200)
        self.assertEqual(self.request('/control',{'action':'status'},Cookie=cookie.split(';')[0],Origin='https://attacker.invalid',**{'X-Eval-Control':'1'})[0],403)

    def test_ingestion_requires_separate_token(self):
        self.assertEqual(self.request('/ingest',{})[0],401)
        self.assertEqual(self.request('/ingest', {}, Authorization='Bearer é')[0], 401)
        token=(self.state/'ingestion.token').read_text()
        self.assertEqual(self.request('/ingest',{},Authorization='Bearer '+token,Origin='https://attacker.invalid')[0],403)

    def test_login_rejects_ambiguous_and_incomplete_bodies(self):
        code = control(self.state, {'action': 'login'})['code']
        body = json.dumps({'code': code})
        origin = f'http://127.0.0.1:{self.port}'
        headers = (f'POST /session HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n'
                   f'Origin: {origin}\r\nX-Eval-Control: 1\r\nContent-Type: application/json\r\n')
        length = f'Content-Length: {len(body)}'
        for framing in (f'{length}\r\n{length}', f'Content-Length: {len(body) + 1}'):
            with self.subTest(framing=framing):
                with socket.create_connection(('127.0.0.1', self.port), timeout=3) as client:
                    client.sendall((headers + framing + '\r\n\r\n' + body).encode())
                    client.shutdown(socket.SHUT_WR)
                    with http.client.HTTPResponse(client) as response:
                        response.begin()
                        self.assertEqual(response.status, 400)
                        self.assertEqual(json.loads(response.read()), {'error': 'invalid_request_or_state'})
        self.assertEqual(self.request('/session', {'code': code}, Origin=origin, **{'X-Eval-Control': '1'})[0], 200)

    def test_private_socket_rejects_invalid_json_objects(self):
        for raw in (b'[]\n', b'{"action":"status"}', b'[' * 2000 + b']' * 2000 + b'\n'):
            with self.subTest(size=len(raw)), socket.socket(socket.AF_UNIX) as client:
                client.settimeout(3)
                client.connect(str(self.state / 'control.sock'))
                client.sendall(raw)
                client.shutdown(socket.SHUT_WR)
                with client.makefile('rb') as stream:
                    self.assertEqual(json.loads(stream.readline()), {'error': 'invalid_request_or_state'})

    def test_failed_http_bind_preserves_recording_and_token(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'state'
            store = Store(state)
            try:
                record = store.start(new_id())
                token = state / 'ingestion.token'
                token.touch(mode=0o600)
                token.write_text('existing-token')
                result = subprocess.run(
                    [sys.executable, '-m', 'codex_eval', '--state', str(state), 'collector', 'start', '--port', str(self.port)],
                    capture_output=True, timeout=5,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(store.recording(record['id'])['finished'])
                self.assertEqual(token.read_text(), 'existing-token')
                self.assertFalse((state / 'control.sock').exists())
            finally:
                store.close()

    def test_socket_controls_record_and_finish_without_model(self):
        record=control(self.state,{'action':'on','thread_id':new_id()})
        report=control(self.state,{'action':'off'})
        self.assertEqual(record['id'],report['recording']['id'])
        display=control(self.state,{'action':'report','recording_id':record['id']})['presentation']
        self.assertIn('Recording 1',display['title'])
        self.assertEqual(display['metrics']['tokens'],'Unavailable')
        self.assertNotIn(record['id'],display['title'])
        self.assertEqual(report['outcome'],'Ungraded')
        self.assertIsNone(report['totals']['input'])
        selected=control(self.state,{'action':'summary','thread_id':record['thread_id']})
        self.assertEqual(selected['recording']['id'],record['id'])
        with self.assertRaises(ValueError): control(self.state,{'action':'summary','thread_id':new_id()})

    def test_record_skill_controls_use_socket_and_current_chat(self):
        thread=new_id()
        request={'action':'record','thread_id':thread}
        started=control(self.state,request)
        self.assertEqual(control(self.state,request)['recording_id'],started['recording_id'])
        self.assertEqual(control(self.state,dict(request,operation='status'))['state'],'armed')
        self.assertEqual(control(self.state,dict(request,thread_id=new_id(),operation='stop'))['state'],'other_chat_active')
        finished=control(self.state,dict(request,operation='stop'))
        self.assertEqual(finished['report']['recording']['id'],started['recording_id'])
        self.assertEqual(control(self.state,dict(request,operation='report'))['report']['recording']['id'],started['recording_id'])

    def test_explicit_receipt_ingestion_over_private_socket(self):
        from codex_eval.adapters import receipt_usage
        thread, execution = new_id(), new_id()
        record = control(self.state, {'action':'on', 'thread_id':thread})
        event = receipt_usage('ollama-response-v1', {'model':'llama3.2:3b', 'prompt_eval_count':23, 'eval_count':8},
                              event_id=new_id(), thread_id=thread, execution_id=execution,
                              request_id=new_id(), occurred_at=time.time())
        payload = dict(action='ingest', recording_id=record['id'], event=event)
        try:
            self.assertTrue(control(self.state, payload)['accepted'])
            self.assertFalse(control(self.state, payload)['accepted'])
            report = control(self.state, {'action':'report', 'recording_id':record['id']})
            self.assertEqual(report['totals'], dict(input=23, output=8, cached=None, reasoning=None))
            self.assertEqual(report['models'][0]['model'], 'llama3.2:3b')
            self.assertEqual(report['models'][0]['adapter'], 'ollama-response-v1')
            self.assertEqual(report['presentation']['metrics']['cache'], 'Unavailable')
            self.assertIsNone(report['actual_billed_usd'])
        finally:
            control(self.state, {'action':'off', 'thread_id':thread})
