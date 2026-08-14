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

Benchmark representativeness is a separate gate from score distribution. `scripts/audit_benchmark_adequacy.py` verifies that narrow claim facets map to weighted checks, exposes broader priority facets covered only by diagnostics or planned candidates, and requires an explicit freshness path. Its catalog result does not prove empirical discrimination. Conversely, a diverse score distribution does not prove the mix represents tool use, long-context work, repository editing, or other omitted real-world facets. `scripts/audit_benchmark_readiness.py` therefore requires every broader priority facet to have at least one completed supporting check across sixteen observations, three model families, two parameter bands, and two independently replicated exact setups, while retaining at least ten points of observed headroom. Literal suite-ceiling frequency must remain at or below 20%, and its 95% Wilson upper confidence bound must also clear that limit; sixteen zero-hit observations are the smallest cohort that can do so. A different adequate check may satisfy the same facet; counts are never pooled across inadequate checks. Scored standalone capability-run artifacts may establish their own declared facet without entering composite-score calibration, but only when each run meets that check's catalog-declared `minimum_task_count`. Undersized observations remain visible as insufficient evidence instead of being mislabeled unobserved. Standalone fixture revisions and composite score versions remain separate evidence cohorts; one cohort must independently clear every threshold, and duplicate views inside a cohort are conservatively collapsed. Broader surface claims require structural coverage, composite corpus headroom, and this per-facet evidence gate together.

A `periodically_refreshed_snapshot` label no longer counts as freshness by itself. Every runnable refreshable check must pin the content release, its release date, and a maximum content age; `audit_benchmark_adequacy.py --as-of-date YYYY-MM-DD` reports the age and fails the freshness facet once that budget expires. Repository activity or a newly pinned commit cannot make old question material fresh. The [BFCL V4](https://github.com/ShishirPatil/gorilla/blob/main/berkeley-function-call-leaderboard/CHANGELOG.md)-derived local subset therefore remains runnable diagnostic evidence but no longer satisfies Assistant freshness after its one-year content-age window. Reasoning now records [LiveBench](https://livebench.ai/) as a research candidate rather than an executable lane: its 2026-06-25 public Reasoning result reached 91.7%, leaving 8.3 points to the suite ceiling and missing InferGrade's ten-point headroom policy. Any adoption needs a harder, bounded, release-pinned local mix plus the same cross-family, challenger, replication, and slice audits; refreshability alone is not enough.

Declared tier sampling is also insufficient by itself. `scripts/audit_benchmark_tiers.py --fail-invalid` materializes every native fixture and checks that canary, standard, and gold selections contain the catalog-required categories, structural tiers, tool outcomes, context lengths, and answer-key positions with explicit per-value case floors. It also rejects undersized fixtures and duplicate or missing task identities. This prevents a correctly labeled full fixture from silently producing a narrow positional shortcut. Container-owned datasets remain runtime-verified, and passing structural coverage does not establish empirical difficulty, contamination resistance, or population representativeness.

## Coverage gate

Capability protocol v3.1 needs all declared benchmark weight (`1.00`), at least two scored components, at least two score dimensions, and `standard` or deeper sample depth before an individual aggregate can publish. A canary can guide setup and expose failures, but it cannot publish the index even if all sampled cases pass.

Corpus-level calibration is separate for Assistant, Coding, and Reasoning. Each score family remains provisional until its own cohort has at least 20 observations across five families, three parameter bands, and eight exact model-plus-quant setups with six distinct values; at least four setups must have repeats from two or more distinct trusted evidence groups; at least 75% of observations must come from Runner-declared current or recent campaign targets; no more than 20% may hit that task suite's ceiling; no family may exceed 40% of that task cohort; and no exact setup may exceed 25%. A plain rerun still counts as repeatability evidence, but it does not count as independent evidence when `evidence_group_id` is missing or unchanged. The group identifier counts only when the corpus operator also assigns `evidence_group_provenance: trusted_corpus_operator_v1`; a self-asserted identifier fails closed, and audit artifacts expose only aggregate group counts. Coding and Reasoning never borrow Assistant observations or readiness. These are distribution-readiness gates, not score transformations or claims that the benchmark mix is psychometrically calibrated.

The same audit now inspects every non-zero-weight component inside score-ready composites. A component needs at least eight observations spanning three model families and two parameter bands before its ceiling distribution can be judged, no more than 20% may reach its own suite ceiling, and both the composite and every sufficiently representative component must retain at least ten points of observed headroom. A 95% Wilson upper bound is reported for each literal ceiling rate; if the point estimate is acceptable but the upper bound still crosses 20%, the audit reports insufficient statistical evidence rather than saturation. Insufficient component sample, breadth, or ceiling-rate confidence blocks distribution readiness; once those minimums exist, an excessive ceiling rate or less than ten points of headroom blocks readiness even when a harder companion benchmark keeps the weighted composite below 100. This prevents one repeatedly tested family or size from manufacturing apparent calibration, and prevents a harder component from hiding a saturated microcheck. Wilson bounds are a conservative screening guard, not proof that observations are independent; the separate trusted evidence-group and setup-repeat gates remain authoritative for provenance.

Generic diversity can still miss the model most likely to expose a shallow suite. Each surface therefore also requires two score-ready observations of an explicit Runner-curated headroom-challenge setup, including one exact setup repeated across two trusted evidence groups. A challenge observation counts only when it contains completed reports for every positive-weight component on that surface; a partial composite remains visible as incomplete and cannot satisfy the gate. Challenge membership is declared on a current or recent campaign target; it is not inferred from parameter count, score, or model-name strings. The initial Assistant, Coding, and Reasoning targets share the gated Qwen3.6 27B setup but keep task-specific benchmark scope, so artifact, memory-fit, runtime, and each task protocol must be qualified before observations can count. This role means only that the setup was selected to stress the suite. It is not a frontier-model or general-capability claim.

The 2026-08-12 audit of the latest 300 public result briefs found no composite score at or above 90 benchmark points. Assistant retained 19 points of IFEval headroom and 54 points of compositional-fixture headroom. Coding's EvalPlus HumanEval+ and MBPP+ components retained about 20 and 24 points respectively, while the static-repair microcheck had only four completed observations, all at its ceiling, among 44 reports dominated by partial results. Reasoning's MMLU-Pro component retained 40 points of headroom, but the three-case exact-answer component reached its ceiling in 12 of 13 score-ready reasoning observations. The reasoning component therefore blocks distribution readiness; the coding microcheck remains insufficiently calibrated and is a replacement candidate. `reasoning_constraint_stress_v1` is the zero-weight diagnostic path for collecting broader exact-answer discrimination evidence across six categories before any successor score proposal. Neither finding nor the new diagnostic changes a published score in place. Demotion, replacement, or changed weight requires a new score version.

Coverage priorities are recent-model-first. Qwen3.5 9B, Gemma 4 E4B, Ministral 3 3B, and Qwen3 8B are the reviewed repeat anchors. The explicit Qwen3.5 coding campaign also collects the zero-weight repository-edit diagnostic, and its reasoning campaign collects both the zero-weight GPQA Diamond and reasoning-constraint-stress diagnostics. These harder diagnostics begin collecting the distribution evidence needed before any later cross-family score-mix proposal; they do not alter the current coding or reasoning score, bypass their promotion blockers, or become default suites. Smaller and larger current-generation sizes expand setup diversity only after exact artifact, memory-fit, runtime, and protocol canaries pass. Qwen3.6 is an explicit freshness target but remains blocked where those gates or suitable memory are missing. Qwen2.5 remains historical control evidence and can still answer direct user demand; it does not lead zero-demand calibration work.

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
