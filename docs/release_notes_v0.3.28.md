# InferGrade Runner 0.3.28

Runner 0.3.28 keeps contract `0.3.20` and moves the current-model coding and
reasoning campaigns into the Runner-owned capability catalog.

## Changed

- Adds a reviewed Qwen3.5-9B Apple Silicon coding anchor using deployment,
  HumanEval+, and MBPP+ checks.
- Adds a reviewed Qwen3.5-9B Apple Silicon reasoning anchor using the exact-
  answer and sampled MMLU-Pro checks.
- Keeps the older Qwen2.5 coding and reasoning lanes as explicit historical
  controls instead of current defaults.

## Claim boundary

This release makes the two campaigns runnable and versioned. It does not claim
that current coding or reasoning evidence has already been collected, that a
single run is repeatable, or that either task score measures global intelligence.
