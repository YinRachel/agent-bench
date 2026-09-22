# Skill-writing hackathon

You are the curator. Write a **skill** (a folder with a `SKILL.md` plus any
supporting files) that makes a fixed **learner** model better at a domain. The
learner never changes; only your skill does. Your skill is scored on held-out
tasks you never see, with the same learner and the same limits you use here.

```
you (+ any AI assistant) ──write──▶ skill folder ──mounted read-only──▶ learner (frozen)
        ▲                                                                  │
        └─────────────── scores + trajectories on training tasks ◀────────┘
```

The learner is pinned in [`hackathon.toml`](hackathon.toml): model, agent harness,
per-task turn limits and the graders / simulated users some domains use. `stbench eval` applies that
file exactly, and the organizers score submissions and the autonomous baseline
with the same file.

| domain | benchmark | what the learner does | score per task |
|---|---|---|---|
| `qf` | QuantitativeFinance-Bench | solves a quantitative-finance task in a sandbox | task tests pass / fail |
| `health` | HealthBench | answers a health conversation | rubric grade from a model grader, 0–1 |
| `tau3` | τ³-bench | serves a simulated customer through tool calls | task assertions pass / fail |
| `hle` | Humanity's Last Exam | answers an expert-level question | answer graded by a model, pass / fail |

## Setup

