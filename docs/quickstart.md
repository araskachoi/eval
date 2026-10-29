# Quick start

Local Eval is an experimental local metrics collector and report viewer. This
guide installs its agent-mediated `/record` skill and starts the local collector.
**Live Codex capture is unavailable.** Without a separately implemented, trusted
harness adapter, a recording shows elapsed time and unavailable usage metrics.
Installing the skill does not make token, cost, model, or line-change capture work.

## 1. Get the source and check prerequisites

Download or clone this project's source, then open a terminal in its root folder
(the directory containing `pyproject.toml`). Keep this checkout at a stable path.
The installer and integration files ship in the source checkout, not the Python
wheel. No package-registry release is assumed by these instructions.

You need Python **3.14 or newer**, a POSIX environment, and a local Codex harness
that loads skills and supplies `CODEX_THREAD_ID` to its shell commands. macOS is
the reviewed desktop environment; Linux and Windows desktop integration have not
been verified. Native Windows is not supported by this installer. The collector
uses Unix sockets, POSIX file permissions, and POSIX shell commands.

```sh
python3 --version
python3 -m codex_eval doctor
```

If `python3` is older, use your Python 3.14 executable in every command below.
Running from source needs no pip installation or third-party runtime dependencies.
`doctor` reports capabilities and an available Codex CLI version; it does not
verify skill discovery, collector connectivity, or live capture.

## 2. Install the Record skill

Preview the generated skill without writing anything:

```sh
python3 scripts/install_record_skill.py --dry-run
```

Install it:

```sh
python3 scripts/install_record_skill.py
```

The default destination is `~/.agents/skills/record`, the user skill location in
the [official skill documentation](https://learn.chatgpt.com/docs/build-skills).
The installer writes `SKILL.md` and `agents/openai.yaml`, embedding absolute paths
to this checkout, the Python interpreter used to run it, and the state directory.
It prints the exact command to start the matching collector. Paths with spaces
are shell-quoted. It does not download anything, start a service, install hooks,
modify global configuration, read chat history, or configure telemetry.

For a harness with a different discovery directory, choose its **parent skills
directory**, not the `record` directory itself:

```sh
python3 scripts/install_record_skill.py --skills-dir "$HOME/.codex/skills"
```

For a custom state directory, select it during installation:

```sh
python3 scripts/install_record_skill.py --state "$HOME/.local/share/local-eval"
```

Use one installation command with both options if needed. The installer refuses
to overwrite any existing `record` folder or symlink. For updates, inspect and
move that folder aside, then rerun the installer. Avoid duplicate Record skills
in different discovery roots. Do not copy the source template directly: its
command placeholders must be rendered by the installer.

## 3. Start the collector

Keep a foreground terminal open in the source root:

```sh
python3 -m codex_eval collector start
```

This uses `~/Library/Application Support/codex-eval`, also the installer's default
state directory. That default currently applies on every platform. If you selected
custom state, use the collector command printed by the installer instead. The
skill, collector, panel, and report commands must all use the same state.

The panel defaults to port 8765 on loopback. To select another port:

```sh
python3 -m codex_eval collector start --port 8766
```

Starting the collector requires no model credentials or API key. It does not make
model calls. If your harness sandbox cannot access the checkout or collector's
Unix socket, its normal filesystem/command permissions still apply.

## 4. Use it in your chat

Reload skills or restart Codex if Record does not appear. Type `/` and select
**Record**, or explicitly invoke `$record`. Enabled skills appear in the desktop
[slash menu](https://learn.chatgpt.com/docs/reference/slash-commands); exact UI
availability depends on the harness.

| In the intended Codex chat | Result |
| --- | --- |
| `/record` or `$record` | Open a measurement window; repeat start keeps that window open |
| `/record status` or `$record status` | Show this chat's recording state |
| `/record stop` or `$record stop` | Close the window and show a summary; it does not cancel work |
| `/record report` or `$record report` | Show this chat's latest recording summary |

Expected first run: start reports that a window is armed and live capture is
unavailable. Stop shows elapsed time, while usage without ingested events remains
**Unavailable**, not zero. Sample metrics never stand in for your chat's data.
The skill uses the agent, so its own control turns may consume model tokens.

Only one recording can be open per collector state. Another chat cannot start or
stop that recording. `record` requires a valid invoking `CODEX_THREAD_ID`; it has
no manual identity override and never guesses the most recent chat.

## 5. View the local panel or export a report

In another terminal in the source root:

```sh
python3 -m codex_eval panel
```

Open the loopback URL returned by the command (default
`http://127.0.0.1:8765`) and enter its one-time code. The code expires after
60 seconds; a successful login lasts one hour. Keep the collector running. The
panel requires an explicit chat UUID; it cannot infer the chat currently visible
in Codex. Use the chat skill when you want automatic current-chat identity.

In the invoking Codex environment, export a compact text summary or inline card:

```sh
python3 -m codex_eval record report --output summary.txt
python3 -m codex_eval record report --format inline --output summary.html
```

Use fresh output filenames; exports refuse to overwrite files. The inline export
is a snapshot fragment for a compatible conversation renderer. For a standalone
HTML report, use the recording UUID returned by deliberate CLI controls:

```sh
python3 -m codex_eval report RECORDING_UUID --output report.html
```

Add `--state /your/state/directory` **before** the command if using custom state.
An ordinary terminal can use `on --thread CHAT_UUID`, `off --thread CHAT_UUID`, and
`summary --thread CHAT_UUID` with a known, deliberately selected UUID. Do not set
a made-up `CODEX_THREAD_ID` to bypass the skill's identity checks.

## Troubleshooting and removal

| Symptom | What to check |
| --- | --- |
| `No module named codex_eval` | Run from the source root; reinstall the skill after moving the checkout or interpreter |
| Current chat identity unavailable | Invoke the skill from the intended local Codex chat; other harnesses need a verified identity adapter |
| Collector unavailable | Run the printed collector command and check that both commands use the same state |
| Another chat has an open recording | Stop it from that original chat first |
| Usage is unavailable | Expected without a trusted event adapter; installing the skill does not collect usage |
| Socket exists after a crash | Confirm the collector is stopped, then run `python3 -m codex_eval cleanup` with matching state; cleanup refuses a live socket |
| Address already in use | Check existing collectors or choose another `--port`; do not reuse a running state directory |

Stop the collector with Ctrl-C. Stopping or restarting it closes unfinished
windows with a gap; recording does not resume automatically. Remove only the
installed `record` folder printed by the installer to uninstall the skill. No
global configuration needs reverting. Review state before deleting it, and delete
exports separately if wanted. Metrics expire after 30 days; exports and OS
backups are independent copies.

For actual event integration, read the [normalized contract](interfaces.md).
`POST /ingest` is authenticated JSON, **not OTLP**; no ready-made live Codex or
Claude Code adapter is shipped. Other harnesses must provide trusted correlation
and supported own-execution usage events; a custom skills directory alone does
not supply those capabilities.

For development tests, follow the [mandatory isolation boundary](security.md).
The dedicated VM/Podman setup is separate from using the collector and skill,
and its local development assets are not shipped. Do not run the fixture suite
directly on your host. See the [README](../README.md) for current limitations and
the [verification record](verification.md) for the scope of prior checks.
