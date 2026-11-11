"""Bounded, source-reviewed assessment definitions; never retain review content."""

GRADERS = {
    'weather-fixture-v1': dict(
        checks={'coordinates', 'display', 'timeout', 'units', 'rate_limit', 'credential_output'},
        scope='weather-fixture', provenance='scripted-weather-fixture'),
    'reference-match-v1': dict(
        checks={'exact_match'}, scope='supplied-reference', provenance='trusted-emitter-comparison'),
}


def assessment(event):
    definition = GRADERS.get(event.get('grader'))
    if definition is None or event.get('check') not in definition['checks']:
        raise ValueError('Unregistered check/grader pair')
    if event.get('status') not in {'passed', 'failed', 'error'}:
        raise ValueError('Invalid check status')
    for key in ('scope', 'provenance'):
        if key in event and event[key] != definition[key]:
            raise ValueError('Assessment definition mismatch')
    return {key: event[key] for key in ('check', 'grader', 'status')} | {
        key: definition[key] for key in ('scope', 'provenance')}
