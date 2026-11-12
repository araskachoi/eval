# Local Eval

A small, local metrics collector and **Finish report** for understanding agent work.
Python 3.14+; standard library only. No model calls, telemetry export, or background
service starts on installation or import.

## Quick start

Follow the [quick start guide](docs/quickstart.md) to install the Record skill,
start the collector, open a recording, and view a report. From a source checkout
with Python 3.14+:

```sh
python3 -m codex_eval doctor
python3 scripts/install_record_skill.py --dry-run
python3 scripts/install_record_skill.py
python3 -m codex_eval collector start
```

Keep the collector terminal open, reload skills if needed, then use `$record`
or select Record from the desktop slash menu. Use `$record stop` to finish.
The installer prints its destination and matching collector command; see the
[guide](docs/quickstart.md) for custom paths, updates, exports, and removal.
No model credentials are needed. No live usage appears without an event adapter.

For manual updates, saved app versions, and rollback, use the
[publish workflow](docs/releases.md). After its first setup, publish a finished
change with `python3 scripts/publish_app.py publish`; it runs isolated checks,
switches the collector, and refreshes the global Record skill together.

## Current limitations

This is an experimental, local collector and reporting foundation. It is not
ready to serve as an automatic live usage meter for public users.

| Area | Current behavior and limitation |
| --- | --- |
| Live capture | No live Codex desktop interception, hooks, OTLP receiver, or ready-made Codex/Claude Code adapter. `/record` arms a window; it does not automatically collect activity. |
| Metrics | Real token, cache, model, and net line-change data require trusted, explicitly correlated events. Missing values stay unavailable. Cached output is not reported; CPU/RAM sampling is unimplemented. |
| Cost | Production pricing and billed USD are unavailable. Sample costs use fictitious rates and are labeled Simulated USD. |
| Recording scope | One active recording per collector state. Current-chat controls require a valid `CODEX_THREAD_ID`; the panel cannot detect the foreground chat. Missing child-agent events mean incomplete totals. |
| Skill overhead | Skill controls invoke the agent and may consume tokens. Reliable control-turn exclusion and removal of later context effects are unimplemented. |
| Platforms | Desktop integration has been reviewed locally on macOS. Python 3.14+ and POSIX shell/socket/permission support are required. Linux desktop integration is unverified; native Windows installation is unsupported. |
| Harness portability | A custom skills directory changes discovery only. Another harness still needs a verified identity and metrics adapter; cross-harness capture is not implemented. |
| Installation | Source-checkout workflow; installer/integration assets are not included in the Python wheel. Manual publishing saves releases and refreshes the global skill. Paths must remain stable. No save watcher or launch-at-login service is installed. |
| Availability | Collector must be running, either in a foreground terminal or started by the publisher. Managed updates refuse active windows; other restarts/crashes interrupt them. Inline cards are snapshots, and renderer support varies. |
| Evaluation | Acceptance recordings and security checks are synthetic. Explicit benchmark runs use Ollama or Codex CLI. Results characterize the selected model and harness on the benchmark task. |
| Development tests | Tests require the dedicated VM and verified rootless containers. The launcher depends on separately provisioned local Podman/VM assets, so a fresh clone is not a turnkey test environment. |

