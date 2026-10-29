# Interfaces and trust boundaries

## Storage

SQLite schema version 1 contains tasks, recordings, normalized events, and
versioned analyses. Events and analyses cascade when a recording expires. A task
is distinct from a recording; continuing a task never overwrites an attempt.

## Normalized event v1

Every event has UUID `event_id`, `thread_id`, `execution_id`, Unix-seconds
`occurred_at`, and `kind`. The ingestion envelope supplies `recording_id`.
The thread and occurrence must match the explicit recording window. Late delivery
is allowed; occurrence after Finish is not. Event IDs deduplicate identical events;
conflicting duplicates fail. A recording holds at most 10,000 events.

Supported kinds:

| Kind | Accepted fields |
| --- | --- |
| execution | parent_id (UUID or null), status: running/completed/failed/interrupted |
| usage | scope=self, mode=cumulative, input/cached/output/reasoning (nonnegative integers or null), optional request_id, harness, provider, model, model_source, fixture_profile |
| changes | scope=recording, mode=snapshot, added/removed (nonnegative integers); latest snapshot replaces earlier snapshots |
| tool | allowlisted tool category, completed/failed status, optional duration_ms |
| check | allowlisted weather check, passed/failed/error, grader=weather-fixture-v1 |
| security | allow/block, allowlisted reason codes, SHA-256 policy_digest, duration_ms |

Tokens are cumulative **per model call** when request_id is present, otherwise
per execution for legacy adapters. request_id is a stable internal UUID assigned
by the trusted adapter, not a raw provider response ID. Updates replace the
previous snapshot for that call; distinct calls sum into the execution. One call
cannot belong to two executions. Do not mix per-call and whole-execution totals
for an execution: ingestion rejects that overlap instead of double counting.
Cached input is a subset of input; reasoning is a subset of output.

## Model and harness identity

- Harness (`codex` / `claude-code`) and provider (`openai` / `anthropic`) are
  independent. Each model call carries its own exact reported model ID; an
  adaptive agent can use several models without splitting it into fake agents.
- model_source is `response`, `harness`, or `unknown`. A configured/default model
  is not evidence of the model used. The current CLI event parser only reports
  harness=codex; the documented turn.completed sample has token usage without a
  model ID. No model is guessed from the agent writing this tool, UI selection,
  installed catalogs, or naming prefixes.
- Exact IDs, including snapshot suffixes where reported, are retained only from
  the reviewed catalog in models.py. Unreviewed identifiers are suppressed to
  prevent arbitrary metadata retention; numeric usage still appears under
  Model not reported. Extend the catalog when verifying a new model or provider.
  Aliases are never expanded into guessed versions. Identity_source describes
  the emitter's evidence; it is not cryptographic proof.
- Reports include provider/harness/model/source usage groups overall and within
  each execution. Unknown attribution is explicit and is not distributed across
  known models. If a model changes inside a single cumulative bucket without
  call boundaries, preserve its latest numeric usage but suppress attribution
  and warn. Rates are not inferred: real USD remains unavailable.
- fixture_profile=weather-v1 selects synthetic fixture pricing independently
  of model identity and is allowed only in controlled-simulation recordings.
  Legacy sim-weather-v1 events are read as fixture_profile=weather-v1 with
  model=null. Raw historical events are not rewritten; normalized replays remain
  idempotent. Newly generated fixture events never put a simulator name in model.

The current CLI parser cannot establish subagent hierarchy or production model
identity. Live Codex capture and a Claude Code adapter are not implemented.
Cross-provider normalized-event tests verify the accounting contract, not live
interoperability. No model inference or authentication is launched by this work.

References: [Codex JSON events](https://learn.chatgpt.com/docs/non-interactive-mode),
[Codex rerouting notifications](https://learn.chatgpt.com/docs/app-server),
[OpenAI model identity](https://developers.openai.com/api/docs/models/gpt-6.1-sol),
[Anthropic model IDs and versioning](https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions).

Line counts describe the **recording-wide net diff from its starting point**.
They are not cumulative edit operations or per-agent counts to sum. The trusted
emitter establishes the baseline and supplies only numeric counts; no source,
paths, patch text, Git inspection, or filesystem access is added by this event.
The CLI parser does not derive counts from file-change items. Missing snapshots
remain unavailable. Existing stored recordings need no migration or backfill.
Current fixture snapshots contain scripted examples, not measured file edits.

Cached input is displayed as a token count without a percentage. Cached output
is shown as **Not reported**: the current adapter supplies no such measurement.
It is not inferred from reasoning, cache-write tokens, or generated output.
Historical `sim-weather-v1` values are interpreted as a fixture pricing profile,
never an actual model. No model ran in those sample recordings.

Authenticated emitters must be trusted separately; a claimed timestamp, origin,
grader ID, or parent relationship is not cryptographic evidence. The initial
transport does not accept untrusted agents as authoritative graders.

## MAGEN adapter

`MagenGate.inspect(text, origin)` returns only action, reason codes, policy digest,
and duration. User-origin proposals bypass inspection as requested. Agent and
unknown origins require an operational detector; detector errors deny submission.
The caller must establish origin outside the agent and hold the submission until
approval. This is not a proxy for Codex inference and cannot stop unrelated tools.

Isolated tests load reviewed `gateway/detectors.py` and `gateway/types.py` from
MAGEN, with an empty staging-package initializer to avoid importing the broader
gateway or starting its services. The digest includes both files and the strict
adapter policy. This adapter intentionally blocks any detector finding and is
not equivalent to the broader gateway's configurable policy or semantic engines.
Nothing is imported from MAGEN on the host.

## Local panel

HTTP binds only to 127.0.0.1. Exact Host and Origin checks, a custom control header,
one-time login, HttpOnly/SameSite cookies, no CORS, and a restrictive CSP protect
browser controls. The Unix control socket is owner-only. Ingestion uses a distinct
bearer credential. Raw bodies and arbitrary error messages are never logged.

Only the current OS user is in scope; malware already running as that user can
access user-owned credentials and state. The panel is not a multi-user service.
