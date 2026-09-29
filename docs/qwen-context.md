# Qwen3-32B on a 32K server

The OpenHands adapter for `Qwen/Qwen3-32B` (also with an `openai/` prefix)
sets `max_input_tokens=27000`, `max_output_tokens=4096`, and explicitly enables
the SDK's `LLMSummarizingCondenser` with `max_tokens=20000`. The lower history
threshold leaves room for system instructions, tool schemas and token-count
differences. Summaries use the same learner and metered gateway. Model reasoning,
task instructions, tools, skills and verifier settings are unchanged.

This is context management, not exact server-side token counting. Unusually large
individual messages can still require the SDK's context-error recovery. Validate
against the live server before launching the full dataset. Summary calls add
token usage and may affect trajectories, so this policy is recorded in both the
resume manifest and evaluation result. Old Qwen3-32B runs cannot be resumed under
the new policy. To continue an older run with its original learner behavior, use
`--resume --legacy-context`. This selects the stock OpenHands runner and keeps
all other manifest compatibility checks. It does not change judge settings.
New runs use the context policy by default; the legacy option requires resume.

```bash
uv run stbench eval --config local-vllm.toml --domain health \
  --arms baseline --concurrency 2 --out runs/qwen3-32b-health-full \
  --resume --legacy-context
```

No Viking server restart is needed. Restart only the local evaluator. First run:

```bash
uv run stbench eval --config local-vllm.toml --domain qf \
  --tasks asian-option-levy-curran --arms baseline --concurrency 1 \
  --out runs/qf-context-pilot
```

Check the agent logs for condensation and successful completion without context
overflow. A verifier score of zero can still be a valid learner failure. Offline
tests check runner constructor wiring, routing, and resume separation; they do
not establish live model summarization quality or task success.
