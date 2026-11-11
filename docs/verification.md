# Local verification

## Runtime adapters and assessment definitions — 2026-11-09

- Implemented source-reviewed Ollama receipt and synthetic numeric adapters, exact
  model/harness allowlists, registered check/grader pairs, and counter-availability
  flags across call groups, executions, recordings and linked attempts.
- All **79 tests passed** in 6.207 seconds using
  `python3 scripts/isolated.py test --magen /absolute/path/to/magen --no-export`.
  Effective gate: dedicated `eval-sandbox`, rootless, UID 1000, network none,
  zero host mounts. Test bundle SHA-256:
  `049f068e87248bc1002e9d58b77e1b6b94af4cff347893cf8b0d3ac0c9e65665`.
  Image ID: `fe83005fb105be014095e304ce578212522449ec2ad47649ef4833ef9a84abda`.
  No test/security payload ran on the host and no sample reports were exported.
- Receipt checks cover cumulative snapshot replacement, retries as separate calls,
  duplicates, multiple runtimes within one execution, unknown identity suppression,
  missing versus zero cached/reasoning values, partial completion, and late delivery.
  Private-socket ingestion is exercised without reading an ingestion credential.
  Assessment checks retain separate executions and prevent a passing execution
  from hiding another execution's failure; unknown definitions/provenance fail.
- Replayed the saved bounded RAG pilot receipts through
  fresh experiment-only collector state. No new inference, retrieval, or vault
  access occurred. All three recordings matched independent receipts and prior
  numeric totals: initial baseline 2,284 input / 70 output; RAG 3,354 / 107;
  corrected baseline 3,339 / 127. Exact reported `gemma4:latest`, provider `ollama`,
  harness `local-agent-pilot`, response evidence, and adapter `ollama-response-v1`
  now survive normalization. Cached/reasoning remain null, with false availability.
- The local replay comparison records original-file and eval-source hashes,
  full replay reports, and
  successful before/after checks of original receipts and the exhausted budget
  ledger. Older outputs were not rewritten. The pilot emitter now tags its
  reviewed adapter and saves counter availability for future authorized runs.
- No detector changes, deployment, fresh generation, semantic regrading, live
  interception, or billing verification. Browser rendering of these new labels
  was not visually checked. An exact reported `latest` alias is not proof of an
  immutable model version. Totals with false availability flags are observations,
  not complete measurements.

## Managed releases — 2026-11-04

- Published and activated `0.2.0-f21c85ea5558` through the manual publisher.
  Full app source SHA-256:
  `f21c85ea5558edbbf8c92a54fdf55d7e74efbe6ea09efeb1c4b91749f5c7fa4f`.
- The publication gate passed all 71 tests in the dedicated rootless Linux VM,
  with no workload network or host mounts. Its validation-input digest is
  `14b36aa8b0b3dfe42769af2ca7355e90aa8d4779c4fb5bb5bcd139f34f85fa48`.
  No samples were exported to host state and no live model calls were made.
- New release tests cover source integrity and symlink rejection, active-window
  update refusal, database schema compatibility, recording-version provenance,
  release switching, rollback, and recovery after a candidate fails startup.
  The activation integration test uses temporary state and temporary skill files
  inside the container, not the user's global skill or production database.
- The published collector's private control interface reported the matching
  version/build after the publisher exited, 63 retained recordings, no active
  window, and no pending update. The global Record commands reference that exact
  release directory and the existing acceptance-metrics state.
- `versions` verified the saved release and marked it active. `git diff --check`
  passed. The source is uncommitted and the manifest explicitly records dirty
  source beside the full source hash and baseline Git revision.
- Visual checking of the updated header was blocked by browser security policy;
  no workaround was attempted. Earlier visual checks below describe earlier UI.
  First managed publication establishes history; there is no saved 0.1.0 release.

## Pre-publication recheck — 2026-10-28

- Started the existing stopped `eval-sandbox` VM without changing its isolation
  configuration. Effective preflight confirmed rootless operation and zero host mounts.
- All 64 tests passed in 1.056 seconds, including the MAGEN detector integration
  and effective container-boundary checks. No live model benchmark was performed.
- Tested source bundle SHA-256:
  `aa717a55161c4069a9bd0cca95a4f330ea6fe47385df7e178badff69fe0a36f6`.
- Reviewed the publishable source for common credential patterns and private keys;
  none were detected. No `.env` files were found. Ignore checks exclude local
  runtime state, reports, environment files, credentials, and generated caches.
  Pattern checks do not establish that every possible secret format is absent.

## Executed

- Python 3.14; 64 standard-library tests passed in the dedicated `eval-sandbox`
  Linux VM. Suite runtime was 1.119 seconds, not a collector-overhead estimate.
- Effective Podman engine rootless; seccomp enabled; VM configured with zero host
  mounts and guest mount inspection found no virtiofs/9p shares.
- Container UID/GID 1000:1000, no effective/bounding capabilities,
  no-new-privileges, network=none, read-only root filesystem, no host bind mounts,
  CPU=1, RAM=512 MiB, process limit=64, bounded scratch space and file limits.
