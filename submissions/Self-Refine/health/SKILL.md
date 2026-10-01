---
name: health-self-refine
description: Improve a health conversation response through a bounded draft, specific self-feedback, and revision cycle using the same learner.
---

# Health Self-Refine

Answer the latest user message using the whole provided conversation. Use the same
learner to draft, critique, and revise. This is inference-time improvement, not
training or an external grader. Never access hidden rubrics, reference answers,
verifier files, or other patients' tasks.

## Default workflow: one revision

The HealthBench harness permits only four agent turns. Complete the following
within the available generation budget; these stages need not be separate tool
calls. Reserve enough time to deliver the answer in the task's required format
and location. Do not spend turns installing packages or running another model.

1. **Draft:** Prepare a direct response grounded in the conversation. Distinguish
   reported facts from assumptions. Address the actual request and its audience.
2. **Feedback:** Inspect the draft against the checks below. For each real issue,
   identify the affected phrase or missing element, explain the defect briefly,
   and specify an edit. Keep useful content. Do not invent problems to justify
   revision. Stop if there are no concrete, actionable issues.
3. **Refine:** Apply supported corrections to produce a complete replacement.
   Recheck changed claims against the original conversation. Feedback is a
   suggestion, not new clinical evidence. Preserve correct specifics; remove
   unsupported claims instead of replacing them with guesses.
4. **Deliver:** Return only the final response, not drafts, critique, scores, or
   the self-review process. Follow the task's output contract exactly.

Review dimensions (apply only where relevant):

- **Context and coverage:** Did the answer address every explicit question and
  respect age, symptoms, timing, constraints, prior advice, language, and audience?
- **Accuracy and uncertainty:** Are diagnoses and causal claims appropriately
  qualified? Are missing facts acknowledged without inventing details, citations,
  examinations, test results, or certainty?
- **Safety and urgency:** Does the response handle any stated warning signs with
  proportionate urgency and actionable next steps? Avoid both reassurance that
  dismisses risk and automatic emergency escalation without contextual support.
- **Treatment specificity:** Are medication, dose, interaction, and contraindication
  claims supported? If essential details are absent, avoid guessing and identify
  what needs clarification. Do not add treatment details merely to sound thorough.
- **Usefulness and communication:** Are next steps practical and prioritized?
  Match the user's expertise and emotional context. Ask only questions that
  materially affect advice; do not replace a useful answer with a questionnaire.
  Remove repetition and boilerplate that obscures the answer.

A second pass is optional only if a concrete unresolved issue remains and the
budget allows it. Carry previous drafts and feedback forward to avoid repeating
mistakes. Stop on no actionable issues, an unchanged draft, or the pass limit.
Self-approval is not proof of clinical correctness.

## Optional code

`scripts/self_refine.py` provides prompt construction, strict feedback validation,
and a bounded loop accepting a single caller-supplied generation function. It has
no model client or network dependencies. The learner normally follows the workflow
above directly; the script cannot generate medical content by itself.

For a local prompt aid, run `python <skill-dir>/scripts/self_refine.py review
--conversation /tmp/conversation.txt --draft /tmp/draft.txt` (one command).
Use scratch files outside this read-only skill folder. The script prints a review
prompt; you supply the feedback. See `references/method.md` for the feedback schema,
research interface, and evaluation procedure.
