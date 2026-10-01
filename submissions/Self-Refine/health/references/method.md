# Method and evaluation

Based on Madaan et al., *Self-Refine: Iterative Refinement with Self-Feedback*,
NeurIPS 2023, Section 2 and Algorithm 1. The algorithm generates a draft, uses
that same model for actionable feedback, and refines with accumulated history.
It returns the latest draft after a stopping signal or bounded iteration count.
The original paper did not evaluate HealthBench.

This adaptation supplies health-response review dimensions rather than task
rubrics. It uses zero-shot instructions instead of copying benchmark examples.
One revision is the default because this repository's HealthBench contract allows
four learner turns. An agent turn is not the same as an algorithm stage or a model
call. The skill's in-context workflow is an approximation of separate calls;
`run()` provides explicit separate-call orchestration for controlled research.
The submitted skill does not replace the harness or change its model settings.

## Code interface

Add the skill's `scripts` directory to your Python import path, then use:

```python
from self_refine import run
result = run(conversation, generate=same_model_callable, max_refinements=1)
answer = result.answer
```

The callable accepts a prompt string and returns text. The caller must keep the
same model for every stage and enforce its own token/time budget. This package
contains no network client. Do not wire an external model into the offline skill
container. Set `max_refinements=0` for a direct-generation control; up to four
refinements are supported for experiments with sufficient budget.

Feedback must be a JSON object with a boolean `stop` and list `issues`. Each issue
has nonempty strings `dimension`, `location`, `problem`, `fix`. `stop` must equal
`not issues`. No fenced JSON, extra keys, scalar scores, or truthy strings are
accepted. Invalid output raises an exception without automatic extra model calls.
The loop records all drafts and feedback, stops early on no issues or unchanged
output, and otherwise returns the latest draft at the cap. A capped final revision
has not received a further critique. It does not select a purported best answer
using unvalidated self-scores. Traces can contain sensitive conversation data;
store them only in the caller's intended evaluation output location.

## Validate and measure

From the repository root:

```bash
uv run python -B submissions/Self-Refine/health/scripts/test_self_refine.py
uv run stbench check-skill submissions/Self-Refine/health
uv run stbench eval --domain health --skill submissions/Self-Refine/health \
  --arms baseline,placebo,skill --limit 5 --concurrency 1 \
  --out runs/health/self-refine-pilot
```

The last command runs paid learner/grader inference and requires the repository's
configured runtime. Use the same tasks, backbone, and budgets across arms. Compare
paired task scores, skill-minus-placebo, tokens, completion rate, and trajectories.
A five-task pilot checks operation, not reliable efficacy. For a stronger claim,
use a larger prespecified training subset and report paired uncertainty. Keep
final evaluation tasks separate from prompt tuning. Do not bake task IDs, rubric
text, or reference answers into the skill. For research ablations compare zero,
one, and two revisions with the same generator and fixed prompts; report added
compute. Static checks and unit tests do not demonstrate HealthBench improvement.
