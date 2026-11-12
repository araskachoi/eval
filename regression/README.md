# Model regression

Regression is an explicit CLI workflow from the source checkout or a managed
release. It uses the dedicated `eval-sandbox` VM for grading and works with
model submissions collected by an external harness. Comparisons read saved JSON
files locally. You manage benchmark results manually in `regression/results/`
or another directory. See [fresh setup and release checks](../docs/regression-setup.md).

## Grade a trial

1. Get the exact initial prompt and turn budget. Choose `independent` for the
   task prompt alone or `guided` for the task plus a fixed implementation outline.
   Both use the same ledger checks. Match the protocol, harness, and settings
   between baseline and candidate. Send text and capture the response as data.
   Give the model no shell or file tools.

   ```sh
   python3 -m codex_eval regression protocol --benchmark ledger-v2 --protocol guided
   ```
   For the filesystem task, use `--benchmark filesystem-v1 --protocol independent`.
   Its prompt contains only a dummy inventory and asks for a standalone
   `organize.py`.

2. In a directory for the turn, save the full submitted file as `ledger.py` for
   ledger or `organize.py` for filesystem. Save the following metadata as
   `turn.json`, using the chosen benchmark and protocol. Measure elapsed time from prompt
   submission to submission handoff. Use milliseconds and omit any metric the
   harness could not measure.

   ```json
   {
     "schema": 1,
     "benchmark": "ledger-v2",
     "protocol": "guided",
     "trial_id": "trial-01",
     "turn": 1,
     "model": {
       "provider": "example",
       "id": "example-model",
       "revision": null,
       "evidence": "provider response"
     },
     "harness": "manual-v1",
     "settings": {"temperature": 0},
     "metrics": {"input_tokens": 250, "output_tokens": 480, "elapsed_ms": 1800}
   }
   ```

   Include the resolved revision when available. Keep harness settings free of
   credentials and other secrets. Optional `cached_input_tokens` is a subset of
   input tokens. Use matching trial IDs on both sides of the comparison.
3. Start the dedicated VM using the [isolation instructions](../docs/security.md)
   and make sure its reviewed image is staged. From the checkout, create a
   directory for each model's results and grade each submission.

   ```sh
   mkdir -p regression/results/baseline regression/results/candidate
   python3 -m codex_eval regression grade --run /path/to/turn.json \
     --output regression/results/baseline/trial-01-turn-1.json
   ```

4. After a failed check, send the returned `repair_prompt` verbatim to the same
   model session. For `ledger-v2`, it includes the failed check names and any
   fixed hints defined by the selected protocol. Save a new submission and
   manifest with the same trial ID and the next turn number. Stop on the first
   full pass, after the protocol's turn budget,
   or on an infrastructure error. On an infrastructure error, use a new output
   filename when retrying and include only the chosen result in the comparison
   directory. Each grading command saves a result and prints feedback. An
   infrastructure or CLI error exits with status 2.

## Compare saved results

```sh
python3 -m codex_eval regression compare regression/results/baseline regression/results/candidate
```

For an A/A check, give the local filesystem runner a directory of saved grades
for one model and a new results directory. It repeats the same trial IDs and
inference settings, verifies the benchmark, model revision, Ollama version,
and sandbox against the saved grades, and writes new grades, receipts, and a
comparison. Start the dedicated VM before running it.

```sh
python3 -B scripts/repeat_filesystem.py \
  --baseline regression/results/2026-11-11-filesystem-v1-ollama/gemma4 \
  --output regression/results/filesystem-gemma-repeat
```

The runner sends only the benchmark prompt and its turn history to loopback
Ollama. It saves submitted scripts temporarily as data for the isolated grader
and retains the numeric receipts and grade results.

Each directory should contain one result JSON per trial and turn for one model.
The report pairs matching trial IDs and shows unmatched trials separately.
Pass rates give the number passed, the number with a known grade, and the total
number of paired trials. Inspect incomplete and infrastructure-error trials
alongside the rates. Token and runtime deltas are candidate minus baseline,
summed through the first pass. A delta is available when both models passed
and both reported the metric for every turn. Grading time is recorded separately
and does not contribute to model runtime.

A few repeated trials can help calibrate the task. Keep the baseline artifact
once the cases exercise meaningful differences, and interpret later results
in the context of normal variation.

`ledger-v2` makes both CLI inputs explicit file paths and awards rejection
checks only after a successful valid apply. Saved `ledger-v1` results retain
their original identity and three-turn budget. For a legacy `ledger-v1` repair,
append the failed check names to its generic repair prompt.

## Add a benchmark

Create a versioned directory under `benchmarks/`, using `ledger-v1` as the
layout example. Its definition specifies the grader, required checks, repair
prompt, and turn budget. The included `ledger-cli-v1` grader handles additional
ledger cases through fixture data. Give changed prompts, fixtures, or grading
rules a new version and collect a new baseline. A new kind of task can supply
another reviewed grader that produces the same check outcomes and turn metrics.

The grader runs submitted Python in a fresh rootless, network-disabled
container for each check. It stages a bounded copy of the submission and
fixtures, observes the CLI and resulting files, and compares those observations
against expected outcomes outside the container. Future tool-enabled agent runs
need their own verified fixture-only workspace plus grading of intended changes
and protected files.

The filesystem grader accepts no host directory input. It builds each tree from
literal dummy strings in the reviewed benchmark definition. It restricts file
writes and removals to the disposable fixture with Landlock and blocks child
process creation. The grader checks the exact tree, file contents and modes
after each of two runs. It discards submission output and fails closed when the
required sandbox controls are unavailable.

## Run a baseline or candidate

Save a run spec with the benchmark, protocol, harness, model and trial count.
For Ollama, supply the installed local model ID and optionally its exact digest
as `revision`.

```json
{"benchmark":"filesystem-v1","protocol":"independent","harness":"ollama","model":"gemma4:latest","trials":3}
```

```sh
python3 -m codex_eval regression run --spec run.json --output regression/results/new-baseline
```

Use a new output directory for a fresh run. Add `--baseline PATH/grades` for a
matched repeat or candidate. Comparisons require the same harness, settings,
benchmark, grader profile and trial IDs. To recover an interrupted run, use the
same arguments and add `--resume`. Completed trials are reused. An interrupted
trial starts over and its earlier grade files remain in `attempts/`. Raw model
text and submitted code are temporary. Result directories are user-managed.

For Codex CLI, set `harness` to `codex` and provide an explicit available model ID.
The optional `reasoning_effort` defaults to `medium`. Supply `CODEX_API_KEY` only
to the trusted launcher. Codex uses an ephemeral session and temporary home,
with shell execution, web search, apps, plugins, hooks and subagents disabled.
The grader still runs in the existing network-disabled VM/container. The
runner records requested Codex model identity, CLI version and reported usage.
Hosted revision and served-model identity are unresolved in this CLI mode.

## Qualify the task checks

Run the reviewed reference and deliberate failure probes inside the grader.

```sh
python3 -m codex_eval regression qualify --benchmark ledger-v2 --protocol independent
python3 -m codex_eval regression qualify --benchmark filesystem-v1 --protocol independent
```

Qualification checks for false credit on blanket rejection, boolean validation,
collision overwrites, and protected-file deletion. Each probe must produce the
expected result for every check. The command records submission and benchmark
digests and the effective grader profile. Use separate local model pilots to
observe completion and repair behavior under a fixed protocol. The synthetic
probes establish grader behavior and the model pilots characterize the tested
models under their saved settings.
