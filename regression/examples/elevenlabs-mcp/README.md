# How local language models recover from a failed voiceover tool call

## Abstract

The broader objective was to find the smallest model able to reason through
and complete designated tasks on the available computer. This study tested
that objective with a voiceover workflow and examined whether clearer tool
error messages help a language model
retry a failed voiceover request without user intervention. Five models ran
through Ollama on the same computer, using a local server that simulated
ElevenLabs. Each model completed 50 trials in each of five conditions, giving
**1,250 trials in total**. An explicit instruction to repeat the tool call
produced 49/50 successful recoveries for Qwen3.5 9B and 47/50 for Qwen3.5 4B.
A message saying a retry was safe produced 1/50 and 3/50, respectively.
The other three models completed no recoveries. These findings describe the
tested models, settings, and simulated workflow. [Trial data](repeated-50.json)

## Method

### Objective and the role of model regression testing

The goal is to identify the smallest model that can complete a defined task
with acceptable reliability and resource usage. Here, reasoning is assessed
through observable decisions, such as retrying a temporary failure and
stopping after a permission denial.

A model regression tool makes this comparison repeatable. It gives each model
the same task and test conditions, checks its actions and final result, and
records success rates, token usage, calls, and time. Replacing a model with a
smaller one can then reveal which behaviors improve or regress, meaning
performance becomes worse. Saved model versions and trial records make those
comparisons inspectable and support retesting after a model or prompt changes.

For this study, Qwen3.5 4B was the smallest tested model to complete any recovery
trials. Under Recovery C it passed 47/50, alongside 49/50 Normal and 50/50
Permission trials. This identifies a candidate for this workflow. Establishing
the minimum suitable model still requires meeting the protocol's reliability
criteria and testing smaller candidates under the same conditions.
[Trial data](repeated-50.json)

### Task and research question

Every trial gave the model exactly this user request:

> Using the connected ElevenLabs MCP, generate one voiceover that says
> ‘Welcome back to the show’ in a warm, friendly voice. Share the link where
> I can listen to it. If you can’t complete it, tell me what blocked you.

The primary question was whether the error message changed the model's ability
to complete this task after a temporary failure. A second question was whether
the model stopped appropriately when generation was permanently denied.

### Models and testing environment

The five models were Gemma 4 (`gemma4:latest`), Qwen3.5 9B,
Qwen2.5-Coder 7B, Qwen3.5 4B, and Llama 3.2 3B. They ran locally on an
Apple M1 Pro MacBook Pro with 16 GB of memory.

The **harness** is the program that sends the request to the model, carries out
its tool calls, returns the tool's responses, and records what happened.
This study used `local-ollama-mcp-v1` with Ollama 0.30.10. MCP, or Model Context
Protocol, is the interface used to communicate with the tool server.

The server simulated the generation workflow using a bundled, playable
1.39-second recording of the requested phrase. Each successful generation
created a distinct listening link to a copy of that recording. The model made
real MCP calls to this local server. The experiment required no ElevenLabs
account, API key, credits, or connection to the hosted service. Voice style
and actual speech synthesis quality were outside the scoring.

### Five test conditions

| Condition | What the server does | What a pass requires |
| --- | --- | --- |
| **Normal** | Creates audio on the first valid generation call. | Complete the requested voiceover and return its listening link. |
| **Recovery A** | The first valid call creates nothing and returns “Generation temporarily unavailable.” | Retry independently, then complete the task. |
| **Recovery B** | Same failure as A, with “No audio was created. You can safely retry this request once.” added. | Meet the same requirements as A. |
| **Recovery C** | Same failure as A, with “No audio was created. Call generate_voiceover one more time now with the same arguments.” added. | Meet the same requirements as A. |
| **Permission** | Every valid call returns a permanent generation permission error and creates nothing. | Explain the permission blocker, make no further generation attempt, and make no claim that audio was created. |

For A, B, and C, only the error wording changed. The tool schema, error flag,
validation, success format, and retry behavior were identical. A valid second
call succeeded. Further valid calls could create additional audio, allowing
the grader to detect duplicates.

### Procedure and fixed settings

Each model ran **250 trials**, comprising **50 trials per condition**.
Every trial started with a fresh conversation and a fresh MCP server.
The harness supplied no additional user messages or repair hints. The model
could see the tool description and responses, but could not see the condition
name or grading rules.

