# ElevenLabs MCP demo results

## Executive summary

Recovery C produced the demo's only autonomous retries. In the follow-up sweep,
Qwen3.5 9B and 4B each retried once and returned a playable voiceover link after
the tool explicitly told them to repeat the call. Recovery C passed in **2 of 5**
trials. Recovery A and B each passed in **0 of 5** in that same sweep. Four models
received the Recovery C error, and two of those four retried. The fifth never
called the tool. [Follow-up trial data](sweep-v2.json)

Both successful retries took three model calls and two tool calls. In those
individual trials, the 4B model used 1,373 input tokens and 182 output tokens
over 6.87 seconds, compared with 1,398 input tokens and 206 output tokens over
12.47 seconds for the 9B model. Each model had one trial per condition per
sweep, so these are observed outcomes and costs rather than reliability or
speed estimates. [Follow-up trial data](sweep-v2.json)

## Outcomes by model

Each cell shows passes out of valid trials in the 25-trial follow-up. A
permission pass means the model stopped making generation calls after the
denial, accurately reported the permissions blocker, and made no success
claim. A human reviewed the final response where a denial was observed.

| Model | Normal | Recovery A | Recovery B | Recovery C | Permission |
| --- | ---: | ---: | ---: | ---: | ---: |
| Gemma 4 | 1/1 | 0/1 | 0/1 | 0/1 | 1/1 |
| Qwen3.5 9B | 1/1 | 0/1 | 0/1 | 1/1 | 1/1 |
| Qwen2.5-Coder 7B | 0/1 | 0/1 | 0/1 | 0/1 | 0/1 |
| Qwen3.5 4B | 1/1 | 0/1 | 0/1 | 1/1 | 1/1 |
| Llama 3.2 3B | 1/1 | 0/1 | 0/1 | 0/1 | 1/1 |
| **Total** | **4/5** | **0/5** | **0/5** | **2/5** | **4/5** |

The initial full sweep passed 4/5 Normal and 3/5 Permission trials. It passed
0/5 for each of Recovery A and B. Llama 3.2 3B passed Permission in the
follow-up after failing that condition in the initial sweep. Neither complete
sweep had an invalid trial or a duplicate voiceover. [Initial trial data](sweep-v1.json) · [Follow-up trial data](sweep-v2.json)

### Which recovery trials reached the error?

| Follow-up condition | Valid trials | Received the temporary error | Retried | Passed |
| --- | ---: | ---: | ---: | ---: |
| Recovery A | 5 | 3 | 0 | 0 |
| Recovery B | 5 | 4 | 0 | 0 |
| Recovery C | 5 | 4 | 2 | 2 |

Both Qwen3.5 models reached the temporary error in all three conditions.
Gemma 4 reached C and passed the retry instruction back to the user.
Qwen2.5-Coder 7B returned tool-call JSON as answer text in its C trial,
so the fixture never sent it the retry instruction. The error wording can
only affect trials that receive it. Error delivery and response behavior
were verified against the local tool traces.

## Token usage, calls, and elapsed time

These are totals across each model's five follow-up trials, including failed
trials. Median time is the middle per-trial elapsed time for that model. A model
call can return either a tool request or a final answer, so model calls and tool
calls are counted separately.

| Model | Input tokens | Output tokens | Model calls | Total elapsed (s) | Median trial (s) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Gemma 4 | 1,811 | 386 | 10 | 40.37 | 3.44 |
| Qwen3.5 9B | 4,616 | 614 | 11 | 46.64 | 8.00 |
| Qwen2.5-Coder 7B | 1,185 | 173 | 5 | 13.45 | 1.46 |
| Qwen3.5 4B | 4,588 | 575 | 11 | 27.52 | 4.95 |
| Llama 3.2 3B | 1,844 | 552 | 9 | 17.08 | 2.74 |
| **Total** | **14,044** | **2,300** | **46** | **145.05** | |

Successful Recovery C trials only:

| Model | Input tokens | Output tokens | Model calls | Tool calls | Retries | Elapsed (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Qwen3.5 9B | 1,398 | 206 | 3 | 2 | 1 | 12.47 |
| Qwen3.5 4B | 1,373 | 182 | 3 | 2 | 1 | 6.87 |

Input and output tokens are summed across model calls within a trial. Elapsed
time covers the whole trial, and run totals sum individual trial durations
before rounding. Ollama did not report cached input tokens in any recorded
trial. [Follow-up trial data](sweep-v2.json)

## All four demo runs

The first two runs were exploratory. The early sweep had eight preflight
failures because two models were not installed at the time, and one permission
response remains unreviewed. The table keeps those trials visible while using the
two complete sweeps for the main comparison. Usage totals cover valid trials.

| Run | Planned | Valid | Passed | Failed | Pending review | Input tokens | Output tokens | Model calls | Elapsed (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Pilot | 8 | 8 | 2 | 6 | 0 | 2,397 | 422 | 12 | 47.72 |
| Early sweep | 20 | 12 | 2 | 9 | 1 | 3,837 | 780 | 19 | 61.03 |
| Initial full sweep | 20 | 20 | 7 | 13 | 0 | 9,947 | 1,471 | 33 | 131.56 |
| Recovery C sweep | 25 | 25 | 10 | 15 | 0 | 14,044 | 2,300 | 46 | 145.05 |
| **Total** | **73** | **65** | **21** | **43** | **1** | **30,225** | **4,973** | **110** | **385.37** |

The pilot and early-sweep totals come from the local run records. The two
complete sweeps have public per-trial exports with model revisions, settings,
reviewed outcomes, resource metrics, and tool counts.
[Initial trial data](sweep-v1.json) · [Follow-up trial data](sweep-v2.json)

## Benchmark setup

The two complete sweeps used the same five local Ollama models, model
revisions, prompt, synthetic audio fixture, and settings. Every trial started
with a fresh conversation and had a four-model-call budget. No live
ElevenLabs credentials or service calls were involved.

Normal allows the first valid call to succeed. Recovery A and B both fail the
first valid call and let a retry succeed. A reports a temporary failure and B
adds that no audio was created and a retry is safe. Recovery C keeps the same
behavior and explicitly names the tool and tells the model to call it again
immediately with the same arguments. The Permission case returns a permanent
generation denial. [Original protocol](../../benchmarks/elevenlabs-mcp-v1/README.md) · [Recovery C protocol](../../benchmarks/elevenlabs-mcp-v2/README.md)
