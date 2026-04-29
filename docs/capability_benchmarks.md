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

- `Multi-turn chat memory`
  - Why: low-cost assistant decision signal for retaining facts, corrections, and output constraints across a short transcript.
  - InferGrade role: native local-friendly assistant decision check after IFEval.

- `MMLU-Pro reference`
  - Why: recognized broad knowledge and reasoning benchmark with harder, more robust multiple-choice questions than legacy MMLU.
  - InferGrade role: explicit sampled assistant reference lane with category breakdowns; useful for stronger evidence, but not a quick default or leaderboard claim.

### Agentic Coding

- `EvalPlus HumanEval+`
  - Why: high-signal code generation benchmark, much more rigorous than the original HumanEval, and explicitly designed for safe evaluation workflows.
  - InferGrade role: first real coding capability benchmark for `agentic_coding`.

- `EvalPlus MBPP+`
  - Why: expands beyond HumanEval-style tasks, uses the same container/evaluation ecosystem, and gives us a second coding signal without introducing a completely separate harness.
  - InferGrade role: gold-tier extension for `agentic_coding`.

## Selected Next

These are selected as high-value next additions, but are not yet wired into the first runnable capability container pass:

- `Repository edit smoke`
  - Why: a deterministic, small repo-edit task can bridge the gap between code-generation benchmarks and SWE-style work.
  - InferGrade role: likely next local-friendly coding decision check before heavier reference suites.

- `GPQA`
  - Why: high-value hard reasoning/knowledge benchmark with strong anti-memorization properties.
  - InferGrade role: assistant reference suite for differentiating models that look similar on instruction following.

- `LiveCodeBench`
  - Why: broad contemporary coding benchmark with multiple task modes and temporal freshness.
  - InferGrade role: coding reference suite after local sandboxing, task pinning, and cost metadata are proven.

- `SWE-bench Verified`
  - Why: highest-value software engineering benchmark in this space, but much more operationally expensive than the first-pass coding lanes.
  - InferGrade role: gold/curated reference evidence first, not a default laptop run.

## Expansion Principle

InferGrade should move toward benchmark legitimacy comparable to serious model-analysis products without making first users wait hours for a first answer. That means every new benchmark candidate should declare:

- the use case it supports,
- whether it belongs in the short decision lane, reference lane, or gold/curated lane,
- the score dimension and planned score policy,
- local feasibility and expected cost,
- and why it is not part of the default quick path yet.

Planned candidates are roadmap metadata only. They must not be rendered or validated as runnable checks until Runner owns a reproducible harness, scoring policy, fixture/version pin, and runtime-cost story.

The detailed acceptance gates for heavier third-party lanes live in [Stronger Evidence Lane Gates](stronger_evidence_lane_gates.md).

## Capability Catalog Shape

InferGrade now treats benchmark scope as:

- capability suites
- benchmark groups
- individual benchmark checks

The currently implemented first-user catalog is:

### `chat_instruction_following`

- group: `instruction_following`
  - check: `ifeval`
- group: `chat_memory`
  - check: `multiturn_chat_memory_v1`
- group: `broad_reasoning_knowledge`
  - check: `mmlu_pro_reference_v1`
- group: `deployment_chat`
  - check: `interactive_chat_v1`
- group: `deployment_batch`
  - check: `batch_generation_v1`
- group: `deployment_long_context`
  - check: `long_context_v1`

### `coding_code_editing`

- group: `coding_core`
  - check: `evalplus_humaneval`
- group: `coding_breadth`
  - check: `evalplus_mbpp`
- group: `deployment_chat`
  - check: `interactive_chat_v1`
- group: `deployment_batch`
  - check: `batch_generation_v1`
- group: `deployment_long_context`
  - check: `long_context_v1`

### `quant_fidelity`

- group: `quant_fidelity`
  - check: `perplexity_reference_v1`

Compatibility breadth labels like `canary`, `standard`, and `gold` are still derived from the selected checks for older flows and release planning, but they are no longer the main user-facing benchmark abstraction.

## Capability State Semantics

The current supported suites should report capability truthfully rather than softening failures into generic missing data:

- `scored`: the planned lane completed with a trustworthy suite score
- `partial`: only part of the planned lane scored
- `failed`: InferGrade attempted the lane, but benchmark execution failed before producing a trustworthy score
- `skipped`: capability execution was explicitly disabled
- `not_yet_benchmarked`: the slice is meaningful, but no benchmark execution has happened yet
- `not_comparable`: the run does not define a meaningful capability slice

The currently supported first-user benchmark lanes are:

- assistant lane: `chat_instruction_following` via `ifeval`, `multiturn_chat_memory_v1`, and explicit sampled `mmlu_pro_reference_v1`
- coding lane: `coding_code_editing` via `evalplus_humaneval` and `evalplus_mbpp`

Those are the lanes we expect to keep locally regression-tested and operationally trustworthy first.

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