Requirements: Docker (running), [uv](https://docs.astral.sh/uv/), Python 3.12+, and a Runware API key.

**Apple Silicon Mac:** task containers are amd64. In Docker Desktop, enable
Settings → General → **"Use Rosetta for x86_64/amd64 emulation on Apple Silicon"**
and Apply & restart; the default emulation crashes while the learner agent installs.
`stbench eval` warns you if it is off.

```bash
git clone <this repo> && cd <repo>
uv sync
cp .env_example .env          # then put your RUNWARE_API_KEY in .env
uv run stbench data pull      # downloads the training tasks into dataset/hackathon/
uv run stbench tasks --domain health
```

## The loop

Evaluate a skill on a few training tasks, with and without the skill:

```bash
cp -r submissions/example-team submissions/my-team   # then edit submissions/my-team/health/SKILL.md
uv run stbench eval --domain health \
  --skill submissions/my-team/health \
  --limit 8 --out runs/health-v1
```

For research runs, add `--model MODEL_ID` to override only the learner backbone
across every selected arm. Omitting it uses `[learner].model` from `hackathon.toml`
(currently `zai-glm-5-3-flash`); graders and simulated users remain unchanged.
Use a model ID supported by the configured OpenAI-compatible upstream. The existing
OpenHands routing adds `openai/` to IDs without a slash and preserves IDs containing
a slash. This option does not change the endpoint or credentials. The effective
learner model is recorded in `eval_result.json`. Research overrides do not change
the organizers' scored learner contract.

Runware Luna can be selected with `--model openai-gpt-5-6-luna`. For this model,
the learner gateway sends `reasoning_effort="none"` (required by Runware for
chat-completion tool calls) and uses `max_completion_tokens` for the existing
budget-clamped output limit. These settings apply to all learner arms, are
recorded under `learner.request_options` in `eval_result.json`, and do not apply
to graders or simulated users. Luna runs therefore evaluate reasoning disabled.
For Luna, a repository-local Harbor adapter configures the pinned OpenHands SDK
with `api_mode="chat"` and `reasoning_effort="none"`. These are recorded under
`learner.sdk_llm_options`. This avoids the SDK's automatic Responses API routing;
the standard Harbor runner does not expose the required LLM options. The adapter
only adds these constructor options to the per-trial runner copy, retaining the
same SDK version, tools, skills, and iteration limits. It fails explicitly if
Harbor changes the runner's LLM construction point. No installed dependencies
are edited.

```bash
uv run stbench eval --domain health \
  --skill submissions/my-team/health --arms baseline,placebo,skill \
  --model openai-gpt-5-6-luna --limit 1 --concurrency 1 \
  --out runs/health-luna
```

It prints the score per arm and the tokens spent, and writes `runs/health-v1/eval_result.json`
(summary and per-task scores) and `runs/health-v1/attempts.jsonl` (every attempt, with the
learner's answer and its Harbor trial folder).

Interrupted evaluations can continue in the same output directory with `--resume`.
Completed task/arm pairs are checkpointed immediately and skipped on restart;
the final summary combines old and new results. Usage ledgers append and the final
costs include all sessions. Reusing an existing output directory without `--resume`
is rejected. Keep the same task selection, arms, learner, graders and skill;
the resume manifest also checks dataset and skill content. Only one evaluator
can write to an output directory at a time (Unix file locking).

`--learner-budget-tokens` and `--grader-budget-tokens` override the token allowances
for the **new invocation**, without changing `hackathon.toml` or model choices.
Omit `--limit` to select the full local dataset. For example:

```bash
uv run stbench eval --domain health --arms baseline,placebo \
  --model openai-gpt-5-6-luna --concurrency 4 --resume \
  --learner-budget-tokens 20000000 --grader-budget-tokens 15000000 \
  --out runs/health/luna-5-SA-base
```

Older interrupted HealthBench baseline/placebo runs without a manifest can be
imported after checking the saved learner settings, verifier scores and grader
model. Other legacy runs need an explicit migration; their configuration is not
silently inferred. Malformed checkpoints are rejected rather than overwritten.

To read what the learner actually did, step by step:

```bash
uv run harbor view runs/health-v1/harbor-jobs     # opens the Harbor trajectory viewer
```

Useful flags:

- `--arms baseline,skill` (default) · add `placebo` to compare against a generic, content-free skill, which is what the leaderboard subtracts
- `--tasks name1,name2` to rerun exactly the tasks you care about
- `--limit N` to cap cost while iterating
- `--concurrency N` to run fewer containers at once (`qf` and `tau3` tasks each ask for 4–8 GB of RAM; use 1 on a laptop)

Then change the skill and run again. You can drive this loop with any coding
agent (Claude Code, Codex, ...): point it at this repo and let it call `stbench eval`.

## Scoring

- Each submitted skill runs on **private held-out tasks** from the same domain in three arms: no skill, a placebo skill, and your skill.
- **Score = pass rate with your skill − pass rate with the placebo.** Extra context on its own does not score.
- The learner, its turn and token limits, and the grader are the ones in `hackathon.toml`.
- The live leaderboard and the final ranking use **different** held-out sets.
- Your local numbers are measured on training tasks, so treat them as a guide.

## Rules

- **Learn from the training tasks only.** Do not copy held-out content, grading rubrics or answers from the public source datasets into a skill.
- **Tools must be self-contained.** Scripts in a skill run inside the task container: no external API calls and no credentials.
- **Don't change the learner.** Edits to `hackathon.toml` or the harness have no effect on your score.
- Every submission is checked for leaked task content and answer keys. A flagged skill scores zero.

## Submitting

Put each skill in `submissions/<team-name>/<domain>/`, then run
`uv run stbench check-skill submissions/<team-name>/<domain>` before you submit.
See [`submissions/README.md`](submissions/README.md).

## Cost tips

Every `stbench eval` spends your Runware credits. The learner runs once per task
per arm, and `health`, `tau3` and `hle` tasks also call a grader or simulated user. Start with `--limit 5`, add
tasks as the skill stabilises, and check the token and cost lines each run prints.
`qf` and `tau3` tasks run a full sandbox each and can take tens of minutes.

## What's in the repo

- `hackathon.toml` — the pinned learner contract
- `src/skilltrainbench/` — the harness: metering gateway, Harbor runtime, paired evaluator
- `submissions/` — your skills

### Local Qwen learner with the existing Runware grader

The separate `[learner_upstream]` table in `qwen-local.toml` routes the learner
to `http://127.0.0.1:11434`; `--learner-base-url` can override that URL.
The local configuration uses Ollama's `qwen3:8b` Q4_K_M weights through a separate
`qwen3-stbench:8b` alias. Create the alias once (the base model must already exist):

```bash
ollama create qwen3-stbench:8b -f configs/qwen3-stbench.Modelfile
```

The alias sets a 20,480-token context and a smaller prompt-processing batch. The
OpenHands adapter uses chat completions, disables thinking, and reserves 16,384
input / 4,096 output tokens. `qwen-local.toml` keeps the original grader, tasks,
and iteration limits, sets concurrency to one, and raises the HealthBench agent
wall-clock timeout to 30 minutes for slower local inference. `hackathon.toml`
remains unchanged.

```bash
uv run stbench eval --config qwen-local.toml \
  --domain health --arms baseline,placebo \
  --learner-base-url http://127.0.0.1:11434 \
  --limit 1 --out runs/health/qwen3-8b-pilot
```

The host gateway connects to Ollama on loopback; task containers continue to use
Harbor's gateway address. **Only the learner is local.** HealthBench still uses
Runware's configured Haiku grader and `RUNWARE_API_KEY`, so grading still costs
money. The learner endpoint receives no provider credentials. An authenticated
separate learner server can use `--learner-key-env ENV_VAR_NAME`. Both root URLs
and URLs ending in `/v1` are accepted. Do not use `STBENCH_UPSTREAM_BASE_URL` for
this split setup: that setting also changes the grader endpoint.

Use a new output directory for Qwen; Luna results must not be resumed with a
changed backbone. For a full local dataset run, omit `--limit` and choose adequate
learner and grader token budgets as described above. Local inference still counts
against the harness's token pool. Ollama does not return API pricing, so learner
cost is reported as unknown rather than an invented dollar amount.

A synthetic OpenHands tool test, with no paid grader, is available:

```bash
uv run python scripts/smoke_local_qwen.py
```