See [Interpretation and limits](#interpretation-and-limits), the
[event contract](docs/interfaces.md), and the dated
[verification record](docs/verification.md) before interpreting results.

## What works in this version

- Record / Finish / Continue task using the CLI; browse reports in an authenticated local panel.
- Separate tasks and attempts, own-execution token accounting, tool failures,
  parent relationships, late-event analysis versions, and explicit partial data.
- Five-part Finish reports and offline HTML exports.
- Strict normalized-event ingestion and a content-dropping CLI-event parser.
- Provider-independent MAGEN gate using the existing detector implementation in
  isolated tests; Ollama is not required.
- Six scripted acceptance walkthroughs and a fail-closed rootless-container
  launcher in a dedicated Linux VM.
- Opt-in [model regression](regression/README.md) with isolated ledger and
  filesystem grading, resumable runs, and comparison of manually managed results.

**This is an instrumented foundation, not verified live Codex desktop capture.**
Record currently arms a window for explicitly correlated normalized events; it
does not intercept the desktop app. No private Codex history or database is read.
The explicit regression runner uses synthetic tasks. Codex CLI inference uses
credentials supplied to the trusted launcher and may incur API charges.

## Run locally

From this directory (installation is optional):

```sh
python3 -m codex_eval doctor
python3 -m codex_eval collector start
```

## Record from the Codex composer

The `record` skill template is packaged in `integrations/codex/record`. Install
it using the [installer](scripts/install_record_skill.py); do not copy the raw
template. The default destination is `~/.agents/skills/record`; `--skills-dir`
selects another discovery root. Existing skills are never overwritten. The
installed skill contains this checkout's absolute path, its Python interpreter,
and the selected collector state. It does not change global configuration.

Enabled skills appear in the desktop slash menu: type `/` and select **Record**;
`$record` is the explicit skill alternative. Restart Codex if discovery has not
updated. This is an agent-mediated skill, not a new built-in recording mode or a
model-free keyboard command.

| Request | Behavior |
| --- | --- |
| `/record` or `$record` | Arm a window for this chat; repeating start leaves the same window open |
| `/record stop` | Close this chat's window and show the shared report; repeat stop preserves its finish time |
| `/record status` | Show only this chat's recording state |
| `/record report` | Show the latest report for this chat |

The equivalent CLI is `python3 -m codex_eval record [start|stop|status|report]`.
It requires the invoking `CODEX_THREAD_ID`; it has no manual thread override.
Stop/report accept `--format inline --output NEW_FILE` for the interactive
snapshot, or text output/file export. The existing `on --thread` controls remain
available for deliberate external operation.

The default installation uses `~/Library/Application Support/codex-eval`, matching
the CLI default. Use the collector command printed by the installer. To use the
existing development panel's `.runtime/acceptance-metrics` instead, pass that
path with `--state` during installation and to all collector/panel commands.
Keep the matching collector running in a foreground terminal; the skill does
not install a service or silently launch one. Reinstall after moving the checkout
or Python interpreter. See the [quick start](docs/quickstart.md) for details.

**Live capture is still unavailable.** Starting a window does not intercept
Codex, run a benchmark, or automatically collect tokens/model IDs/line counts.
No telemetry configuration, hooks, or submission interception are installed.
The skill's own control turns consume tokens, and reliable control-turn exclusion
is not implemented. Starting/stopping from another chat cannot change the active
window. A missing chat identity or stopped collector fails without a fallback.

Sources: [official skill discovery documentation](https://learn.chatgpt.com/docs/build-skills) and [slash commands](https://learn.chatgpt.com/docs/reference/slash-commands).

## Open the local panel

In another terminal:

```sh
python3 -m codex_eval panel
```

Open `http://127.0.0.1:8765` in Codex's browser panel or a local browser and enter
the one-time code from the second command. It expires in 60 seconds; the resulting
session lasts one hour. Credentials never appear in the URL. The browser panel
still requires an explicit chat UUID; the collector's own environment cannot
identify the chat currently visible in another surface.

CLI controls use a private Unix socket and make no model calls:

```sh
python3 -m codex_eval on --thread CHAT_UUID
python3 -m codex_eval off --thread CHAT_UUID
python3 -m codex_eval status
python3 -m codex_eval on --thread CHAT_UUID --task TASK_UUID
python3 -m codex_eval report RECORDING_UUID --output report.html
```

When invoked by Codex in the current chat, `on`, `off`, and `summary` use the
validated `CODEX_THREAD_ID` automatically. In an ordinary terminal, pass
`--thread CHAT_UUID`. An explicit ID selects that chat deliberately; no command
guesses from recency. Finish refuses to close a different chat's recording.

```sh
python3 -m codex_eval summary
python3 -m codex_eval summary --output summary.txt
python3 -m codex_eval summary --format inline --output summary.html
```

The terminal and inline summary share the same four values: total tokens,
elapsed recording time, USD, and cached input, plus cached output and line changes.
Cached input is a token count; cached output is currently “Not reported.” Lines
shows added/removed counts from the latest recording-level net-diff snapshot.
Old recordings without that snapshot show “Unavailable”; sample line counts are
scripted. No source text or paths are collected. `sim-weather-v1` is a simulation
legacy label for made-up rates, not a real AI model. New fixtures store that
information in `fixture_profile`, with `model` left null. Saving text produces exactly the
terminal output; files are owner-only and never overwritten. Inline output is
an HTML fragment for the conversation renderer, with an expandable breakdown.
It is a snapshot, without network requests or live Record/Finish controls.
Inline rendering and expansion were confirmed in this Codex installation;
backend control through that surface remains unverified. Saved full reports
include the same compact summary, with technical diagnostics collapsed.
If this chat has no recordings, summary fails rather than showing another chat.
Sample USD uses synthetic fixture rates; production pricing is unavailable.

The panel calls measurement windows **recordings**. A recording can contain
multiple prompts and subagents; recordings of the same task remain linked.
Reviewed sample cases have fixed, readable names. Repeated verification
runs stay under “Earlier sample copies,” separate from live recordings. No
prompt-derived titles are stored. Legacy samples without known provenance use
“Sample recording”; real tasks without collected titles use a task number.
Identifiers and raw metrics appear only in collapsed technical details.
The browser's unverified Record/Continue controls have been removed; CLI controls
remain available for explicitly correlated metrics.

Agent controls appear only when meaningful: single-agent reports have no
grouping or sorting controls. Multiple agents can be compared by tokens, tool
time, or failed calls when values differ. Hierarchy groups subagents under their
parent; comparison lists them by the selected metric and displays that metric.
Changing the view does not change the recording or token accounting.

“Models used” reports the exact model IDs supplied by trusted response/harness
events, with provider, harness, and token totals. Per-call accounting supports
adaptive agents switching models within one execution, including mixed-provider
events. Model snapshots are preserved as reported, never guessed. Unknown models
stay unattributed; new IDs require review in the small model catalog or a
source-reviewed runtime adapter definition. Explicit Ollama receipt ingestion and
a synthetic numeric adapter share the same call accounting contract. Neither
automatically captures runtime activity. Non-weather supplied-reference checks
use a registered grader with bounded scope; manual RAG quality reviews remain
external. See the [extension contracts](docs/interfaces.md#reviewed-runtime-extensions). Synthetic
pricing is separate from model identity. Older sample reports are reinterpreted
without changing stored history. Live Codex model capture and a Claude Code
adapter remain unimplemented; the tests are synthetic and make no model calls.

Finish closes immediately without cancelling agent work. Starting another
recording under the task preserves both attempts. Unknown usage is never zero.
Stopping or restarting the collector closes unfinished windows with a gap.
If a crash leaves a stale socket, stop the collector and run
`python3 -m codex_eval cleanup`; this refuses to remove a live collector's socket.

Runtime state defaults to `~/Library/Application Support/codex-eval` (0700).
Use `--state /absolute/private/directory` before the command to select another
location. SQLite, ingestion credentials, and control sockets are owner-only.
Metrics expire after 30 days; explicit HTML exports and OS backups are separate
copies. `purge` applies retention, not forensic media erasure.

## Ingesting metrics

`POST /ingest` accepts a JSON object with `recording_id` and `event`, using the
separate bearer credential in the collector state's `ingestion.token` file.
Keep this token out of commands, URLs, reports, shell history, and logs.
Browser-origin ingestion is denied. This endpoint is **not an OTLP endpoint**.

The normalized contract is documented in [docs/interfaces.md](docs/interfaces.md).
Only supported fields survive normalization. Content, commands, arbitrary errors,
and unknown attributes are discarded. Authentication does not establish that an
external emitter or grader is truthful: attach only trusted, verified adapters.

## Isolated acceptance tests

Do **not** run the security fixtures or tests directly on the host. Follow
[docs/security.md](docs/security.md). Once the dedicated `eval-sandbox` VM is
running and its reviewed Python image is staged:

```sh
# Terminal 1: hold the dedicated VM; Ctrl-C stops it.
python3 scripts/isolated.py hold

# Terminal 2: inspect, then test. Stage the pinned image only if absent.
python3 scripts/isolated.py preflight
python3 scripts/isolated.py stage
python3 scripts/isolated.py test --magen /absolute/path/to/magen
```

The runner copies only reviewed source and tests into a fresh rootless container;
it mounts no host files, inherits no credentials, has no workload network, and
checks effective configuration before starting. It removes the container after
success, failure, or timeout. The test environment uses fake endpoints and keys.

The local Podman executable and VM files under `.runtime/` are development assets,
not dependencies shipped by the Python package. The launcher fails if they are
missing. It never installs a rootful daemon or silently runs tests on the host.

See [docs/acceptance.md](docs/acceptance.md) for scenario definitions and limits.

## Interpretation and limits

- Desktop observation, simulated fixtures, and controlled execution have different
  capabilities. A simulated execution tree is not evidence of desktop support.
- Own usage is summed once. Inclusive usage is rejected rather than guessed.
  Tool counts do not establish per-tool token costs; retries are not inferred.
- Local CPU/RAM collection is not implemented yet. Hosted inference resources
  are unavailable. Missing children and attribution remain visible limitations.
- Production pricing is not bundled. API-equivalent and billed USD are unavailable
  until a verified pricing catalog and live adapter are added. The fixture's
  `synthetic-v1` rates are deliberately fictitious and labeled **Simulated USD**.
- Outcomes reflect supplied checks, not general quality. Normal chats are Ungraded.
  Fake endpoints do not establish real-agent correctness or MAGEN effectiveness.
- Metrics-only analysis cannot explain semantic failures or reconstruct a prompt.
  Compare configurations, checks, and coverage before interpreting differences.
- MAGEN checks agent-origin proposals; direct user prompts are not automatically
  sanitized. Inspection approval never relaxes isolation or execution permissions.
- Rootless containers plus a VM reduce risk; they cannot prove immunity to runtime
  or hypervisor vulnerabilities. Unverifiable controls stop execution.

## Removal

Stop the collector with Ctrl-C and stop only the dedicated `eval-sandbox` VM.
If installed, remove only the `record` skill folder printed by the installer.
No global Codex configuration needs reverting. Delete exported reports separately.
Review runtime-state and VM removal explicitly rather than deleting unrelated
Podman machines, images, credentials, or application data.