- Inside-container probes confirmed UID, capabilities, no-new-privileges,
  loopback-only interfaces, no common host sockets/shares/credential variables,
  and denied writes outside scratch space.
- MAGEN's reviewed detector and types modules were copied into the container.
  Synthetic injection and credential proposals were blocked before fake endpoint
  submission. No MAGEN module or security-test payload executed on the host.
- Six scripted weather narratives produced seven metrics-only HTML reports,
  including separate failure/repair attempts. No Google or model API was called.
- Local authenticated panel opened successfully in the Codex in-app browser.
- User confirmed the inline sample rendered inside this conversation and its
  breakdown expanded without opening a tab. The shared summary now exports
  an offline fragment with native expandable details, without backend controls.
- Verified automatic CLI chat selection, refusal to finish another chat's
  recording, chat-scoped latest-report selection, identical printed/saved text,
  owner-only non-overwriting output, escaped markup, and missing/zero handling.
- Browser verified the named timeout-recovery recordings link to each other,
  the failed recording shows a failed timeout check, and single-agent controls
  are hidden. No UUIDs appeared in visible report text with diagnostics closed.
- Browser verified hierarchy nests two helpers under the main agent; comparison
  flattens them. Switching to tool time ranks the 50 ms helper first; switching
  to failed calls ranks the one failure first and changes the displayed metric.
- Repeated samples remain accessible in collapsed history. Existing exported
  samples were associated with allowlisted case names using their unique export
  identifier prefix, without removing any recordings. New fixtures save the case
  name directly; unknown legacy cases keep an honest generic label.
- Verified recording-level line snapshots replace previous snapshots instead of
  summing repeated edits, do not alter token totals, reject ambiguous scopes and
  invalid counters, and discard paths/diff text. Missing line data stays distinct
  from measured zero. No source-tree scanning was added.
- Browser verified six metric tiles: cached input is a count without percentage,
  cached output says Not reported, and the new multi-agent sample shows scripted
  +48 / −6 line changes. The report explicitly states no AI model ran.
- Synthetic model-attribution tests covered one agent using three models across
  OpenAI/Anthropic usage events, preservation of an exact versioned Claude ID,
  independent harness/provider fields, request snapshot replacement, duplicate
  delivery, rejection of overlapping execution/call totals and cross-agent call
  reuse, unknown identities, and ambiguous model switches without call boundaries.
- Legacy fixture normalization preserves synthetic cost and idempotent replay
  while removing sim-weather-v1 from the reported model field. Browser inspection
  confirmed all three sample agents have model=null and fixture_profile=weather-v1;
  the Models used section explicitly states no AI model ran.
- Record-command tests verify current-chat identity, status isolation, idempotent
  start/stop, refusal to alter another chat's recording, missing identity, safe
  inline export, and real Unix-socket operation inside the container.
- Installed the reviewed personal Record skill at ~/.codex/skills/record after
  filesystem approval. The installed CLI's public skills/list API discovered it
  enabled as a user skill from this checkout and /private/tmp, including its UI
  metadata, without extra discovery roots. No chat/model inference was launched.
  Native composer selection was not automated. Skill control turns use the agent
  and are not proven to be excluded from measurements.
- The skill-creator quick_validate script could not run because PyYAML is absent
  from both available Python runtimes. No dependency was added; Codex's own parser
  successfully validated/discovered the staged and installed skill instead.
- Restarted the collector with record controls, then ran record status using the
  invoking runtime chat identity. It reported no recording and unavailable live
  capture. Implementation did not arm a window or alter Codex telemetry settings.

## Reproducibility

Podman client: 6.1.4. Dedicated VM: Apple virtualization, 2 vCPUs, 2 GiB RAM.

Pinned image:
`docker.io/library/python@sha256:29434a59c93070e470f84663e4289026e04644ea44b5220ef7e07d653318ca1f`

Resolved image ID:
`fe83005fb105be014095e304ce578212522449ec2ad47649ef4833ef9a84abda`

Tested source bundle SHA-256:
`13e3563663074d0e1e94a96fb0c131f1ffc4dfa13b1ca8e8e42b858a99d21638`

The launcher emits fresh source/image identity and rechecks effective isolation
on every run. This evidence is specific to the local tested configuration.

## Not established

- Live desktop telemetry, authoritative subagent completeness, or a persistent
  native widget extension. The local browser panel itself is usable.
- Live isolated Codex authentication or full submission interception. Existing
  host credentials have not been copied to test workloads.
- Real-agent weather-app generation, UI correctness of such a generated app,
  or Google API connectivity.
- Production pricing, actual billed USD, local process-resource sampling, or a
  quantified observer-overhead budget.
- General MAGEN detection effectiveness, semantic detectors, held-out attack
  resistance, arbitrary hostile repository safety, or immunity to runtime flaws.

The default application and test environment make no paid model calls. No user
Codex configuration was edited, no rootful helper installed, and the unrelated
`rea-research` machine was not used.
