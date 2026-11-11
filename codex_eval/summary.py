"""One metrics-only presentation for terminal, saved files, and inline snapshots."""
import html
from pathlib import Path
from string import Template

from .core import identifier
from .models import model_summary

CASES = {
    'desktop': ('Basic recording', 'A sample of a single recorded agent action. This does not test live desktop capture.'),
    'multi': ('Multiple agent actions', 'Two scripted agent actions in one recording. Separate actions do not create separate recordings.'),
    'subagents': ('Main agent with two helpers', 'One recording contains a main agent and two simulated subagents. One helper has a failed weather lookup.'),
    'repair': ('Weather app · Timeout recovery', 'Two recordings of the same sample task: the first fails the timeout check; the second passes it.'),
    'blocked': ('Prompt blocked by MAGEN', 'A synthetic unsafe proposal is blocked before submission to a fake endpoint.'),
    'partial': ('Missing final usage', 'A simulated agent is still running when recording stops. Its final token usage is missing.'),
}


def recording_details(record):
    title, description = CASES.get(record.get('sample_case'), (
        'Sample recording' if record['source'] == 'controlled-simulation' else f"Task {record.get('task_number', '')}".strip(),
        'Scripted test data; the original sample name was not saved.' if record['source'] == 'controlled-simulation' else 'A recording window in a selected chat. A task title was not collected.',
    ))
    return {'title': f"{title} · Recording {record.get('number', 1)}", 'description': description}


def agent_labels(report):
    children = sorted((n for n in report['executions'] if n['parent_id'] is not None), key=lambda n: n['id'])
    labels = {n['id']: f'Subagent {i}' for i, n in enumerate(children, 1)}
    roots = sorted((n for n in report['executions'] if n['parent_id'] is None), key=lambda n: n['id'])
    labels.update({n['id']: 'Main agent' if len(roots) == 1 else f'Agent action {i}' for i, n in enumerate(roots, 1)})
    return labels


def fields(report):
    totals = report['totals']
    known = lambda n: 'Unavailable' if n is None else f'{n:,}'
    tokens = None if any(totals[k] is None for k in ('input', 'output')) else totals['input'] + totals['output']
    seconds = report['elapsed_seconds']
    elapsed = 'In progress' if report['recording']['finished'] is None else 'Unavailable' if seconds is None else f'{seconds:,.1f} s'
    cached, inputs = totals['cached'], totals['input']
    cache_complete = report['counter_complete']['cached'] and all(n['usage'] and n['usage']['cached'] is not None for n in report['executions'])
    cache = 'Unavailable' if not cache_complete or cached is None else known(cached)
    changes = report.get('changes', {})
    added, removed = changes.get('added'), changes.get('removed')
    app = report['recording'].get('application')
    simulated = report['recording']['source'] == 'controlled-simulation'
    cost = report['simulated_usd'] if simulated else report['api_equivalent_usd']
    return {
        'source': 'Sample data · simulated run' if simulated else 'Desktop capture unverified',
        'tokens': known(tokens), 'elapsed': elapsed,
        'cost': 'Unavailable' if cost is None else f'${cost}',
        'cost_label': 'Simulated USD' if simulated else 'Estimated USD',
        'cache': cache, 'input': known(inputs), 'output': known(totals['output']),
        'cached_output': 'Not reported',
        'lines': 'Unavailable' if added is None or removed is None else f'+{added:,} −{removed:,}',
        'lines_added': known(added), 'lines_removed': known(removed),
        'model': 'Simulation — no AI model ran' if simulated else model_summary(report.get('models', [])),
        'application': f"Local Eval {app['version']} · {app['release_id']}" if app else 'Recorded app version unavailable',
        'coverage': 'Partial observations' if report['coverage'] == 'incomplete' else 'Recorded events consistent',
        'outcome': report['outcome'],
    }


def execution_rows(report):
    labels = agent_labels(report)
    return [(labels[n['id']], 'Unavailable' if n['own_tokens'] is None else f"{n['own_tokens']:,}", n['status']) for n in report['executions']]


def text(report):
    f = fields(report)
    lines = [recording_details(report['recording'])['title'], f['source'], f"Tokens: {f['tokens']} | Elapsed: {f['elapsed']} | {f['cost_label']}: {f['cost']} | Cached input: {f['cache']} | Cached output: {f['cached_output']} | Lines: {f['lines']}",
             f['application'],
             f"Model: {f['model']}",
             f"{f['coverage']} · {f['outcome']}", f"Input: {f['input']} | Output: {f['output']} | Cache is a subset of input."]
    lines.extend(f'{name}: {tokens} own tokens · {status}' for name, tokens, status in execution_rows(report))
    if report['recording']['source'] != 'controlled-simulation':
        for row in report.get('models', []):
            lines.append(f"{row['harness'] or 'Harness not reported'} | {row['provider'] or 'Provider not reported'} | {row['model'] or 'Model not reported'} | {row['model_source']} | {row.get('adapter') or 'Adapter not reported'} | {row['tokens'] if row['tokens'] is not None else 'Unavailable'} tokens | Estimated USD: unavailable")
    lines.extend(f"{a['check']}: {a['status']} | {a['grader']} | {a['scope']} | {a['provenance']}" for a in report.get('assessments', []))
    lines.append('USD is an estimate or simulation, never a billed amount. Missing values are unavailable, not zero.')
    return '\n'.join(lines) + '\n'


def inline(report):
    values = {k: html.escape(str(v)) for k, v in fields(report).items()}
    values.update({k: html.escape(v) for k, v in recording_details(report['recording']).items()})
    values['root_id'] = 'eval-' + identifier(report['recording']['id'])
    values['rows'] = ''.join('<tr>' + ''.join('<td>' + html.escape(value) + '</td>' for value in row) + '</tr>' for row in execution_rows(report))
    values['model_rows'] = ''.join('<tr>' + ''.join('<td>' + html.escape(str(value)) + '</td>' for value in (
        row['harness'] or 'Not reported', row['provider'] or 'Not reported',
        row['model'] or ('No model — simulation' if row['fixture_profile'] else 'Not reported'),
        row['tokens'] if row['tokens'] is not None else 'Unavailable',
    )) + '</tr>' for row in report.get('models', []))
    return Template((Path(__file__).parent / 'web/summary.html').read_text()).substitute(values)
