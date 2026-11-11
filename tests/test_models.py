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

    def test_receipt_adapters_share_the_accounting_contract(self):
        from codex_eval.adapters import receipt_usage
        # Independent receipts: two Ollama attempts (including a failed retry),
        # then a different runtime in the same execution. No model is invoked.
        receipts = [
            ('ollama-response-v1', {'model':'llama3.2:3b', 'prompt_eval_count':11, 'eval_count':7}),
            ('ollama-response-v1', {'model':'llama3.2:3b', 'prompt_eval_count':13, 'eval_count':5}),
            ('numeric-fixture-v1', {'model':'counter-model-v1', 'input':17, 'output':3, 'cached':0, 'reasoning':0}),
        ]
        for adapter, receipt in receipts:
            request = new_id()
            self.at += 1
            event = receipt_usage(adapter, receipt | {'response':'PRIVATE_RESPONSE', 'prompt':'PRIVATE_PROMPT'},
                                  event_id=new_id(), thread_id=self.thread, execution_id=self.agent,
                                  request_id=request, occurred_at=self.at)
            self.assertEqual(normalize(event), event)
            self.assertNotIn('PRIVATE_', json.dumps(event))
            # A partial receipt for the same call must be replaced, not added.
            partial = event | dict(event_id=new_id(), input=2, output=1, occurred_at=self.at-.5)
            self.store.ingest(dict(recording_id=self.record['id'], event=partial))
            payload = dict(recording_id=self.record['id'], event=event)
            self.store.ingest(payload)
            self.assertFalse(self.store.ingest(payload))
        self.put('tool', tool='mcp', status='failed', duration_ms=9)
        report = self.store.finish(now=self.at+1)
        self.assertEqual(report['totals'], dict(input=41, output=15, cached=0, reasoning=0))
        self.assertEqual(sum(row['tokens'] for row in report['models']), 56)
        self.assertEqual(report['counter_complete'], dict(input=True, output=True, cached=False, reasoning=False))
        self.assertEqual(report['task_summary']['counter_complete'], report['counter_complete'])
        self.assertEqual(fields(report)['cache'], 'Unavailable')
        self.assertEqual(report['tool_failures'], 1)
        self.assertEqual({r['adapter'] for r in report['models']}, {'ollama-response-v1', 'numeric-fixture-v1'})
        self.assertIn('ollama-response-v1', text(report))
        self.assertIn('llama3.2:3b', inline(report))

    def test_local_identity_is_bounded_and_replayable(self):
        from codex_eval.adapters import receipt_usage
        for model in ('llama3.2:3b', 'PRIVATE_MODEL', 'gpt-6.1-sol', None):
            event = receipt_usage('ollama-response-v1', {'model':model, 'prompt_eval_count':2, 'eval_count':1},
                                  event_id=new_id(), thread_id=self.thread, execution_id=self.agent,
                                  request_id=new_id(), occurred_at=self.at)
            self.assertEqual(normalize(event), event)
            self.assertEqual(event['model'], model if model == 'llama3.2:3b' else None)
            self.assertNotIn('PRIVATE_MODEL', json.dumps(event))
        invalid = event | {'provider':'openai', 'model':'gpt-6.1-sol', 'model_source':'response'}
        self.assertIsNone(normalize(invalid)['model'])
        invalid = event | {'adapter':'PRIVATE_ADAPTER', 'model':'PRIVATE_MODEL'}
        self.assertNotIn('PRIVATE_', json.dumps(normalize(invalid)))
        for count in (True, -1, 2.5, '2'):
            with self.assertRaises(ValueError):
                receipt_usage('ollama-response-v1', {'prompt_eval_count':count}, event_id=new_id(),
                              thread_id=self.thread, execution_id=self.agent, request_id=new_id(), occurred_at=self.at)

    def test_partial_call_snapshot_and_late_receipt(self):
        call = new_id()
        self.usage(request_id=call, input=5, output=2, cached=None, reasoning=None)
        self.put('execution', parent_id=None, status='running')
        first = self.store.finish(now=self.at+10)
        self.assertFalse(first['counter_complete']['cached'])
        self.assertIn('Unfinished activity; final usage is unavailable', first['warnings'])
        self.usage(request_id=call, input=9, output=4, cached=0, reasoning=0)
        self.put('execution', parent_id=None, status='completed')
        second = self.store.report(self.record['id'])
        self.assertEqual(second['totals'], dict(input=9, output=4, cached=0, reasoning=0))
        self.assertTrue(all(second['counter_complete'].values()))
        self.assertGreater(second['analysis_version'], first['analysis_version'])
        self.assertEqual(fields(second)['cache'], '0')

    def test_missing_counter_in_one_call_is_not_a_measured_zero(self):
        self.usage(request_id=new_id(), cached=0, reasoning=0)
        self.usage(request_id=new_id(), cached=None, reasoning=None)
        report = self.store.finish(now=self.at+1)
        self.assertEqual(len(report['models']), 1)
        self.assertFalse(report['models'][0]['counter_complete']['cached'])
        self.assertFalse(report['models'][0]['counter_complete']['reasoning'])
        self.assertFalse(report['executions'][0]['counter_complete']['cached'])
        self.assertFalse(report['counter_complete']['reasoning'])
        self.assertEqual(fields(report)['cache'], 'Unavailable')
        self.assertEqual(report['totals']['input'], 200)

    def test_pilot_alias_and_harness_remain_exact(self):
        from codex_eval.adapters import receipt_usage
        event = receipt_usage('ollama-response-v1', {'model':'gemma4:latest', 'prompt_eval_count':1120, 'eval_count':20},
                              event_id=new_id(), thread_id=self.thread, execution_id=self.agent,
                              request_id=new_id(), occurred_at=self.at, harness='local-agent-pilot')
        self.assertEqual(event['model'], 'gemma4:latest')
        self.assertEqual(event['harness'], 'local-agent-pilot')
        self.assertEqual(normalize(event), event)
        invalid = normalize(event | {'harness':'PRIVATE_HARNESS'})
        self.assertIsNone(invalid['model'])
        self.assertNotIn('PRIVATE_', json.dumps(invalid))
