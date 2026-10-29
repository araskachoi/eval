import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_eval.__main__ import main
from codex_eval.core import Store, new_id
from codex_eval.server import record_control


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / 'state'
        self.store = Store(self.state)
        self.thread = new_id()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def command(self, operation='start', thread=None):
        return record_control(self.store, dict(thread_id=thread or self.thread, operation=operation))

    def test_start_and_stop_are_idempotent_and_status_is_scoped(self):
        self.assertEqual(self.command('status')['state'], 'idle')
        first = self.command()
        self.assertEqual(first['state'], 'armed')
        self.assertEqual(first['capture'], 'unavailable')
        self.assertEqual(self.command()['recording_id'], first['recording_id'])
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(self.command('status',new_id()), {'state':'idle','capture':'unavailable'})
        finished = self.command('stop')['report']
        self.assertEqual(self.command('stop')['report']['recording']['finished'], finished['recording']['finished'])
        self.assertEqual(self.command('report')['report']['recording']['id'], first['recording_id'])
        self.assertIsNone(finished['totals']['input'])
        self.assertEqual(finished['outcome'], 'Ungraded')

    def test_cannot_start_or_stop_another_chats_recording(self):
        first = self.command()
        for operation in ('start','stop'):
            self.assertEqual(self.command(operation,new_id())['state'], 'other_chat_active')
        self.assertIsNone(self.store.recording(first['recording_id'])['finished'])
        self.command('stop')

    def test_bad_identity_and_operation_never_change_state(self):
        for request in ({'thread_id':'not a chat','operation':'start'}, {'thread_id':self.thread,'operation':'toggle'}):
            with self.assertRaises(ValueError): record_control(self.store,request)
        self.assertEqual(self.store.list(), [])

    def run_cli(self, args, environment, control=None):
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ,environment,clear=True), patch('sys.argv',['codex-eval','--state',str(self.state),'record',*args]), contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            if control is None:
                main()
            else:
                with patch('codex_eval.__main__.control', side_effect=control): main()
        return output.getvalue(), errors.getvalue()

    def test_cli_resolves_invoking_chat_and_warns_capture_is_unavailable(self):
        def collector(state, request):
            self.assertEqual(state,self.state)
            self.assertEqual(request,{'action':'record','thread_id':self.thread,'operation':'start'})
            return self.command()
        output,_=self.run_cli([],{'CODEX_THREAD_ID':self.thread},collector)
        self.assertIn('armed for this chat',output)
        self.assertIn('not automatically collected',output)
        self.assertNotIn(self.thread,output)

    def test_cli_missing_identity_never_contacts_collector(self):
        for env in ({},{'CODEX_THREAD_ID':'bad'}):
            with patch('codex_eval.__main__.control') as collector:
                with self.assertRaises(SystemExit): self.run_cli([],env)
                collector.assert_not_called()
        self.assertEqual(self.store.list(),[])

    def test_cli_stop_exports_shared_inline_without_overwriting(self):
        self.command()
        dest=Path(self.tmp.name)/'recording.html'
        def collector(state, request): return record_control(self.store,request)
        self.run_cli(['stop','--format','inline','--output',str(dest)],{'CODEX_THREAD_ID':self.thread},collector)
        content=dest.read_text()
        self.assertIn('Unavailable',content)
        self.assertIn('<details>',content)
        self.assertNotIn('sim-weather-v1',content)
        self.assertEqual(dest.stat().st_mode & 0o777,0o600)
        with self.assertRaises(SystemExit):
            self.run_cli(['report','--format','inline','--output',str(dest)],{'CODEX_THREAD_ID':self.thread},collector)
        self.assertEqual(dest.read_text(),content)
