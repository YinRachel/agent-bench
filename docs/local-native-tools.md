# Local evaluation with the original OpenHands tool protocol

DeepSeek now uses Harbor's stock `openhands-sdk` adapter. There is no
DeepSeek runner patch, prompt-based tool conversion, or custom HealthBench
prompt. The original file-output contract and rubric scoring remain in place.
Local endpoint routing and optional upstream authentication are retained.
Recorded trial exceptions invalidate attempts even when a verifier returns a
reward; this deliberate departure from upstream avoids reporting failed
learner invocations as valid scores.

The SSH tunnel forwards HTTP only. A healthy endpoint and successful plain
text generation do not establish native tool support. Before Docker evaluation:

```bash
uv run python scripts/check_native_tools.py --config local-vllm.toml
```

The check sends one small native `tool_choice=auto` request, checks its
structured function name and arguments, and executes no tools. It consumes
model tokens but does not write benchmark scores. It does not prove multi-turn
tool reliability. The learner server must supply a compatible tool parser and
chat template, and the checkpoint must actually generate that protocol.
There is no automatic prompt-based fallback.

On 2026-09-28 the forwarded DeepSeek endpoint returned HTTP 400:
`"auto" tool choice requires --enable-auto-tool-choice and --tool-call-parser to be set`.
Do not start a full run on that configuration. A parser for another DeepSeek
checkpoint is not automatically compatible with R1-Distill-Qwen-32B.

After the check passes, validate a new one-task run:

```bash
uv run stbench eval --config local-vllm.toml --domain health \
  --arms baseline --limit 1 --concurrency 1 \
  --out runs/local-vllm-health-native-smoke
```

Inspect native tool calls, tool execution, the saved response, and verdicts.
Keep old prompt-based runs intact. Resume rejects their manifest for DeepSeek;
use a new output directory for native-tool experiments. Qwen judge settings
remain separate and should be held fixed for comparisons.
