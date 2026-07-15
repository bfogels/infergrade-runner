# InferGrade Runner 0.3.27

Runner 0.3.27 keeps contract `0.3.20` and repairs the current-model coding evidence lane so sampled EvalPlus runs score the exact pinned subset they generated.

## Coding benchmark execution

- applies HumanEval+ and MBPP+ subset overrides to EvalPlus's import-time dataset state before scoring
- rejects missing, duplicate, or unexpected prediction IDs before the scorer can emit misleading partial evidence
- preserves separate raw completions, normalization metadata, samples, scorer output, and task-level pass/failure states
- validates both pinned HumanEval+ and MBPP+ subset paths with real container smokes

## Native runtime failures

- fails fast when native `llama.cpp` cannot load the selected model instead of waiting through a misleading readiness timeout

## Evidence boundary

This release repairs execution and failure classification. It does not retroactively convert earlier failed EvalPlus attempts into scored evidence, establish coding superiority for any model, or make canary subsets equivalent to full benchmark or leaderboard runs. Fresh measured runs are required.
