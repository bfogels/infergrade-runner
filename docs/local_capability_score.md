# Local Capability Score Contract

InferGrade reports task-scoped local capability scores, not a global intelligence score. Deployment speed, latency, memory, model size, cost, and quant fidelity remain separate decision axes.

## Score families

The Runner currently owns three versioned score families:

| Score | Version | Intended question |
| --- | --- | --- |
| Local assistant score | `local_assistant_score_v1` | How well did this setup perform on the pinned assistant benchmark mix? |
| Local coding score | `local_coding_score_v1` | How well did this setup perform on the pinned coding benchmark mix? |
| Local reasoning score | `local_reasoning_score_v1` | How well did this setup perform on the pinned reasoning benchmark mix? |

Scores use a `0..1` contract value and may be displayed as `0..100`. Comparisons are valid only within the same score version and surface.

## Version 1 benchmark weights

Weights live in `schemas/capability_catalog.json` as `primary_score_weight` values. They sum to one within each scored surface.

- Assistant: IFEval `0.75`; multi-turn chat memory `0.25`.
- Coding: EvalPlus HumanEval+ `0.55`; EvalPlus MBPP+ `0.30`; static repair `0.15`.
- Reasoning: MMLU-Pro reference `0.80`; exact-answer decision sample `0.20`.

The weights deliberately keep tiny synthetic checks from carrying the same headline influence as broader decision or reference benchmarks. Changing a weight or benchmark mix requires a new score version.

## Coverage gate

A surface needs at least `0.50` of its declared benchmark weight before the aggregate becomes headline-ready. Below that threshold InferGrade preserves:

- the component result;
- its observed weighted score;
- the coverage fraction;
- missing benchmark IDs;
- and the next useful benchmark action.

But `capability_score` remains `null`. This prevents a perfect result on a three- or five-case microcheck from appearing as a broad `100/100` capability claim.

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

These scores help choose a local model, quant, runtime, and hardware setup for a named task surface. They do not establish universal model quality, production readiness, safety, expert reasoning, repository-editing ability, or leaderboard-grade standing.
