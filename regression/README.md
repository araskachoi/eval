# Model regression

Regression is an explicit CLI workflow from the source checkout or a managed
release. It uses the dedicated `eval-sandbox` VM for grading and works with
model submissions collected by an external harness. Comparisons read saved JSON
files locally. You manage benchmark results manually in `regression/results/`
or another directory.

## Grade a trial

1. Get the exact initial prompt and turn budget. Choose `independent` for the
   task prompt alone or `guided` for the task plus a fixed implementation outline.
   Both use the same ledger checks. Match the protocol, harness, and settings
   between baseline and candidate. Send text and capture the response as data.
   Give the model no shell or file tools.

   ```sh
   python3 -m codex_eval regression protocol --benchmark ledger-v2 --protocol guided
   ```
2. In a directory for the turn, save the full submitted file as `ledger.py` and
   save the following metadata as `turn.json`. Measure elapsed time from prompt
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
