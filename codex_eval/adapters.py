"""Reviewed receipt adapters. No network, credential, or automatic capture access."""

# Extend in source review with an exact model allowlist and a receipt contract test.
RUNTIMES = {
    'ollama-response-v1': dict(provider='ollama', harnesses=('ollama', 'local-agent-pilot'),
                               models={'llama3.2:3b', 'gemma4:latest'}, model_source='response'),
    'numeric-fixture-v1': dict(provider='synthetic', harnesses=('numeric-fixture',),
                              models={'counter-model-v1'}, model_source='response'),
}


def receipt_usage(adapter, receipt, *, event_id, thread_id, execution_id, request_id, occurred_at, harness=None):
    """Map one explicitly supplied cumulative call receipt; normalize at the boundary.

    The caller owns correlation and stable request/event UUIDs. A retry is a new
    request; redelivery reuses its event UUID. Never supply delta receipts here.
    """
    from .core import normalize
    runtime = RUNTIMES[adapter]
    if adapter == 'ollama-response-v1':
        counters = dict(input=receipt.get('prompt_eval_count'), output=receipt.get('eval_count'),
                        cached=None, reasoning=None)
    else:
        counters = {key: receipt.get(key) for key in ('input', 'cached', 'output', 'reasoning')}
    return normalize(dict(event_id=event_id, thread_id=thread_id, execution_id=execution_id,
                          request_id=request_id, occurred_at=occurred_at, kind='usage',
                          scope='self', mode='cumulative', adapter=adapter,
                          provider=runtime['provider'], harness=harness if harness is not None else runtime['harnesses'][0],
                          model_source=runtime['model_source'], model=receipt.get('model'), **counters))
