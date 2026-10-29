# Weather acceptance walkthroughs

The initial suite uses an offline Google Weather-shaped response and scripted
agent events. It does not contact Google or generate/execute an application using
a live agent. Check results in scripted histories test the reporting machinery;
they do not certify a generated weather app.

The reviewed base prompt, follow-up, and repair are in `codex_eval/weather.py`.
The fake transport provides success, authentication, rate-limit, unavailable,
malformed-response, and timeout cases. No geocoding, remote icons, or API keys
are required. Contract reference:
https://developers.google.com/maps/documentation/weather/current-conditions

| Scenario | Finish report acceptance |
| --- | --- |
| Desktop-shaped observation | Ungraded; coverage unknown; never imply actual desktop capture |
| Multiple prompts | Separate executions with combined observed consumption |
| Subagents | Three attributable executions, own usage counted once, a failed tool call visible |
| Failure then repair | Two preserved recordings under one task; failed check followed by passing check |
| MAGEN block | No downstream submission; security decision distinct from correctness |
| Finish during work | Partial activity; missing final usage never replaced with eventual full-turn totals |

The five report sections are consumption, contributors, operational failures,
check outcomes, and observations worth investigation. Every cost or count remains
traceable to a recording and source. Unrecognized counters, inclusive accounting,
conflicting IDs, and out-of-window events are rejected.

Future live smoke tests require explicit model/run limits and verified isolation,
authentication, event coverage, and interception. No live test runs automatically.
Desktop capture is a separate compatibility gate; CLI execution is the agreed
fallback, not a license to copy host credentials into test workloads.
