# Local verification — 2026-10-28

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
