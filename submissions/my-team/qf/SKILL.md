---
name: finance-pipeline-recovery
description: Build and debug financial data-processing scripts that must produce structured output files, with syntax checks, evidence-based edit recovery, and output validation.
---

# Reliable financial data pipelines

Translate the task's requested deliverables into a short checklist: output paths,
columns or JSON keys, row grain, ordering, units, and numerical checks. Derive
these from the task instructions, not assumptions. Read input headers and small
samples before implementing joins or calculations.

## Keep the program executable

Build the pipeline in small executable stages. Keep reusable functions at the
top level and orchestration in a short main function. After changing function
boundaries or indentation, run `python -m py_compile YOUR_SCRIPT.py` using the
same interpreter that will execute the script. Fix the first syntax error before
adding more calculations. A successful file edit is not proof the program runs.

## Recover from failed edits

Treat a rejected replacement as evidence that your view of the file is stale.
Immediately read the actual affected lines, including surrounding indentation,
before constructing another edit. Copy the exact current text as the replacement
target; ensure the new text differs. Do not repeat a rejected edit unchanged.

If local edits repeatedly fail or damage function structure, stop patching
individual indentation fragments. Save a backup, read the whole affected
function, and replace that complete function using clear boundaries. For a short
script whose structure is broken throughout, rewriting it coherently can be
safer than further fragment replacements. Preserve already implemented logic,
then syntax-check and execute again. Change strategy after two failed repairs
to the same block instead of spending the remaining turns repeating them.

## Validate execution and deliverables

Run the script after syntax checking. Read the exit status and traceback; repair
the earliest runtime failure before inspecting downstream missing files. Use
small input samples for debugging when appropriate, but generate final outputs
from the full requested input scope.

Before finishing, check every requested artifact exists and can be loaded.
Compare CSV headers and JSON keys with the deliverable checklist. Check required
nonempty values, uniqueness at the requested row grain, sort order, join
cardinality, and totals across outputs. Use financial invariants only where the
task warrants them, such as weights summing to one or position values summing
to portfolio totals. Handle units and zero denominators explicitly.

Derive summaries from the same computed tables used for detailed outputs.
Placeholder summaries or empty files created merely to satisfy existence checks
are not completed calculations. Run any provided validation commands that the
task permits; do not modify tests or fabricate their results. If execution still
fails, report the actual blocker and remaining deliverables rather than claiming
completion.
