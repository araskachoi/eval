# Repeated Recovery C study

This study adds 50 fresh trials per condition for each of the five previously
tested models. The budget is 1,250 trials in total, with four model calls at
most per trial. The earlier pilot observations remain separate.

The five conditions, prompt, fixture, harness and settings match the original
Recovery C sweep. Installed model digests and the Ollama version must match
that sweep. Conditions are shuffled within each five-trial block using the
existing design seed 1138. Each trial has a fresh conversation and MCP process.
The model order remains fixed to avoid repeated model loading.

Report verified completions over valid trials with 95% Wilson intervals for
each model and condition. Report B minus A, C minus A, and C minus B in
percentage points. For effect uncertainty, resample complete five-condition
blocks within each model using 10,000 bootstrap draws and seed 1138, and use
the 2.5th and 97.5th percentiles. These are exploratory intervals without
multiple-comparison adjustment. Report invalid trials separately and review
permission responses using the existing rubric.

This study describes repeatability in the local fixture workflow. The original
80-trial reliability recommendation rule remains a separate study design.
Runtime includes model loading and is sensitive to machine load and cache.
Token counts measure work performed across model calls.

Run the study with:

```sh
python3.14 -B -m codex_eval regression mcp sweep --benchmark elevenlabs-mcp-v2 \
  --trials 50 --output regression/results/elevenlabs/recovery-c-50
```
