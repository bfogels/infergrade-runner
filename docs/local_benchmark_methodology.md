# Local Benchmark Methodology

This document defines the v0.2.7 contract for local capability evidence. It is intentionally narrower than a benchmark lab methodology: Runner should produce reproducible local artifacts that help a user choose a setup, while avoiding leaderboard or global model-quality claims.

## Evidence Lanes

Runner uses four evidence lanes:

- `smoke`: a minimal execution check. It can show that a setup runs, but cannot support quality conclusions.
- `decision`: a small local sample that can help choose a setup for one use case on one machine.
- `reference`: deeper local evidence with stronger fixture, duration, and scoring controls.
- `gold`: high-legitimacy evidence that requires stronger dataset, scoring, sandbox, provenance, and maintainer-review controls before product claims become strong.

The terms `gold/curated` and `curated/gold` are retired. If evidence is curated, that is provenance or review metadata; the evidence lane remains `gold`.

## Capability Surfaces

Capability artifacts declare one primary surface:

- `local_assistant_capability`: instruction following, structured output, conversational retention, and assistant behavior.
- `local_coding_capability`: code generation, repair, structured patch output, and bounded repo-edit tasks.
- `local_reasoning_capability`: exact-answer, multiple-choice, or structured reasoning checks.
- `quant_fidelity`: quant-to-quant fidelity signals such as perplexity or controlled reference outputs.
- `deployment_fitness`: runtime, latency, throughput, memory, stability, and local hardware fit.

These surfaces are not combined into a global intelligence score. A model can be fast but weak on a capability lane, or capable but too slow for a user’s hardware.

## Artifact Contract

The Runner-owned `capability_run` artifact is distinct from `native_first_run` and from product-facing result records. The schema lives at `schemas/json/capability_run.schema.json` and requires:

- evidence lane, surface, evidence grade, confidence label, and experimental flag
- task family, prompt/task version, fixture or dataset revision, scoring policy, scorer type, and repetitions
- model, runtime, hardware, and generation-preset provenance
- summary state, score dimension, score where applicable, duration, TTFT, tokens/sec, and token counts when available
- per-task state, output artifact pointer, score where applicable, scorer metadata, timing, token counts, and failure class
- manifest, raw output paths, scoring output paths, and supporting file paths
- supported and unsupported claim boundaries

Every artifact must remain useful without Hub. Hub may summarize or compare, but Runner owns execution truth.

## State Semantics

Capability states are explicit:

- `scored`: the task or run produced a trustworthy score under its scoring policy.
- `partial`: only part of the planned lane scored.
- `failed`: Runner attempted the task or run, but execution, generation, scoring, sandboxing, or runtime setup failed.
- `skipped`: the task or lane was intentionally disabled or excluded.
- `not_yet_benchmarked`: the surface is meaningful, but no benchmark execution happened.
- `not_comparable`: the task or run cannot be compared under the declared protocol.

Failed, skipped, and not-comparable states must not be collapsed into zero scores unless the declared scoring policy explicitly says that is correct.

## Confidence Labels

Confidence labels describe evidence weight, not prestige:

- `single_smoke`
- `thin_local_sample`
- `repeated_local_run`
- `stronger_local_sample`
- `reference_sample`
- `gold`

Runner must not automatically promote evidence into a stronger confidence label just because a score is high. Promotion requires the corresponding protocol controls, sample size, repetition, and validation gates.

## Local-First Protocol

Every runnable check should capture:

- prompt/task version
- fixture or dataset revision
- model artifact identity and quant identity where available
- runtime/backend version and selected runtime channel
- hardware snapshot
- generation preset
- repetition count
- scoring method and scorer version
- raw outputs and scoring artifacts
- duration, input/output tokens, TTFT, tokens/sec, failures, and partials where available

Docker or Podman can be used for lanes that truly require sandboxing, but native first-run and first local capability answers should not silently become Docker-only.

## Claim Boundaries

Local capability artifacts may support narrow statements like:

- this setup completed a pinned local assistant task set
- this setup produced deterministic structured outputs for the declared fixtures
- this setup had the recorded latency and token throughput on this hardware
- this quant artifact produced the recorded fidelity signal under the declared scorer

They do not support claims like:

- globally best model
- public leaderboard evidence
- broad assistant intelligence
- decision-grade evidence without implemented thresholds and gates
- public gold evidence without gold controls and maintainer review

## Future Backlog

Adaptive model-vs-model testing, local dollar-cost estimation, broad SWE-bench, LiveCodeBench, runnable GPQA, public leaderboard mechanics, and cloud benchmark execution remain future work. They should not be mixed into the v0.2.7 contract slice.
