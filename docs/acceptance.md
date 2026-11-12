# Acceptance walkthroughs

The isolated suite uses six scripted recordings to check reporting behavior.
For real model submissions and the ledger task, see [model regression](../regression/README.md).
The walkthroughs make no inference calls and use synthetic counters and checks.

| Scenario | Finish report acceptance |
| --- | --- |
| Desktop-shaped observation | Ungraded with unknown coverage |
| Multiple prompts | Separate executions with combined observed consumption |
| Subagents | Three attributable executions, own usage counted once, a failed tool call visible |
| Failure then repair | Two preserved ledger sample recordings under one task, with a failed check followed by a passing check |
| MAGEN block | Blocked proposal with a security decision distinct from correctness |
| Finish during work | Partial activity with missing final usage visible |

The five report sections are consumption, contributors, operational failures,
check outcomes, and observations worth investigation. Every cost or count
remains traceable to a recording and source. Unrecognized counters, inclusive
accounting, conflicting IDs, and out-of-window events are rejected.
Historical weather recordings remain readable.