Conditions were shuffled in 50 groups of five trials for each model, with each
group containing one trial per condition. The shuffle used seed 1138, a saved
number that makes the ordering reproducible. Models ran in a fixed order.

All models used temperature 0.2, a setting controlling output randomness,
a 4,096-token context limit, and a 512-token output limit per model call.
Thinking mode was disabled. A trial allowed at most four model calls.
A model call could request a tool action or return a final answer.
The inference connection timed out after 150 seconds per call. Model versions,
Ollama version, prompt, audio fixture, and settings matched the earlier sweep
and were recorded before the repeated run. [Recorded settings and model versions](repeated-50.json)

### Scoring and evidence

For Normal and recovery conditions, passing required the requested script in
the tool trace, exactly one playable result, and the correct result link in
the final answer. The grader checked recorded calls, created files, and live
audio downloads. Permission explanations received manual review using the
documented rubric. The reviewer checked that the answer identified the actual
permission blocker and made no false success claim.

Provider outages or broken instrumentation counted as invalid runs.
A valid trial that stopped early or exhausted its budget without completing
the task counted as a failure. There were **zero invalid trials** in this run.
[Scoring rubric](../../benchmarks/elevenlabs-mcp-v1/README.md)

## Results

### Outcomes by model

Each cell shows **passes out of 50 trials**, followed by the percentage.
The five conditions together account for 250 trials per model and 1,250 overall.
Earlier exploratory trials are excluded from these tables.

| Model | Normal | Recovery A | Recovery B | Recovery C | Permission |
| --- | ---: | ---: | ---: | ---: | ---: |
| Gemma 4 | 49/50 (98%) | 0/50 (0%) | 0/50 (0%) | 0/50 (0%) | 50/50 (100%) |
| Qwen3.5 9B | 50/50 (100%) | 0/50 (0%) | 1/50 (2%) | 49/50 (98%) | 44/50 (88%) |
| Qwen2.5-Coder 7B | 0/50 (0%) | 0/50 (0%) | 0/50 (0%) | 0/50 (0%) | 0/50 (0%) |
| Qwen3.5 4B | 49/50 (98%) | 0/50 (0%) | 3/50 (6%) | 47/50 (94%) | 50/50 (100%) |
| Llama 3.2 3B | 19/50 (38%) | 0/50 (0%) | 0/50 (0%) | 0/50 (0%) | 32/50 (64%) |

Compared with B, C increased observed completion by **96 percentage points**
for Qwen3.5 9B and **88 percentage points** for Qwen3.5 4B.
For example, 98% minus 2% gives a 96-percentage-point difference.
No trial created duplicate audio. [Trial data](repeated-50.json)

### Average resource usage per model

Each value is the arithmetic mean across that model's **250 trials**,
including successes and failures, with 50 trials from each condition.
Tokens are pieces of text processed or generated by the model.
Input tokens are counted across every model call, including repeated
conversation history. Elapsed time covers the whole trial, including model
loading, tool execution, and verification.

| Model | Average input tokens | Average output tokens | Average model calls | Average elapsed time (s) |
| --- | ---: | ---: | ---: | ---: |
| Gemma 4 | 362.32 | 74.47 | 2.00 | 3.42 |
| Qwen3.5 9B | 924.94 | 126.00 | 2.20 | 7.51 |
| Qwen2.5-Coder 7B | 237.00 | 31.97 | 1.00 | 1.50 |
| Qwen3.5 4B | 916.98 | 115.86 | 2.20 | 4.49 |
| Llama 3.2 3B | 334.20 | 103.42 | 1.62 | 2.43 |

All trials recorded these metrics. Cached input tokens, meaning tokens reused
from earlier processing, were unavailable from Ollama.

Qwen3.5 4B averaged 4.49 seconds per trial compared with 7.51 for 9B under
the same mix of conditions. Early stopping also reduces these averages.
Qwen2.5-Coder averaged one model call because it ended every trial before
making a tool call. Its low usage therefore accompanies a 0% pass rate.
These averages describe the cost of attempted tasks, including failures.
[Per-trial metrics](repeated-50.json)

## Analysis and discussion

### Explicit retry instructions helped the two Qwen3.5 models

Both Qwen3.5 models received the injected error in all 50 trials of each
recovery condition. Their successful B and C trials each made one retry and
created one result. Their failed C trials made no retry. The 9B model's one
C failure said it would retry immediately, but ended with a final answer
without executing that action (`trial-0309`). The 4B model's three C failures
asked the user to try again (`trial-0764`, `trial-0829`, and `trial-0891`).

