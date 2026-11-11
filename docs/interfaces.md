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
| usage | scope=self, mode=cumulative, input/cached/output/reasoning (nonnegative integers or null), optional request_id, harness, provider, model, model_source, fixture_profile, adapter |
| changes | scope=recording, mode=snapshot, added/removed (nonnegative integers); latest snapshot replaces earlier snapshots |
| tool | allowlisted tool category, completed/failed status, optional duration_ms |
| check | registered check/grader pair, passed/failed/error; definition-derived scope and provenance |
| security | allow/block, allowlisted reason codes, SHA-256 policy_digest, duration_ms |

Tokens are cumulative **per model call** when request_id is present, otherwise
per execution for legacy adapters. request_id is a stable internal UUID assigned
by the trusted adapter, not a raw provider response ID. Updates replace the
previous snapshot for that call; distinct calls sum into the execution. One call
cannot belong to two executions. Do not mix per-call and whole-execution totals
for an execution: ingestion rejects that overlap instead of double counting.
Cached input is a subset of input; reasoning is a subset of output.

## Model and harness identity

- Built-in harness (`codex` / `claude-code`) and provider (`openai` / `anthropic`) are
  independent. Each model call carries its own exact reported model ID; an
  adaptive agent can use several models without splitting it into fake agents.
- model_source is `response`, `harness`, or `unknown`. A configured/default model
  is not evidence of the model used. The current CLI event parser only reports
  harness=codex; the documented turn.completed sample has token usage without a
  model ID. No model is guessed from the agent writing this tool, UI selection,
  installed catalogs, or naming prefixes.
- Exact IDs, including snapshot suffixes where reported, are retained only from
  the reviewed catalog in models.py or runtime definitions in adapters.py.
  Unreviewed identifiers are suppressed to
  prevent arbitrary metadata retention; numeric usage still appears under
  Model not reported. Extend the reviewed definitions when verifying a new model or provider.
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

### Reviewed runtime extensions

`adapters.py:RUNTIMES` is the source-reviewed extension point. Each versioned
adapter fixes provider, allowed harnesses, permitted identity source, and exact
model IDs.
There is no event-supplied registry, wildcard, arbitrary model metadata, or dynamic
plugin import. Extend a definition only alongside receipt/normalization and
accounting tests. `adapter` is an allowlisted provenance claim, not authentication.
Only attach trusted emitters to either ingestion transport.

`ollama-response-v1` accepts exact response IDs `llama3.2:3b` and `gemma4:latest`,
provider `ollama`, harness `ollama` or `local-agent-pilot`, and source `response`.
The latter harness/model are verified against the saved bounded pilot receipts;
`latest` remains the exact reported alias, with no snapshot inferred.
`receipt_usage` maps explicitly supplied Ollama
`prompt_eval_count` to input and `eval_count` to output. It leaves cached and
reasoning null; absent counters are never filled with zero. An unreviewed model
still contributes numeric usage but its name is discarded. No alias expansion,
model discovery, HTTP request, or local runtime launch is performed.
`numeric-fixture-v1` uses provider `synthetic`, harness `numeric-fixture`, and exact
model `counter-model-v1`; it maps input/cached/output/reasoning directly and is a
non-RAG synthetic contract fixture, not evidence that a real model ran.

A trusted caller supplies stable event/request UUIDs, explicit thread/execution
correlation, and occurrence time to `receipt_usage`; optional `harness` selects
a reviewed harness (default: the first in the definition). Send the returned usage
event through the existing ingestion envelope. The private Unix control client
`codex_eval.__main__.control(state, {'action':'ingest', 'recording_id':record_id,
'event':event})` avoids reading the bearer credential. This is explicit ingestion,
not live interception. Repeated snapshots reuse request_id; exact redelivery also
reuses event_id. Each model attempt/retry gets a new request_id. Emit execution
status and generic tool events separately; no RAG-only category is added.

### Counter availability

Events retain null counters. Model groups, executions with usage, recording
reports, and linked task summaries expose `counter_complete` for each of the four counters.
These flags describe counter availability across received call snapshots;
collection gaps, missing boundaries, regressions, and unfinished executions still
require the independent coverage/warnings fields. The flags cannot establish that
an adapter delivered every call. `totals` are sums of **observed** values, null
when none were reported; a numeric subtotal with a false completeness flag is
not a complete measurement or an assertion that missing usage was zero. Cached
input displays Unavailable when any received call lacks it, even if another call
reported a measured zero. Counter availability does not establish billing
correctness; production USD remains unavailable.

### Registered assessments

`checks.py:GRADERS` binds each versioned grader to a finite check set, scope, and
provenance. Extend it in source review with normalization and report tests.
`weather-fixture-v1` retains its existing six check IDs and derives scope
`weather-fixture`, provenance `scripted-weather-fixture`. `reference-match-v1`
accepts only `exact_match`, scope `supplied-reference`, provenance
`trusted-emitter-comparison`. Its emitter compares an output with an explicit
reference and supplies passed/failed/error; eval does not collect either text,
execute grader code, or infer semantic quality. This check does not establish RAG
accuracy, grounding, or retrieval quality. Manual RAG reviews remain external.

Scope/provenance are derived from the registered definition; conflicting supplied
values fail. Arbitrary answers, references, comments, and grader IDs are not saved.
A claimed grader/provenance does not prove the emitter performed the comparison.
Reports retain `assessments` keyed by execution/grader/check, with latest status
within that key. Different executions cannot overwrite one another. The compact
`checks` map retains legacy weather names and namespaces other graders; error or
failure in any execution takes precedence over a passing execution. Outcomes
refer only to supplied checks, with no claim of complete assessment coverage.
Old stored events need no migration; replay derives the same reviewed metadata.

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
