import json
from pathlib import Path
import tempfile
import time
import unittest

from codex_eval.core import Store, new_id, normalize
from codex_eval.report import render
from codex_eval.scenarios import scenario


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'state')
        self.thread=new_id()
        self.node=new_id()
        self.record=self.store.start(self.thread,source='controlled-simulation',now=time.time()-100)
        self.at=self.record['started']+1

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def put(self,kind,**extra):
        self.at+=1
        event=dict(event_id=new_id(),thread_id=self.thread,execution_id=self.node,occurred_at=self.at,kind=kind)
        event.update(extra)
        payload=dict(recording_id=self.record['id'],event=event)
        self.store.ingest(payload)
        return payload

    def execution(self,status='completed'):
        self.put('execution',parent_id=None,status=status)

    def usage(self,input=100,cached=20,output=40,reasoning=10):
        return self.put('usage',scope='self',mode='cumulative',input=input,cached=cached,output=output,reasoning=reasoning,model='sim-weather-v1')

    def test_cumulative_duplicate_and_subset_accounting(self):
        self.execution()
        self.usage(input=80)
        payload=self.usage()
        self.assertFalse(self.store.ingest(payload))
        report=self.store.finish(now=self.at+1)
        self.assertEqual(report['totals'],dict(input=100,cached=20,output=40,reasoning=10))
        self.assertEqual(report['executions'][0]['own_tokens'],140)
        self.assertEqual(report['simulated_usd'],'0.000245')
        self.assertIsNone(report['actual_billed_usd'])

    def test_line_changes_use_latest_recording_snapshot_without_double_counting(self):
        self.execution()
        self.usage()
        self.put('changes',scope='recording',mode='snapshot',added=80,removed=10)
        payload=self.put('changes',scope='recording',mode='snapshot',added=48,removed=6)
        self.assertFalse(self.store.ingest(payload))
        report=self.store.finish(now=self.at+1)
        self.assertEqual(report['changes'],dict(added=48,removed=6))
        self.assertEqual(report['totals'],dict(input=100,cached=20,output=40,reasoning=10))
        self.assertEqual(len(report['executions']),1)
        self.assertEqual(report['security'],[])

    def test_line_changes_reject_content_and_ambiguous_scope(self):
        for value in (-1, True, 1.5, 'source code', None):
            with self.assertRaises(ValueError): self.put('changes',scope='recording',mode='snapshot',added=value,removed=0)
        with self.assertRaises(ValueError): self.put('changes',scope='execution',mode='snapshot',added=1,removed=0)
        with self.assertRaises(ValueError): self.put('changes',scope='recording',mode='delta',added=1,removed=0)
        p=self.put('changes',scope='recording',mode='snapshot',added=0,removed=0,filename='PRIVATE_FILENAME',diff='PRIVATE_CONTENT')
        stored=self.store.db.execute('SELECT data FROM events WHERE event_id=?',(p['event']['event_id'],)).fetchone()[0]
        self.assertNotIn('PRIVATE_',stored)

    def test_legacy_recording_without_line_events_is_unavailable(self):
        report=self.store.finish(now=self.at+1)
        self.assertEqual(report['changes'],dict(added=None,removed=None))

    def test_conflicting_duplicate_rejected(self):
        p=self.usage()
        p['event']['output']=90
        with self.assertRaises(ValueError): self.store.ingest(p)

    def test_inclusive_usage_rejected(self):
        with self.assertRaises(ValueError): self.put('usage',scope='inclusive',mode='cumulative')

    def test_unknown_values_remain_unknown(self):
        self.execution()
        self.usage(input=None,cached=None,output=None,reasoning=None)
        report=self.store.finish(now=self.at+1)
        self.assertIsNone(report['totals']['input'])
        self.assertEqual(report['coverage'],'incomplete')

    def test_no_events_never_complete(self):
        report=self.store.finish()
        self.assertEqual(report['coverage'],'incomplete')
        self.assertIsNone(report['totals']['input'])
        self.assertEqual(report['outcome'],'Ungraded')

    def test_single_active_chat_and_idempotent_start(self):
        self.assertEqual(self.store.start(self.thread)['id'],self.record['id'])
        with self.assertRaises(ValueError): self.store.start(new_id())

    def test_wrong_chat_rejected(self):
        with self.assertRaises(ValueError): self.put('execution',status='completed',parent_id=None,thread_id=new_id())

    def test_control_content_discarded(self):
        p=self.usage()
        p['event']['event_id']=new_id()
        p['event']['prompt']='SYNTHETICKEY_DO_NOT_SAVE'
        p['event']['raw_output']='<script>not-a-command</script>'
        self.store.ingest(p)
        all_rows=''.join(row[0] for row in self.store.db.execute('SELECT data FROM events'))
        self.assertNotIn('SYNTHETICKEY',all_rows)
        self.assertNotIn('<script>',all_rows)

    def test_partial_finish_excludes_future_usage(self):
        self.execution(status='running')
        report=self.store.finish(now=self.at+1)
        self.assertIn('Unfinished activity; final usage is unavailable',report['warnings'])
        self.at+=10
        with self.assertRaises(ValueError): self.usage()

    def test_delayed_event_versions_analysis(self):
        self.execution()
        first=self.store.finish(now=self.at+10)
        self.usage()
        second=self.store.report(self.record['id'])
        self.assertGreater(second['analysis_version'],first['analysis_version'])
        self.assertEqual(second['analysis_version'],self.store.report(self.record['id'])['analysis_version'])

    def test_continue_preserves_attempts(self):
        self.store.finish()
        second=self.store.start(self.thread,task_id=self.record['task_id'])
        self.assertNotEqual(second['id'],self.record['id'])
        self.assertEqual(len(self.store.list()),2)

    def test_counter_regression_warns(self):
        self.execution()
        self.usage(input=100)
        self.usage(input=50)
        self.assertIn('Usage counter regressed; totals are incomplete',self.store.finish()['warnings'])

    def test_cycle_warns(self):
        self.put('execution',status='completed',parent_id=self.node)
        self.usage()
        self.assertIn('Invalid execution cycle',self.store.finish()['warnings'])

    def test_invalid_counters(self):
        for value in (-1,True,1.5,10**20):
            with self.assertRaises(ValueError): self.usage(input=value)
        with self.assertRaises(ValueError): self.usage(cached=101)

    def test_retention_cascades(self):
        self.store.db.execute('UPDATE recordings SET started=0')
        self.store.db.commit()
        self.store.purge()
        self.assertEqual(self.store.list(),[])

    def test_export_escapes_fields(self):
        report=self.store.finish()
        report['outcome']='<script>malicious-looking fixture text</script>'
        output=render(report)
        self.assertNotIn('<script>',output)
        self.assertIn('&lt;script&gt;',output)
        self.assertIn("default-src 'none'",output)

    def test_future_schema_is_not_downgraded(self):
        self.store.db.execute('PRAGMA user_version=99')
        self.store.db.commit()
        with self.assertRaises(ValueError): Store(Path(self.tmp.name)/'state')

    def test_registered_assessments_preserve_scope_and_provenance(self):
        self.execution()
        payload = self.put('check', check='exact_match', grader='reference-match-v1', status='failed',
                           answer='PRIVATE_ANSWER', reference='PRIVATE_REFERENCE')
        self.assertFalse(self.store.ingest(payload))
        self.node = new_id()
        self.execution()
        self.put('check', check='exact_match', grader='reference-match-v1', status='passed')
        self.put('check', check='display', grader='weather-fixture-v1', status='passed')
        report = self.store.finish(now=self.at+1)
        self.assertEqual(report['outcome'], 'Failed')
        self.assertEqual(len(report['assessments']), 3)
        result = report['assessments'][0]
        self.assertEqual(result['scope'], 'supplied-reference')
        self.assertEqual(result['provenance'], 'trusted-emitter-comparison')
        self.assertNotIn('PRIVATE_', json.dumps(report))
        self.assertIn('reference-match-v1', render(report))
        self.assertEqual(report['checks']['display'], 'passed')

    def test_unregistered_checks_and_claimed_provenance_fail(self):
        for fields in ({'check':'accuracy'}, {'grader':'PRIVATE_GRADER'}, {'scope':'weather-fixture'},
                       {'provenance':'human-reviewed'}, {'status':'unknown'},
                       {'check':'exact_match', 'grader':'weather-fixture-v1'}):
            with self.assertRaises(ValueError):
                self.put('check', **(dict(check='exact_match', grader='reference-match-v1', status='passed') | fields))