The observed difference is consistent with the explicit instruction helping
these models choose another tool call. The study does not reveal their
internal reasoning. [Trial data and tool counts](repeated-50.json)

### Gemma handed the retry instruction back to the user

Gemma reached the temporary error in all 150 recovery trials and never retried.
In C, every trial ended after two model calls, leaving room within the
four-call budget. In `trial-0010`, its answer began:

> I encountered a temporary issue while trying to generate the voiceover.
> Please try calling the `generate_voiceover` tool again with the exact same arguments

The trace recorded one generation attempt and zero creations. The failure was
stopping after an instruction to the user. The recorded behavior does not
establish why Gemma chose that response. [Trial record](repeated-50.json)

### Llama failed both before and after receiving the error

Llama made no generation call in **18/50 C trials**. In the other **32/50**,
it received the error but made no retry. Some responses described another
attempt or printed tool-call JSON as ordinary text.

In `trial-1011`, the final answer said “Here's another attempt at generating
the voiceover” and printed a JSON request. The trace still recorded only the
original failed call. In Normal, Llama created audio in 27/50 trials, but
only 19 passed all checks for the script and final link. The failed checks
can overlap, so their counts should not be added together.
[Trial records and tool counts](repeated-50.json)

### Qwen2.5-Coder never reached the recovery step

This model made zero generation calls across all 250 trials. Its responses
presented tool-call requests as text, and the harness did not execute that text.
Consequently, it never received any injected recovery error. Its results
measure an earlier tool-use failure, so they provide no direct evidence about
its response to A, B, or C. [Trial records and tool counts](repeated-50.json)

### Recovery and permission handling were different strengths

Qwen3.5 9B had the highest C recovery rate but passed 44/50 Permission trials.
One trial repeated generation after the denial (`trial-0440`). Five other
answers failed the explanation rubric by attributing the problem to a
temporary issue, configuration issue, or unsupported licensing explanation.

Qwen3.5 4B and Gemma passed all 50 Permission trials. Llama received a denial
in 33 trials and passed 32. One answer claimed to offer a link to a generated
voiceover despite zero creations (`trial-1172`). Its other 17 trials never
called the tool. These outcomes show why both recovery and appropriate
stopping matter when evaluating the workflow. [Reviewed trial outcomes](repeated-50.json)

## Limitations

The sample contains 50 observations per model and condition. Observed rates
can change in another run. The fixed model order, shared computer, and model
caching limit timing comparisons. The models also use different tokenizers,
so token counts are not a direct measure of equal computational work.

The task uses one script, one tool schema, one harness, and a simulated
service with an immediately successful retry. Real service delays, login
problems, and audio quality require other tests. C was designed after
observing the initial A/B failures, and this larger run followed that
exploration. Permission explanations involve reviewer judgment.

The traces establish calls, responses, creations, and final answers.
They cannot identify whether a failure originates in model training,
tool-call formatting, or sensitivity to the harness instructions.

## Data and reproducibility

- [All 1,250 trials](repeated-50.json) contain reviewed outcomes, model revisions, fixed settings, token counts, model calls, timing, and tool counts.
- [Repeated-study protocol and command](../../benchmarks/elevenlabs-mcp-v2/repeated-run.md) records the design before the larger run.
- [Harness implementation](../../../codex_eval/elevenlabs_benchmark.py) and [MCP fixture](../../../codex_eval/elevenlabs_fixture.py) define execution and grading.
- [Original condition definitions and rubric](../../benchmarks/elevenlabs-mcp-v1/README.md) and [Recovery C definition](../../benchmarks/elevenlabs-mcp-v2/README.md) provide the full protocol.
- [Additional statistical calculations](repeated-50-analysis.json) preserve the interval calculations separately from this overview.

The public exports omit local playback addresses and raw conversation text.
Trial IDs above identify records in the export. Brief response excerpts in
this report were checked against the locally retained responses and MCP traces.

### Earlier exploratory runs

Four earlier runs contained 73 planned trials, of which 65 were valid.
One early sweep had eight invalid trials because two models were not yet
installed. These trials helped develop the benchmark and are excluded from
the 1,250-trial analysis. The [20-trial sweep](sweep-v1.json) and
[25-trial C pilot](sweep-v2.json) remain available as historical data.
