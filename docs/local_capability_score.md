# Local Capability Benchmark Index Contract

InferGrade reports task-scoped benchmark-attainment indexes, not grades of a model and not a global intelligence score. Deployment speed, latency, memory, model size, cost, and quant fidelity remain separate decision axes.

## Score families

The Runner currently owns three versioned score families:

| Score | Version | Intended question |
| --- | --- | --- |
| Local assistant benchmark index | Capability protocol v3.1 | What fraction of the current weighted assistant suite did this setup attain? |
| Local coding score | `local_coding_score_v2` | How well did this setup perform on the pinned coding benchmark mix? |
| Local reasoning score | `local_reasoning_score_v2` | How well did this setup perform on the pinned reasoning benchmark mix? |

Scores use a `0..1` contract value. Hub displays this as benchmark points, not `x/100`: a value of `0.72` is `72 benchmark points`. A value of `1.0` must be labeled `suite ceiling reached`, never `perfect`, because it means only that every scored check in that version passed. Comparisons are valid only within the same score version and surface.

## Current assistant benchmark weights

Weights live in `schemas/capability_catalog.json` as `primary_score_weight` values. They sum to one within each scored surface.

- Capability protocol v3.1: IFEval `0.45`; the 24-case compositional instruction fixture `0.55`.
- Multi-turn chat memory remains visible as a zero-weight diagnostic component.
- Coding: EvalPlus HumanEval+ `0.55`; EvalPlus MBPP+ `0.30`; static repair `0.15`.
- Reasoning: MMLU-Pro reference `0.80`; exact-answer decision sample `0.20`.

Changing a weight or benchmark mix requires a new protocol revision. The expanded compositional fixture is provisional until it passes the declared cross-model distribution audit; IFEval remains its established companion component.

## Saturation policy

The memory microcheck was removed from assistant headline weight after a 2026-07-14 audit of the latest 300 public result briefs found 35 of 37 scored results at its ceiling, including sub-billion-parameter models. Its result still proves whether a setup cleared that exact fixture, but it no longer distinguishes assistant capability.

Every weighted component needs a periodic distribution audit across diverse model families and sizes. If its ceiling rate exceeds the documented threshold, InferGrade must demote it to diagnostic evidence, expand or replace it, and increment the score version. A saturated component must not be rescued by arbitrary penalties or model-age priors.

## Coverage gate

Capability protocol v3.1 needs all declared benchmark weight (`1.00`), at least two scored components, at least two score dimensions, and `standard` or deeper sample depth before an individual aggregate can publish. A canary can guide setup and expose failures, but it cannot publish the index even if all sampled cases pass. Corpus-level calibration is separate: the protocol remains provisional until at least 20 observations across five families, three parameter bands, and eight exact model-plus-quant setups retain six distinct values; at least four setups must have independent repeats; at least 75% of observations must come from Runner-declared current or recent campaign targets; no more than 20% of observations may hit the suite ceiling; no family may exceed 40% of the corpus; and no exact setup may exceed 25%. These gates prevent a small number of repeatedly benchmarked legacy setups from manufacturing a calibration pass. Coding and reasoning v2 retain their declared gates.

Coverage priorities are recent-model-first. Qwen3.5 9B, Gemma 4 E4B, Ministral 3 3B, and Qwen3 8B are the reviewed repeat anchors. Smaller and larger current-generation sizes expand setup diversity only after exact artifact, memory-fit, runtime, and protocol canaries pass. Qwen3.6 is an explicit freshness target but remains blocked where those gates or suitable memory are missing. Qwen2.5 remains historical control evidence and can still answer direct user demand; it does not lead zero-demand calibration work.

The audit never curves, caps, or compresses a score. Raw attainment remains inspectable. If the distribution saturates, InferGrade must expand or replace the benchmark and issue a new protocol revision.

The compatibility identifier `local_assistant_score_v4` remains in result bundles so already-produced evidence stays in one comparable cohort. It is an internal score-contract identifier, not the public protocol name.

Below a gate InferGrade preserves:

- the component result;
- its observed weighted score;
- the coverage fraction;
- missing benchmark IDs;
- and the next useful benchmark action.

But `capability_score` remains `null`. This prevents a ceiling result on a tiny diagnostic from appearing as a broad capability claim.

The legacy numeric `capability_confidence` also remains `null` until the score clears the same coverage gate. Evidence state, component results, and coverage still show that the benchmark itself completed.

Missing coverage does not reduce the observed score. Coverage and capability remain separate signals so users can distinguish “weak model” from “not enough evidence.”

## Per-task performance

When a backend reports generation timings, capability results carry a separate `task_performance` summary:

- median and p95 time per task;
- median and p95 output tokens per task;
- median and p95 decode tokens per second;
- total input and output tokens;
- timing and token coverage fractions;
- measurement source.

Runner does not infer decode throughput from end-to-end task latency, and it does not invent token counts for backends that omit them. `measurement_status: not_reported_by_backend` is a valid result.

## Claim boundary

These indexes help choose a local model, quant, runtime, and hardware setup for a named task surface. They do not establish universal model quality, production readiness, safety, expert reasoning, repository-editing ability, or leaderboard-grade standing. A suite ceiling describes the benchmark's inability to distinguish further performance; it is not evidence of model perfection.
