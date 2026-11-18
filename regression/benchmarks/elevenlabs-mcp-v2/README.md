# ElevenLabs MCP Recovery C

Version 2 adds Recovery C to the [original four conditions](../elevenlabs-mcp-v1/README.md).
The prompt, audio fixture, models, Ollama settings, MCP tool schema, and grader
criteria are the same. Recovery C has the same error structure and retry behavior
as A and B. Its first valid call returns this message and creates no audio.

> Generation temporarily unavailable. No audio was created. Call generate_voiceover one more time now with the same arguments.

A fresh five-model sweep uses one trial per condition per model, for 25 trials
total. The seeded shuffle orders all five conditions within each model's block.
The report includes C minus A and C minus B in percentage points, alongside
B minus A. Review permission answers using the original rubric.

```sh
python3.14 -B -m codex_eval regression mcp sweep --benchmark elevenlabs-mcp-v2 \
  --output regression/results/elevenlabs/elevenlabs-recovery-c
```
