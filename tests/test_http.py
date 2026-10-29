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
from codex_eval.core import new_id


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
        token=(self.state/'ingestion.token').read_text()
        self.assertEqual(self.request('/ingest',{},Authorization='Bearer '+token,Origin='https://attacker.invalid')[0],403)

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
