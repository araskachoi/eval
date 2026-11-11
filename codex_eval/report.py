import html
import json
from .summary import inline


def render(report):
    """Offline export: escaped metrics only; no scripts, fonts, or remote assets."""
    def table(rows):
        return '<table>' + ''.join('<tr>' + ''.join('<td>' + html.escape(str(v)) + '</td>' for v in row) + '</tr>' for row in rows) + '</table>'
    sections = [
        ('What did this recording use?', table([
            ('Input / cached / output / reasoning', json.dumps(report['totals'])),
            ('Elapsed seconds', report['elapsed_seconds']),
            ('API-equivalent USD', report['api_equivalent_usd']),
            ('Simulated USD (not billed)', report['simulated_usd']),
            ('Coverage', report['coverage']),
            ('Counter completeness', json.dumps(report['counter_complete'])),
        ])),
        ('Where did consumption accumulate?', table([
            ('Execution', 'Parent', 'Own tokens', 'Tool failures', 'Status'),
            *[(n['id'], n['parent_id'] or 'root / unknown', n['own_tokens'], n['failures'], n['status']) for n in report['executions']],
        ])),
        ('What went wrong operationally?', '<pre>' + html.escape(json.dumps({'failed_tool_calls':report['tool_failures'],'warnings':report['warnings'], 'security':report['security']}, indent=2)) + '</pre>'),
        ('Did it meet its checks?', '<p>' + html.escape(report['outcome']) + '</p>' + table((a['check'], a['status'], a['grader'], a['scope'], a['provenance'], a['execution_id']) for a in report['assessments'])),
        ('Models and harnesses reported', table([
            ('Harness', 'Provider', 'Exact model ID', 'Identity source', 'Adapter', 'Tokens'),
            *[(n['harness'] or 'Not reported', n['provider'] or 'Not reported', n['model'] or ('No model — simulation' if n['fixture_profile'] else 'Not reported'), n['model_source'], n['adapter'], n['tokens']) for n in report.get('models', [])],
        ])),
        ('What deserves investigation?', '<pre>' + html.escape(json.dumps({'findings':report['findings'],'task_history':report.get('task_summary')}, indent=2)) + '</pre>'),
    ]
    return '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Finish report</title><style>body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:20px;color:#202b35}td{padding:10px;border-bottom:1px solid #ddd;overflow-wrap:anywhere}pre{white-space:pre-wrap}h2{margin-top:36px}</style>
<h1>Finish report</h1>''' + inline(report) + '<details><summary>Technical diagnostics</summary><p>Recorded observations, not an explanation of model intent. Local resources unavailable unless explicitly measured.</p>' + ''.join('<section><h2>' + title + '</h2>' + body + '</section>' for title, body in sections) + '</details></html>'
