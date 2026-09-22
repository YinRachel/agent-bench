---
name: health-self-improvement
description: Verify and selectively improve health answers before submission.
---

# Health Self-Improvement

Solve the user's health task directly.

Do not replace your existing medical reasoning with a fixed template.
Preserve a good initial answer rather than rewriting it unnecessarily.

## Procedure

For each task:

1. Understand exactly what the user is asking.
2. Form a candidate answer using your existing knowledge and reasoning.
3. Verify the candidate for concrete defects.
4. Repair only defects you can identify.
5. Write only the final answer to the required output file.

Do not expose the draft, verification process, or internal reasoning in the
final response.

## Supporting files

Use the supporting files selectively:

- `response_patterns.md` contains lightweight patterns for different kinds of
  health requests. Consult it when deciding how the response should be
  structured or whether clarification is necessary.

- `verification.md` contains the detailed candidate-answer verification
  procedure. Use it to check a candidate when verification is useful.

Do not mechanically reproduce these files in the answer.
Do not add content merely because it appears in a supporting file.

## Core verification

Before finalizing, check:

- REQUEST: Did I answer exactly what was asked?
- FORMAT: Did I follow explicit format, language, and length requirements?
- FACTS: Is any claim likely incorrect, outdated, unsupported, or
  context-dependent?
- ASSUMPTIONS: Did I assume information not provided?
- OMISSIONS: Is anything essential to the requested answer missing?
- SAFETY: Is there a concrete safety problem I failed to address?
- OVERREACH: Did I add unnecessary diagnoses, warnings, referrals,
  treatments, or background information?

## Selective repair

Revise only when you can identify a concrete defect.

When repairing:
- fix the identified defect;
- preserve correct parts of the candidate;
- do not expand unrelated parts of the answer;
- do not introduce new claims unless necessary for the repair.

If the candidate already answers the task accurately and appropriately,
preserve it.

Prefer a correct, direct answer over a more comprehensive answer.