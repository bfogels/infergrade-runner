# InferGrade Runner 0.3.29

Runner 0.3.29 keeps contract `0.3.20` and corrects the Runner-owned MMLU-Pro
format-failure boundary used by task-scoped reasoning evidence.

## Changed

- Counts a completed generation that violates the declared answer-letter format
  as an incorrect answer under `exact_multiple_choice_letter_accuracy_v3`.
- Keeps generation and runtime failures unscored, with existing partial/failed
  benchmark states and task-level failure artifacts preserved.
- Publishes malformed-output counts as diagnostics while retaining the strict
  completed-generation denominator.
- Aligns scored benchmark coverage with component-score eligibility and removes
  a false `suite_unavailable_for_use_case` reason from valid explicit reasoning
  selections.

## Claim boundary

This release fixes whether completed format violations participate in a sampled
MMLU-Pro score. It does not recover answers, loosen the parser, rescale raw
attainment, rewrite existing results, establish repeatability, or claim global
reasoning or intelligence quality.
