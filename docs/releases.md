# Publish and return to an earlier version

Publishing is manual. Saved source edits do not change the installed app until
you publish. The publisher validates the finished source, saves a private release
copy, starts that collector, and refreshes the global Record skill to use it.
There is no watcher, remote download, or launch-at-login service.

## First managed publish

Use Python 3.14+. Start the dedicated test VM in another terminal:

```sh
python3 scripts/isolated.py hold
```

Then, from the source checkout:

```sh
python3 scripts/publish_app.py publish \
  --magen /absolute/path/to/magen \
  --skills-dir "$HOME/.codex/skills"
```

The default recording state is `~/Library/Application Support/codex-eval`. To
retain another existing database, add `--state /absolute/path/to/that/state`.
If Record is already installed there, review it and add `--adopt-skill` once to
authorize replacing its two managed files. A legacy foreground collector must
be stopped once before the first managed publish; finish any recording first.
The publisher refuses to interrupt an active recording.

The dedicated rootless VM and pinned Python image must already be provisioned
as described in [security.md](security.md). Publishing never falls back to host
tests. Validation uses fake endpoints, no workload network, no host mounts, no
model credentials, and no paid calls. It does not add sample recordings to your
database. Missing isolation assets or failed checks prevent activation.

## After finishing a change

The first publish remembers the state, skills directory, interpreter, port, and
MAGEN source location. Subsequent updates use one command:

```sh
python3 scripts/publish_app.py publish
```

Finish edits before running it; changing source during validation refuses the
publish. The running app uses a release copy rather than the editable checkout.
Restart or reload Codex skills if needed. Reload the browser after an update and
obtain a fresh one-time code with the matching `panel` command in the installed
skill. Browser sessions are not retained across collector restarts. The VM may
be stopped after publication; the collector does not require it to view metrics.

Change `VERSION` in `codex_eval/version.py` for a semantic version bump. It is the
single source for the package version. Each release also has a source hash, for
example `0.2.0-0123456789ab`; builds with different code remain distinguishable
even when the semantic version is unchanged. The private release manifest records
the full source hash, Git revision and tracked dirty status, and validation
evidence. Uncommitted source is identified by the hash, not just the Git revision.
No credentials, runtime state, Git directory, or test fixtures are copied into
the app release. Release hashes detect changes; they are not publisher signatures.

The app header shows its running version. New recordings retain the version and
build that opened them; reports and exports preserve that provenance across later
updates. Existing recordings without provenance show version unavailable.

## List versions and roll back

```sh
python3 scripts/publish_app.py versions
python3 scripts/publish_app.py status
python3 scripts/publish_app.py rollback EXACT_RELEASE_ID_FROM_VERSIONS
python3 scripts/publish_app.py stop
```

`versions` identifies the active release and checks saved release integrity.
`status` shows the installation configuration and selected release. Rollback uses
an already validated local release and refreshes Record to match; it does not
need to run fixtures again. `stop` stops the managed collector without removing
releases, the skill, or data. Publish or roll back to start it again.

Releases live in `.runtime/app/releases`; the selected release is recorded in
`.runtime/app/install.json`. Keep this checkout and its release directories at
stable paths. The first managed release is **0.2.0**; the earlier 0.1.0 declaration
did not have a saved release to restore. Rollback history begins with publication.

Rollback changes code, **not recorded data**. The same database and its ordinary
30-day metrics retention remain in use. Incompatible schema versions, modified
release files, and independently edited global skill files block switching.
Compatible schema checks are not a database backup. This release adds an optional
provenance table without raising the existing schema version.

If startup fails during a managed update, the publisher leaves the prior release
selected, restores any skill files it changed, and attempts to restart that prior
collector. An OS crash or power loss during switching is not a transaction across
the process, skill files, and config file: inspect `status`, finish recovery, then
retry. Keep backups for recovery from disk failure. No automatic release pruning
is performed, so earlier skill commands remain usable while their releases exist.
