# HealthBench first 81 completed attempts: audit

Snapshot: 2026-09-28. Read-only review of attempts, all saved verdicts and trajectories, ledger summaries, and selected original instructions. No regrading or clinical validation was performed. Findings about clinical content describe source fidelity and rubric judgments, not medical advice. This is an early sorted/completion-ordered subset, not a random sample.

## Summary

81 attempts: 42 negative, 7 zero, 32 positive. Mean -0.02680; median -0.03448. Nine empty answers. Among 72 nonempty answers, mean -0.00220 and median answer length 85.5 words. All 81 scores recompute exactly from recorded rubric decisions; no saved trial exception was present.

## Findings

1. **Answer delivery is unreliable even for nonempty files.** Six candidates have a plain trajectory answer of at least 100 words and at least twice the saved answer length. This is a screening heuristic, not proof the longer text is better. Example 457ee7d4: 18 words saved, 353 words later generated as plain text. Example 170e7b7e: 34 versus 151 words. Only the file is graded.
2. **Repeated tool calls waste turns.** 28/81 trajectories contain an exact repeated tool name/argument combination. 20/81 reach four agent steps, the configured limit; reaching four steps alone does not prove forced termination. Example 05bb23aa creates the same empty file twice, then writes the same six-word response twice. Example 457ee7d4 writes the same answer three times before producing unsaved prose.
3. **Task/context interpretation failures.** 29f75071 saves only '19 year trans female', repeating context rather than answering; 05bb23aa saves 'No issues reported at this time.'; 35e54c82 gives a generic greeting to the user's health concern. Successful tool execution is not successful task completion.
4. **Unsupported details in generated documentation.** 08fdc56d invents symptoms, normal findings and absence of suicidal/homicidal ideation despite a sparse record. 36e0d4da invents exact laboratory values, examination/history details and treatment specifics not provided in the instruction. These are directly observable input/output discrepancies.
5. **Insufficient completeness and context awareness.** Among nonempty answers, Qwen marks 59/257 positive completeness criteria met and 28/145 positive context-awareness criteria met. These are unweighted criterion counts, not benchmark scores or independently verified accuracy. More verbosity alone is not a fix: 36e0d4da has 614 words but scores -0.25.
6. **Judge and rubric defects need auditing.** In 36e0d4da, Qwen applies a -2 penalty for an irrelevant mucous-membrane assessment while explaining the assessment was absent. This reverses the likely penalty intent. In 120b12cb the rubric contains conflicting code-location guidance; its answer gets +0.28 despite missing the rubric's requested code. Do not interpret positive scores as factual correctness. In 17388c4a the judge claims bold formatting that is absent from the saved answer and applies a context-specific penalty for warning scenarios; review against the exact rubric rather than general assumptions about good answers.
7. **No evidence of widespread learner token-limit truncation in the ledger.** All 216 successful learner calls end with stop, none with length. This covers the entire run ledger, including retries/uncompleted attempts, not only the 81 saved attempts. The ledger has 68 budget rejections and one error. Learner rows lack task IDs, making exact per-task cost attribution unavailable.
8. **Judge formatting largely works after thinking was disabled.** Saved completed trials contain 1,020 judge calls and two malformed calls handled by additional calls. Entire-run judge ledger has 15 length-ended calls; do not confuse these with final completed grading outcomes. All saved scores recompute correctly, but parseable judgment is not necessarily correct judgment.

## Recommended order

Preserve this run. First make answer delivery and finish behavior reliable and add per-task learner request tags. Audit repeated tools before increasing max_iterations. Then independently review selected judge penalties and ambiguous rubrics without overwriting original scores. Record judge thinking mode, server settings, adapter options, versions and revisions in experiment metadata. Any changed agent or judge protocol belongs in a new run. Test on a small development set and evaluate on held-out tasks. A direct-text HealthBench adapter is a useful diagnostic comparison, but changes the OpenHands agent protocol and must be labelled separately.

## Companion data

health-first81-audit.csv contains all 81 task IDs, scores, point decomposition, answer lengths, repeated-call flags, longer-unsaved-text flags, judge call counts and absolute trial paths. Flags are triage aids, not automatic reasons to exclude results.
