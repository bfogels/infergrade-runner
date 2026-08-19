# Benchmark Legitimacy Program

InferGrade's benchmark product should climb from quick setup checks to stronger local evidence and then to reference and gold evidence. The catalog must make that progression explicit so thin local samples cannot accidentally become broad claims.

## Maturity Levels

Runner uses these benchmark maturity levels:

- `planned`: roadmap metadata only; not runnable.
- `thin_local_sample`: small pinned local fixture with deterministic scoring and thin-sample caveats.
- `strong_local_candidate`: implemented or near-implemented local evidence that still needs broader samples, repeated-run facts, observed duration, or failure-rate metadata before stronger claims.
- `reference_candidate`: recognized or justified benchmark candidate that still needs complete reproducibility, scoring, dataset, or sandbox review.
- `reference_runnable`: intentionally selected reference evidence with pinned dataset or fixture revision, preserved raw/scoring artifacts, and explicit claim boundaries.
- `gold_candidate`: possible high-legitimacy evidence that requires legal/access controls, stronger sandbox/runtime controls, and maintainer review.
- `gold_runnable`: runnable gold evidence only after reference gates, dataset/legal/access gates, sandbox controls, and maintainer-review gates are satisfied.

## Required Catalog Metadata

Every implemented check and every planned benchmark candidate must have a `benchmark_status_matrix` entry declaring:

- capability surface
- evidence lane
- maturity
- runnable status
- default inclusion status
- fixture or dataset revision status
- harness status
- scoring policy id
- sample policy
- expected duration/token-volume status
- sandbox requirement
- claim boundary
- promotion blockers

Runner tests validate that this metadata exists. New benchmark checks should fail catalog tests until their legitimacy status is declared.

The validator also enforces the promotion transition. An entry in `planned_benchmark_candidates` must remain `not_runnable` and cannot declare runnable maturity. Promotion moves the lane into `checks`; a runnable check must name an implemented harness and bounded duration/token-volume status, while `reference_runnable` and `gold_runnable` additionally require a pinned fixture or dataset. A benchmark cannot appear in both collections. These checks prevent a roadmap-only lane from becoming runnable through status-copy changes alone; they do not substitute for reviewing the harness or its evidence.

## Promotion Gates

A `thin_local_sample` can be runnable when:

- fixtures are pinned in Runner;
- scoring is deterministic;
- task count and sample policy are documented;
- artifact contract is valid;
- unsupported claims are explicit.

A `reference_runnable` lane requires:

- a recognized benchmark source or explicit justification;
- pinned dataset, fixture, or task-window revision;
- reproducible harness behavior;
- reviewed scoring policy;
- local sample and deeper/full sample policy;
- raw outputs and scoring artifacts preserved;
- structured failure states.

A `gold_runnable` lane requires all reference gates plus:

- dataset/legal/access controls;
- strong sandbox/runtime controls;
- maintainer review;
- product copy that prevents casual default-laptop or leaderboard-style overclaiming.

## Current Status

The first thin local samples are:

- `multiturn_chat_memory_v1`
- `coding_static_repair_v1`
- `repository_edit_smoke_v1` (intentional, zero-weight diagnostic pending a cross-family distribution audit)
- `stateful_tool_loop_diagnostic_v1` (intentional, zero-weight synthetic stateful diagnostic pending a cross-family distribution audit)
- `reasoning_exact_answer_v1`
- `reasoning_constraint_stress_v1` (legacy direct-no-think v1 fixture; quarantined from runnable, readiness, recommendation, and release evidence)

The first reference-runnable lanes are:

- `mmlu_pro_reference_v1`
- `evalplus_humaneval`
- `evalplus_mbpp`
- `gpqa_diamond_reference_v1`
- `context_retrieval_reference_v1`
- `bfcl_local_reference_v1`
- `perplexity_reference_v1`

Important candidates that are not yet promoted:

- `livecodebench_reference_v1`: implementation-ready but non-runnable. The v6 task window, deterministic 48-task snapshot, scorer, hidden-test boundary, and unprivileged subprocess controls are implemented; source-license review and a separately verified protocol image still block selection.
- `swebench_verified_gold_v1`: gold candidate only, non-runnable until maintainer-reviewed gold controls exist.

`gpqa_diamond_reference_v1` and `context_retrieval_reference_v1` are
diagnostic-only reference lanes. They have zero headline capability weight and
are not part of the default suites.

`bfcl_local_reference_v1` and `stateful_tool_loop_diagnostic_v1` are complementary zero-weight tool-use diagnostics. The first is a pinned BFCL-derived single-turn structured-call reference; the second is a pinned synthetic multi-generation simulator loop. Neither supports native function-calling, broad agent-autonomy, or leaderboard claims, and neither is empirically ready without cross-family distributions and headroom audits.

`perplexity_reference_v1` is reference-runnable only as same-family quant-fidelity evidence. Its comparability key includes model family, checkpoint, tokenizer id, corpus id/revision, and protocol id/parameters. It does not support cross-family model ranking, broad capability claims, gold evidence, or leaderboard claims.

## Claim Boundaries

Allowed language:

- thin local sample
- strong local evidence
- reference lane
- gold lane
- experimental
- not comparable
- failed
- partial
- reference sample
- gold evidence

Avoid language unless the gates actually exist:

- leaderboard-grade
- globally best
- proven intelligence
- decision-grade
- gold-runnable

Benchmark legitimacy is not a copywriting exercise. A lane earns stronger claims only after Runner owns the contract, harness, data policy, scoring policy, artifacts, failure semantics, and review path.