class Scenarios(unittest.TestCase):
    def test_all_six_acceptance_walkthroughs(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'state')
            results={name:scenario(store,name) for name in ('desktop','multi','subagents','repair','blocked','partial')}
            self.assertEqual(results['desktop'][0]['outcome'],'Ungraded')
            self.assertEqual(results['desktop'][0]['coverage'],'incomplete')
            self.assertEqual(len(results['multi'][0]['executions']),2)
            self.assertEqual(len(results['subagents'][0]['executions']),3)
            self.assertEqual(results['subagents'][0]['totals']['input'],600)
            root=next(n for n in results['subagents'][0]['executions'] if n['parent_id'] is None)
            self.assertEqual(root['observed_subtree_tokens'],850)
            self.assertEqual(root['own_tokens'],140)
            self.assertEqual(results['subagents'][0]['tool_failures'],1)
            self.assertEqual(results['repair'][0]['outcome'],'Failed')
            self.assertEqual(results['repair'][1]['outcome'],'Passed supplied checks')
            self.assertEqual(results['repair'][0]['recording']['task_id'],results['repair'][1]['recording']['task_id'])
            self.assertEqual(len(results['repair'][1]['task_summary']['attempts']),2)
            self.assertEqual(results['blocked'][0]['security'][0]['action'],'block')
            self.assertEqual(results['blocked'][0]['outcome'],'Ungraded')
            self.assertIsNone(results['partial'][0]['totals']['input'])
            store.close()
