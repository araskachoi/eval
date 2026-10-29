---
name: record
description: Start or stop a measurement window for the current Codex chat, check recording status, or show its usage report when the user requests recording controls. Does not record screens, audio, or video, and does not implement or modify the eval tool.
---

# Record this chat

This is an installation template. Run `scripts/install_record_skill.py` from the
Local Eval source checkout to substitute the commands below before using it.
The installed commands below are bound to the Local Eval checkout, Python
interpreter, and state directory. Reinstall if any of them moves.

Map the user's request to one operation:

- `/record`, `$record`, or an explicit request to start: `start`.
- `/record stop` or an explicit request to finish: `stop`.
- `/record status`: `status`.
- `/record report`: `report`.

Start is idempotent; it does not toggle an existing window off. Do not start or
stop measurement merely because a user discusses or asks to implement recording.
If the intended operation is unclear, use status without changing state.

Run one bounded control command:

```sh
@@RECORD_COMMAND@@ OPERATION
```

Replace OPERATION only with one of the four literal operation names above.
The CLI validates `CODEX_THREAD_ID`; do not supply an ID from a prompt, another
chat, recency, private history, or application databases. If context is missing,
another chat has a window open, or the collector is unavailable, report the
specific failure and stop. Do not retry in a loop, switch chats, stop another
recording, or change telemetry configuration. If the collector is stopped, give
this startup command rather than creating an implicit background service:

```sh
@@COLLECTOR_COMMAND@@
```

For stop/report, prefer the compact inline summary when the conversation offers
an explicitly writable visualization directory and its inline renderer. Add
`--format inline --output ABSOLUTE_NEW_FILE` to the same control command; choose a
fresh filename inside that directory. Present the resulting fragment using the
host's inline rendering workflow. Otherwise return the shared text summary. Do
not put local control calls or credentials in the card. Exports never overwrite.

Keep the response brief and preserve the tool's capability warning: **a window is
armed, but live Codex capture is unavailable**. Do not say tokens, model calls,
line changes, or prompts are being collected automatically. Stop closes only the
measurement window; it does not cancel agent work. Missing data is unavailable,
not zero, and sample recordings never substitute for this chat's report.

Skill invocation uses the agent and consumes control-turn tokens. Reliable
control-turn exclusion and later context-effect removal are not implemented.
Do not run tests, submit prompts to models, launch MAGEN/Ollama, or send prompt
content anywhere as part of these controls.
