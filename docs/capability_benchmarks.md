# Capability Benchmarks

InferGrade needs capability benchmarks that are:

- representative of real user-facing skills,
- objectively scored,
- practical to run in containers,
- and credible enough that the open-source community already recognizes them.

## Implemented First

### General Assistant

- `IFEval`
  - Why: strong fit for instruction following, objective checking, compact enough to tier by sample count, and already used by the Hugging Face Open LLM Leaderboard.
  - InferGrade role: first real quality gate for `general_assistant`.

### Agentic Coding

- `EvalPlus HumanEval+`
  - Why: high-signal code generation benchmark, much more rigorous than the original HumanEval, and explicitly designed for safe evaluation workflows.
  - InferGrade role: first real coding capability benchmark for `agentic_coding`.

- `EvalPlus MBPP+`
  - Why: expands beyond HumanEval-style tasks, uses the same container/evaluation ecosystem, and gives us a second coding signal without introducing a completely separate harness.
  - InferGrade role: gold-tier extension for `agentic_coding`.

## Selected Next

These are selected as high-value next additions, but are not yet wired into the first runnable capability container pass:

- `MMLU-Pro`
  - Why: stronger broad knowledge/reasoning signal than legacy MMLU and already recognized in modern open-model evaluation stacks.

- `GPQA`
  - Why: high-value hard reasoning/knowledge benchmark with strong anti-memorization properties.

- `LiveCodeBench`
  - Why: broad contemporary coding benchmark with multiple task modes and temporal freshness.

- `SWE-bench Verified`
  - Why: highest-value software engineering benchmark in this space, but much more operationally expensive than the first-pass coding lanes.

## Tiering

### `general_assistant`

- `canary`: `IFEval` subset
- `standard`: larger `IFEval` subset
- `gold`: full `IFEval`

### `agentic_coding`

- `canary`: `EvalPlus HumanEval+` subset
- `standard`: full `EvalPlus HumanEval+`
- `gold`: full `EvalPlus HumanEval+` plus `EvalPlus MBPP+`

## Container Contract

Each benchmark container follows the same basic contract:

1. `prepare`
   - emits `cases.jsonl`
   - emits any filtered benchmark input files needed for evaluation

2. host-side generation
   - InferGrade asks the backend adapter to answer each case prompt
   - InferGrade writes `predictions.jsonl`

3. `evaluate`
   - reads `predictions.jsonl`
   - runs official or benchmark-native evaluation logic inside the container
   - emits `summary.json` and raw benchmark artifacts

This split keeps model execution and benchmark scoring decoupled while still making the benchmark harness itself reproducible and containerized.

## Why Not Everything At Once

The heavier benchmarks are absolutely worth supporting, but first implementation priority goes to the benchmarks that let us ship:

- a real capability score,
- a credible first coding lane,
- a credible first assistant lane,
- and a stable container contract that later benchmarks can reuse.

That is a better foundation than trying to jump straight to every prestigious benchmark in the ecosystem at once.
