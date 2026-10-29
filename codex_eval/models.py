"""Reviewed identities, independent of harnesses and synthetic pricing."""
CATALOG = {
    'openai': {'gpt-6.1-sol', 'gpt-6.1-terra', 'gpt-6-astra', 'gpt-6-sol', 'gpt-6-luna'},
    'anthropic': {'claude-opus-5', 'claude-sonnet-5', 'claude-opus-4-6', 'claude-opus-4-7',
                  'claude-opus-4-8', 'claude-sonnet-4-6', 'claude-sonnet-4-5-20250929', 'claude-haiku-4-5-20251001'},
}
COUNTERS = ('input', 'cached', 'output', 'reasoning')


def identity(event):
    provider = event.get('provider') if event.get('provider') in CATALOG else None
    source = event.get('model_source') if event.get('model_source') in {'response', 'harness'} else 'unknown'
    model = event.get('model')
    # shortcut: unreviewed IDs are suppressed; extend this catalog when verifying another model/adapter.
    model = model if isinstance(model, str) and model in CATALOG.get(provider, ()) and source != 'unknown' else None
    fixture = 'weather-v1' if event.get('fixture_profile') == 'weather-v1' or event.get('model') == 'sim-weather-v1' else None
    return dict(provider=provider, model=model, model_source=source if model else 'unknown',
                harness=event.get('harness') if event.get('harness') in {'codex', 'claude-code'} else None,
                fixture_profile=fixture)


def sum_counters(items):
    return {key: sum(u[key] for u in items if u[key] is not None) if any(u[key] is not None for u in items) else None for key in COUNTERS}


def breakdown(usages):
    groups = {}
    for usage in usages:
        key = tuple(usage[k] for k in ('harness', 'provider', 'model', 'model_source', 'fixture_profile'))
        groups.setdefault(key, []).append(usage)
    rows = []
    for key, items in groups.items():
        row = dict(zip(('harness', 'provider', 'model', 'model_source', 'fixture_profile'), key))
        row['totals'] = sum_counters(items)
        row['tokens'] = sum(row['totals'][k] for k in ('input', 'output')) if all(row['totals'][k] is not None for k in ('input', 'output')) else None
        row['usage_records'] = len(items)
        row['usage_complete'] = all(all(u[k] is not None for k in ('input', 'cached', 'output')) for u in items)
        row['api_equivalent_usd'] = None
        rows.append(row)
    return rows


def model_summary(rows):
    known = {row['model'] for row in rows if row['model']}
    unknown = any(not row['model'] and not row['fixture_profile'] for row in rows)
    if not known:
        return 'Not reported'
    return (next(iter(known)) if len(known) == 1 else f'{len(known)} models') + (' · some usage unattributed' if unknown else '')
