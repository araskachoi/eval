import json
from pathlib import Path
import tempfile
import time
import unittest

from codex_eval.core import Store, new_id, normalize
from codex_eval.summary import fields, inline, text


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'state')
        self.thread, self.agent = new_id(), new_id()
        self.at = time.time() - 100
        self.record = self.store.start(self.thread, now=self.at)
        self.put('execution', parent_id=None, status='completed')

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def put(self, kind, **attrs):
        self.at += 1
        event = dict(event_id=new_id(), thread_id=self.thread, execution_id=self.agent, occurred_at=self.at, kind=kind, **attrs)
        payload = dict(recording_id=self.record['id'], event=event)
        self.store.ingest(payload)
        return payload

    def usage(self, **attrs):
        return self.put('usage', **(dict(scope='self', mode='cumulative', input=100, cached=20, output=40, reasoning=None,
                                       harness='codex', provider='openai', model='gpt-6.1-sol', model_source='response') | attrs))

    def test_adaptive_agent_keeps_model_calls_separate(self):
        self.usage(request_id=new_id())
        self.usage(request_id=new_id(),model='gpt-6-astra',input=300,output=120)
        self.usage(request_id=new_id(),provider='anthropic',model='claude-sonnet-4-5-20250929',input=200,output=90)
        report = self.store.finish(now=self.at+1)
        self.assertEqual(report['totals']['input']+report['totals']['output'],850)
        self.assertEqual(len(report['executions']),1)
        self.assertIsNone(report['executions'][0]['usage']['model'])
        self.assertEqual(sum(row['tokens'] for row in report['models']),850)
        self.assertEqual({row['model'] for row in report['models']},{'gpt-6.1-sol','gpt-6-astra','claude-sonnet-4-5-20250929'})
        self.assertEqual(fields(report)['model'],'3 models')
        self.assertIsNone(report['api_equivalent_usd'])
        for model in ('gpt-6.1-sol','claude-sonnet-4-5-20250929'):
            self.assertIn(model,text(report))
            self.assertIn(model,inline(report))

    def test_request_snapshots_and_duplicates_count_once(self):
        request = new_id()
        self.usage(request_id=request,input=80)
        payload = self.usage(request_id=request)
        self.assertFalse(self.store.ingest(payload))
        report = self.store.finish(now=self.at+1)
        self.assertEqual(report['models'][0]['tokens'],140)
        self.assertEqual(report['models'][0]['usage_records'],1)

    def test_cannot_mix_whole_execution_and_per_call_usage(self):
        self.usage()
        with self.assertRaises(ValueError): self.usage(request_id=new_id())
        self.agent = new_id()
        self.put('execution',parent_id=None,status='completed')
        self.usage(request_id=new_id())
        with self.assertRaises(ValueError): self.usage()

    def test_same_call_cannot_be_counted_under_two_agents(self):
        request = new_id()
        self.usage(request_id=request)
        self.agent = new_id()
        self.put('execution',parent_id=None,status='completed')
        with self.assertRaises(ValueError): self.usage(request_id=request)

    def test_model_switch_without_call_boundaries_stays_unattributed(self):
        self.usage()
        self.usage(model='gpt-6-astra',input=120)
        report = self.store.finish(now=self.at+1)
        self.assertEqual(report['totals']['input'],120)
        self.assertIsNone(report['models'][0]['model'])
        self.assertTrue(any('per-model attribution unavailable' in w for w in report['warnings']))

    def test_configured_or_unreviewed_models_are_not_observed_identity(self):
        for attrs in ({'model_source':'configuration'}, {'model':'SYNTHETIC_PRIVATE_MODEL'}, {'provider':'anthropic'}, {'model':'<script>fixture</script>'}):
            payload=self.usage(request_id=new_id(), **attrs)
            normalized=normalize(payload['event'])
            self.assertIsNone(normalized['model'])
            self.assertNotIn('SYNTHETIC_PRIVATE_MODEL',json.dumps(normalized))
            self.assertNotIn('<script>',json.dumps(normalized))
        report=self.store.finish(now=self.at+1)
        self.assertEqual(fields(report)['model'],'Not reported')

    def test_harness_provider_and_exact_version_are_independent(self):
        self.usage(request_id=new_id(),harness='claude-code',provider='anthropic',model='claude-haiku-4-5-20251001')
        report=self.store.finish(now=self.at+1)
        row=report['models'][0]
        self.assertEqual((row['harness'],row['provider'],row['model']),('claude-code','anthropic','claude-haiku-4-5-20251001'))
        self.assertEqual(fields(report)['model'],'claude-haiku-4-5-20251001')

    def test_legacy_simulation_is_represented_as_fixture_not_model(self):
        self.store.finish(now=self.at+1)
        self.record=self.store.start(self.thread,source='controlled-simulation',now=self.at+2)
        self.at+=2
        payload=self.usage(model='sim-weather-v1')
        # Old saved events predate the identity fields. Replay remains idempotent.
        with self.store.db:
            self.store.db.execute('UPDATE events SET data=? WHERE event_id=?',(json.dumps(payload['event']),payload['event']['event_id']))
        self.assertFalse(self.store.ingest(payload))
        report=self.store.finish(now=self.at+1)
        self.assertNotIn('sim-weather-v1',json.dumps(report))
        self.assertIsNone(report['executions'][0]['usage']['model'])
        self.assertEqual(report['executions'][0]['usage']['fixture_profile'],'weather-v1')
        self.assertEqual(report['simulated_usd'],'0.000245')
