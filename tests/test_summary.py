import contextlib
import io
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from codex_eval.__main__ import current_thread, main
from codex_eval.core import Store, new_id
from codex_eval.scenarios import scenario
from codex_eval.summary import fields, inline, text, recording_details, agent_labels


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / 'state'
        self.store = Store(self.state)
        self.report = scenario(self.store, 'subagents')[0]

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_shared_metrics_and_safe_markup(self):
        f = fields(self.report)
        self.assertEqual(f['tokens'], '850')
        self.assertEqual(f['cache'], '60')
        self.assertNotIn('%', f['cache'])
        self.assertEqual(f['cached_output'], 'Not reported')
        self.assertEqual(f['lines'], '+48 −6')
        self.assertEqual(f['model'], 'Simulation — no AI model ran')
        self.assertEqual(f['cost_label'], 'Simulated USD')
        for key in ('tokens', 'elapsed', 'cost', 'cache', 'cached_output', 'lines', 'model'):
            self.assertIn(f[key], text(self.report))
            self.assertIn(f[key], inline(self.report))
        self.report['outcome'] = '<script>fixture</script>'
        fragment = inline(self.report)
        self.assertNotIn('<script>', fragment)
        self.assertIn('&lt;script&gt;', fragment)
        self.assertIn('<details>', fragment)
        self.assertIn('Subagent 1', fragment)
        self.assertNotIn('fetch(', fragment)

    def test_unknown_and_zero_are_distinct(self):
        self.report['totals'] = dict(input=None, output=None, cached=None, reasoning=None)
        self.report['simulated_usd'] = None
        f = fields(self.report)
        self.assertEqual([f[k] for k in ('tokens', 'cost', 'cache')], ['Unavailable'] * 3)
        self.report['totals'] = dict(input=0, output=0, cached=0, reasoning=0)
        f = fields(self.report)
        self.assertEqual(f['tokens'], '0')
        self.assertEqual(f['cache'], '0')

    def test_cached_input_requires_matching_coverage(self):
        self.report['executions'][0]['usage']['cached'] = None
        self.assertEqual(fields(self.report)['cache'], 'Unavailable')

    def test_line_changes_missing_and_zero_are_distinct(self):
        self.report.pop('changes')
        self.assertEqual(fields(self.report)['lines'], 'Unavailable')
        self.report['changes'] = {'added': 0, 'removed': 0}
        self.assertEqual(fields(self.report)['lines'], '+0 −0')
        self.report['changes'] = {'added': 1200, 'removed': 20}
        self.assertEqual(fields(self.report)['lines'], '+1,200 −20')

    def test_readable_names_preserve_recording_task_and_agent_relationships(self):
        title = recording_details(self.report['recording'])['title']
        self.assertEqual(title, 'Main agent with two helpers · Recording 1')
        self.assertNotIn(self.report['recording']['id'], title)
        labels = agent_labels(self.report)
        root = next(n for n in self.report['executions'] if n['parent_id'] is None)
        self.assertEqual(labels[root['id']], 'Main agent')
        self.assertEqual(len(self.store.list()), 1)
        repaired = scenario(self.store, 'ledger-repair')
        for index, report in enumerate(repaired, 1):
            self.assertEqual(recording_details(report['recording'])['title'], f'Ledger CLI · Repair · Recording {index}')
        legacy = repaired[1]['recording'] | {'sample_case': 'repair'}
        self.assertEqual(recording_details(legacy)['title'], 'Weather app · Timeout recovery · Recording 2')
        self.assertEqual(len(repaired[1]['task_summary']['attempts']), 2)
        self.assertEqual(len(repaired[1]['executions']), 1)

    def test_sample_labels_are_reviewed_metadata_only_and_survive_reopen(self):
        with self.assertRaises(ValueError):
            self.store.start(new_id(), source='controlled-simulation', sample_case='arbitrary prompt content')
        with self.assertRaises(ValueError):
            self.store.start(new_id(), sample_case='repair')
        self.store.close()
        self.store = Store(self.state)
        self.assertEqual(self.store.recording(self.report['recording']['id'])['sample_case'], 'subagents')
        legacy = self.store.start(new_id(), source='controlled-simulation', now=time.time()-1)
        report = self.store.finish()
        self.assertIn('original sample name was not saved',recording_details(report['recording'])['description'])
        self.store.db.execute('UPDATE recordings SET started=0')
        self.store.purge()
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM sample_cases').fetchone()[0], 0)

    def test_chat_resolution_and_finish_ownership(self):
        thread = new_id()
        with patch.dict(os.environ, {'CODEX_THREAD_ID': thread}, clear=True):
            self.assertEqual(current_thread(), thread)
            self.assertEqual(current_thread(new_id()) != thread, True)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError): current_thread()
        with patch.dict(os.environ, {'CODEX_THREAD_ID': 'invalid'}, clear=True):
            with self.assertRaises(ValueError): current_thread()
        with self.assertRaises(ValueError): self.store.latest_report(thread)
        selected = self.report['recording']['thread_id']
        self.assertEqual(self.store.latest_report(selected)['recording']['id'], self.report['recording']['id'])
        record = self.store.start(thread, now=time.time()-1)
        with self.assertRaises(ValueError): self.store.finish(thread_id=new_id())
        self.assertIsNone(self.store.recording(record['id'])['finished'])
        self.store.finish(thread_id=thread)

    def test_cli_print_and_file_match_without_overwrite(self):
        dest = Path(self.tmp.name) / 'summary.txt'
        thread = self.report['recording']['thread_id']
        args = ['codex-eval', '--state', str(self.state), 'summary']
        with patch.dict(os.environ, {'CODEX_THREAD_ID': thread}), patch('codex_eval.__main__.control', return_value=self.report) as control:
            printed = io.StringIO()
            with patch('sys.argv', args), contextlib.redirect_stdout(printed): main()
            self.assertEqual(control.call_args.args[1], {'action':'summary', 'thread_id':thread})
            with patch('sys.argv', args + ['--output', str(dest)]), contextlib.redirect_stdout(io.StringIO()): main()
            self.assertEqual(dest.read_text(), printed.getvalue())
            self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
            with patch('sys.argv', args + ['--output', str(dest)]), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): main()
            self.assertEqual(dest.read_text(), printed.getvalue())
