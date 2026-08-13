# Capability Benchmarks

Capability container defaults use the canonical public `ghcr.io/bfogels/<image>:<runner-version>` release reference. Source checkouts build that exact reference; installed runners pull it. Capability artifacts record the resolved local image ID and any repository digest so the actual scorer can be audited after the run. Source developers may override an image explicitly with `INFERGRADE_IFEVAL_IMAGE`, `INFERGRADE_EVALPLUS_IMAGE`, `INFERGRADE_MMLU_PRO_IMAGE`, `INFERGRADE_GPQA_IMAGE`, or `INFERGRADE_BFCL_IMAGE`; an unversioned `:local` image is never selected implicitly for evidence collection.

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
  - Output-shape policy: isolated empty visible responses remain strict wrong answers and are counted as model-output failures. A run with a majority of empty visible responses is quarantined as a model/template/runtime protocol failure instead of becoming a capability score. Token-budget exhaustion is recorded for diagnosis but does not invalidate IFEval on its own.

- `Multi-turn chat memory`
  - Why: low-cost assistant decision signal for retaining facts, corrections, and output constraints across a short transcript.
  - InferGrade role: zero-weight diagnostic after its five-case fixture empirically saturated; it no longer contributes headline assistant score weight.

- `MMLU-Pro reference`
  - Why: recognized broad knowledge and reasoning benchmark with harder, more robust multiple-choice questions than legacy MMLU.
  - InferGrade role: explicit sampled assistant reference lane with category breakdowns; useful for stronger evidence, but not a quick default or leaderboard claim.

- `Reasoning exact answer`
  - Why: gives local users a compact reasoning decision signal without shipping restricted datasets or making reference-suite claims.
  - InferGrade role: native local-friendly exact-answer reasoning check for thin local sample evidence.

- `GPQA Diamond reference`
  - Why: harder expert-level multiple-choice evidence can add headroom where smaller reasoning checks cluster.
  - InferGrade role: deliberately selected diagnostic reference evidence. It has zero Capability protocol v3.1 weight until cross-family distribution, duration, malformed-output, and repeatability audits justify promotion.

- `BFCL V4 local tool-use reference`
  - Why: structured function selection, arguments, parallel calls, and relevance abstention cover an assistant capability that instruction-following accuracy does not.
  - InferGrade role: zero-weight, intentionally selected reference diagnostic over a hash-ranked 110-case subset balanced across 11 BFCL V4 static and live single-turn categories. The upstream commit and every downloaded source file digest are pinned. Canary and standard samples round-robin across categories instead of taking a narrow prefix.
  - Claim boundary: InferGrade uses a strict runtime-neutral JSON call prompt and local deterministic scorer. The result is not an official BFCL V4 leaderboard score, does not prove native runtime function calling, and does not measure BFCL multi-turn, memory, web-search, or stateful agentic capability. Those require separately identified protocols.

- `Stateful tool-loop diagnostic`
  - Why: separate generations with executed intermediate state test opaque-token chaining, conditional action, guarded abstention, and idempotent completion that a single-turn call cannot measure.
  - InferGrade role: zero-weight synthetic diagnostic over 24 pinned trajectories and eight domains, with deterministic side-effect-free local simulator results between turns.
  - Claim boundary: the result is not native function-calling proof, real external-tool execution, long-horizon autonomy, BFCL/GAIA conformance, or leaderboard evidence. Cross-family discrimination and headroom are unproven.

- `Context retrieval reference`
  - Why: local users need to know whether a setup can retrieve a pinned fact at the prompt lengths they intend to use.
  - InferGrade role: deterministic exact-key retrieval at nominal 4K, 8K, and 16K buckets, with observed task token counts. It does not claim broad long-context reasoning or maximum-context support and has zero headline score weight.

### Agentic Coding

- `Coding static repair`
  - Why: gives local users a quick coding decision lane before sandboxed code execution is safe enough for broader default use.
  - InferGrade role: first native local-friendly coding decision check. It scores deterministic static constraints and preserves malformed output or generation failures explicitly.

- `EvalPlus HumanEval+`
  - Why: high-signal code generation benchmark, much more rigorous than the original HumanEval, and explicitly designed for safe evaluation workflows.
  - InferGrade role: first executable coding reference lane for `agentic_coding`. It preserves generated code, EvalPlus revision, sample policy, pass@1 base/plus scoring, raw outputs, scoring outputs, and task-level execution failure classes. It is not LiveCodeBench, SWE-bench, repo-edit proof, gold evidence, or a public leaderboard claim.

- `EvalPlus MBPP+`
  - Why: expands beyond HumanEval-style tasks, uses the same container/evaluation ecosystem, and gives us a second coding signal without introducing a completely separate harness.
  - InferGrade role: executable coding breadth reference lane for `agentic_coding`, separate from HumanEval+. It preserves MBPP task ids and prompts, generated samples, EvalPlus revision, sample policy, pass@1 base/plus scoring, raw outputs, scoring outputs, and task-level execution failure classes. It is not LiveCodeBench, SWE-bench, repo-edit proof, gold evidence, broad agentic software-engineering proof, or a public leaderboard claim.

## Diagnostic and Selected Next

- `Repository edit smoke`
  - Why: deterministic miniature repo-edit tasks bridge the gap between code-generation benchmarks and SWE-style work.
  - InferGrade role: intentionally selectable zero-weight diagnostic. Its isolated scorer and pinned fixtures are implemented, but cross-family discrimination and headroom remain unproven.

The following are selected as high-value later additions and are not runnable yet:

- `LiveCodeBench`
  - Why: broad contemporary coding benchmark with multiple task modes and temporal freshness.
  - InferGrade role: coding reference suite after local sandboxing, task pinning, and cost metadata are proven.

- `SWE-bench Verified`
  - Why: highest-value software engineering benchmark in this space, but much more operationally expensive than the first-pass coding lanes.
  - InferGrade role: gold evidence first, with curated provenance and maintainer review, not a default laptop run.

- `LongBench v2`
  - Why: realistic long-context task reasoning across multiple task categories is materially broader than deterministic key retrieval.
  - InferGrade role: reasoning and assistant reference candidate after memory-fit, task-sampling, duration, recovery, and explicit judge-identity policies are proven. Source: [LongBench v2](https://arxiv.org/abs/2412.15204).

## Expansion Principle

InferGrade should move toward benchmark legitimacy comparable to serious model-analysis products without making first users wait hours for a first answer. That means every new benchmark candidate should declare:

- the use case it supports,
- whether it belongs in the smoke, decision, reference, or gold lane,
- the score dimension and planned score policy,
- local feasibility, expected wall-clock duration, and expected token volume,
- and why it is not part of the default quick path yet.

Planned candidates are roadmap metadata only. They must not be rendered or validated as runnable checks until Runner owns a reproducible harness, scoring policy, fixture/version pin, and runtime-cost story.

## Benchmark Adequacy Audit

`scripts/audit_benchmark_adequacy.py` audits the static catalog along four separate axes:

- whether every narrow claim facet is backed by a positively weighted check,
- which broader real-world priority facets have runnable or diagnostic coverage,
- which missing facets have an explicit planned benchmark rather than an unowned gap,
- and whether the surface has a refreshable lane plus any already-known headline saturation risk.

The audit deliberately reports `scoped_claim_coverage_ready` separately from `broad_surface_coverage_ready`. The current catalog covers its narrow task-scoped claim definitions, but it does not pass broad-surface coverage. Assistant now has a runnable, periodically refreshable structured tool-use diagnostic, but still lacks runnable preference and long-context task-reasoning evidence; tool use also lacks the independent cross-family observations and demonstrated headroom required by the empirical facet gate, and the memory diagnostic is already saturated. Coding lacks runnable contemporary and real-repository issue-resolution evidence. Reasoning lacks runnable long-context task reasoning. Coding and Reasoning also lack a runnable refreshable priority facet and retain known headline component ceiling risks. A known saturation risk blocks broad readiness whether the affected priority facet is headline-weighted or diagnostic-only; role separation remains visible in the report.

This is a catalog-structure audit, not empirical validation. `scripts/audit_capability_calibration.py` remains the result-corpus gate for cross-family distribution, repeats, failure quality, component ceiling rates, and score headroom. A surface needs both kinds of evidence before broader claims are credible; passing either audit never substitutes for the other.

For a claim-readiness decision, run both gates through the fail-closed join:

```bash
PYTHONPATH=python/runner-core/src python3 scripts/audit_benchmark_readiness.py /path/to/result-bundles --fail-scoped-ready
```

`scripts/audit_benchmark_readiness.py` reports separate scoped-claim and broad-surface blockers for every task surface. Scoped readiness requires the catalog's narrow facets plus an empirically diverse, non-saturated score distribution. Broad readiness additionally requires the broader priority facets, a runnable refreshable facet, and no known headline or diagnostic saturation risk. Missing or unreadable result evidence remains unready; the audit never curves, caps, or rescales raw attainment. Use `--fail-broad-ready` only for a workflow that is intentionally gating a broad-surface claim, because the current catalog is expected to fail that stronger gate.

The gap choices are grounded in the scope of the candidate benchmarks rather than their popularity. [LiveCodeBench](https://arxiv.org/abs/2403.07974) adds continuously collected coding problems and broader execution modes beyond static function-generation sets. [SWE-bench](https://arxiv.org/abs/2310.06770) uses real repository issues that can require multi-file changes. [GPQA](https://arxiv.org/abs/2311.12022) supplies a harder expert-science diagnostic, while [MMLU-Pro](https://arxiv.org/abs/2406.01574) remains the harder broad multi-domain headline component. [IFEval](https://arxiv.org/abs/2311.07911) remains a verifiable instruction-following component, not a proxy for tool use, preference quality, or long-context task reasoning.

## Optional Local Judge Boundary

InferGrade does not currently download or host a judge model. If a future benchmark requires one, the judge must be an explicit opt-in dependency with a pinned model, quant, runtime, prompt, and immutable receipt. Judge-derived outcomes must remain a separate experimental evidence dimension until calibrated against deterministic or human reference labels. Runner must never silently substitute a local judge for canonical scoring, and Hub must disclose judge identity rather than presenting the result as benchmark-native ground truth.

The detailed acceptance gates for heavier third-party lanes live in [Stronger Evidence Lane Gates](stronger_evidence_lane_gates.md).

The machine-readable catalog now also includes a benchmark legitimacy status matrix. See [Benchmark Legitimacy Program](benchmark_legitimacy_program.md) for the maturity levels and promotion gates. Every runnable check and planned candidate must declare its maturity, runnable status, fixture or dataset status, harness status, sample policy, claim boundary, and promotion blockers.

## Capability Catalog Shape

InferGrade now treats benchmark scope as:

- capability suites
- benchmark groups
- individual benchmark checks

The currently implemented first-user catalog is:

### `chat_instruction_following`

- group: `instruction_following`
  - check: `ifeval`
- group: `assistant_compositional`
  - check: `assistant_compositional_instruction_v2`
- group: `chat_memory`
  - check: `multiturn_chat_memory_v1` (diagnostic only; zero headline-score weight)
- group: `chat_memory`
  - check: `multiturn_chat_memory_v1`
- group: `reasoning_exact_answer`
  - check: `reasoning_exact_answer_v1`
- group: `broad_reasoning_knowledge`
  - check: `mmlu_pro_reference_v1`
- group: `deployment_chat`
  - check: `interactive_chat_v1`
- group: `deployment_batch`
  - check: `batch_generation_v1`
- group: `deployment_long_context`
  - check: `long_context_v1`

### `coding_code_editing`

- group: `coding_static_repair`
  - check: `coding_static_repair_v1`
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

Runner records fixture preparation, model generation, scorer execution, and total wall time separately for every selected capability benchmark under `task_performance.phase_timings`. These timings are operational evidence, not score inputs. They let Hub calibrate honest run-duration ranges and identify setup or scorer overhead without changing canonical serial generation (`server_slots=1`) or mixing accelerated throughput experiments into comparable capability results.

## Benchmark Maturity

Benchmark maturity is separate from evidence lane:

- `thin_local_sample` means a small local task set can guide setup, but cannot support reference or global claims.
- `strong_local_candidate` means the lane is useful locally but still needs broader samples, repeatability, and observed metadata before stronger claims.
- `reference_candidate` means the benchmark is promising for reference evidence but still has open harness, data, scoring, or sandbox blockers.
- `reference_runnable` means the reference lane has enough controls to run intentionally and emit artifact-backed reference evidence.
- `gold_candidate` and `gold_runnable` are reserved for high-legitimacy evidence with stronger controls and maintainer review.

Thin local samples cannot be promoted because their score is high. Promotion requires protocol controls.

Container-backed capability scorers run under `capability_container_isolation_v1`: the invoking host user rather than container root, no network, all Linux capabilities dropped, no-new-privileges, a read-only root filesystem, bounded memory and process counts, and only `/work` plus a no-exec `/tmp` writable. The exact policy is recorded beside the scorer image identity in each result. These controls reduce risk from generated code and scorer dependencies; they do not make arbitrary community benchmarks safe or automatically promote a planned executable benchmark.

## Capability Surfaces

Runner-owned capability artifacts use these surfaces:

- `local_assistant_capability`: instruction following, structured output, conversational retention, and assistant behavior.
- `local_coding_capability`: code generation, repair, structured patch output, and bounded repo-edit tasks.
- `local_reasoning_capability`: exact-answer, multiple-choice, or structured reasoning checks.
- `quant_fidelity`: quant-to-quant fidelity signals such as perplexity or controlled reference outputs.
- `deployment_fitness`: latency, throughput, memory, runtime stability, and local hardware fit.

These surfaces must remain separate. Deployment fitness is not capability quality, and quant fidelity is not a general capability score.

## Capability State Semantics

The current supported suites should report capability truthfully rather than softening failures into generic missing data:

- `scored`: the planned lane completed with a trustworthy suite score
- `partial`: only part of the planned lane scored
- `failed`: InferGrade attempted the lane, but benchmark execution failed before producing a trustworthy score
- `skipped`: capability execution was explicitly disabled
- `not_yet_benchmarked`: the slice is meaningful, but no benchmark execution has happened yet
- `not_comparable`: the run does not define a meaningful capability slice

The currently supported first-user benchmark surfaces are:

- assistant surface: `chat_instruction_following` via `ifeval` and `assistant_compositional_instruction_v2`, with `multiturn_chat_memory_v1` retained as diagnostic smoke evidence
- coding surface: `coding_code_editing` via `evalplus_humaneval` and `evalplus_mbpp`
- reasoning surface: `mmlu_pro_reference_v1` when selected intentionally as reference evidence
- quant-fidelity surface: `perplexity_reference_v1`
- deployment-fitness surface: `interactive_chat_v1`, `batch_generation_v1`, and `long_context_v1`

Those are the lanes we expect to keep locally regression-tested and operationally trustworthy first.

## Capability Run Artifact

`native_first_run` proves a local setup can execute and upload first-run evidence. A `capability_run` artifact is different: it records a benchmark protocol, evidence lane, capability surface, task fixture revisions, scorer policy, raw outputs, scoring outputs, failure states, runtime provenance, hardware provenance, duration, token counts where available, and claim boundaries.

The schema is `schemas/json/capability_run.schema.json`; the methodology is [Local Benchmark Methodology](local_benchmark_methodology.md).

The first local assistant artifact path is `multiturn_chat_memory_v1`: it emits a `capability_run.json` beside `cases.jsonl`, `predictions.jsonl`, and `summary.json`. This is a thin local sample and remains experimental decision evidence.

The memory fixture no longer contributes headline assistant-score weight. A 2026-07-14 audit of the latest 300 public result briefs found 37 scored memory runs and 35 exact suite-ceiling results across models ranging from hundreds of millions to billions of parameters. That roughly 95% ceiling rate means the fixture can still prove that a setup cleared five basic retention cases, but it cannot separate stronger models. Restoring score weight requires a new cross-model discrimination audit.

`assistant_compositional_instruction_v2` is the replacement local decision component. It runs twenty-four pinned synthetic tasks (four in canary) that combine corrections, filtering, ordering, dependency waves, interval merging, allocation, state transitions, reconciliation, and strict JSON output. Entire structured answers are scored by JSON equality; extra prose and malformed JSON score zero. The artifact separately reports semantic JSON accuracy and format-violation counts when a fenced JSON value is otherwise correct, so users can distinguish task errors from machine-readable-output failures without relaxing the headline contract. It is deliberately provisional and must pass the versioned corpus-distribution audit before stronger claims. It is not preference quality, factual knowledge, psychometric calibration, global intelligence, or leaderboard evidence.

The first v1 local calibration on 2026-07-14 used three GGUF setups on Apple M1 Pro with deterministic direct-answer generation. These 12-case results are retained as the reason to expand the fixture; they are not v2 results and cannot be compared numerically with v2:

| Setup | Strict compositional | Semantic JSON | Memory diagnostic |
| --- | ---: | ---: | ---: |
| Qwen3-0.6B Q8_0 | 0/12 | 0/12 | 1/8 constraints |
| Qwen2.5-7B-Instruct Q4_K_M | 2/12 | 7/12 | 8/8 constraints |
| Qwen3.5-9B Q4_K_M | 7/12 | 7/12 | 8/8 constraints |

The older 7B setup's remaining misses included genuine filtering, deduplication, transform, and state-update errors; five otherwise-correct answers violated the strict JSON-only contract with Markdown fences. The 9B setup retained clear headroom rather than reaching the v1 suite ceiling. A control run with thinking left enabled exhausted every Qwen3-0.6B task budget inside unfinished thinking and correctly remained failed evidence rather than becoming a zero score. The expanded v2 fixture subsequently scored Qwen3.5-9B Q4_K_M at 11/24 strict tasks (45.8%), retaining additional headroom. This remains component calibration, not full Capability protocol v3.1 calibration, because the composite also requires IFEval.

The first local coding artifact path is `coding_static_repair_v1`: it emits a `capability_run.json` beside `cases.jsonl`, `predictions.jsonl`, and `summary.json`. It checks fenced Python outputs against deterministic static constraints. It does not execute generated code, run unit tests, sandbox a repository, or support SWE-bench/LiveCodeBench-style claims.

`repository_edit_smoke_v1` is the first executable repository-edit diagnostic. It uses eight pinned miniature Python repositories spanning state/time behavior, immutable transformations, archive-path safety, rate limiting, event reconciliation, protocol parsing, permission policy, and bounded scheduling. Canary runs two tasks, standard runs six, and gold runs all eight. The model receives source files and an issue description, returns one bounded unified diff, and the scorer permits edits only to the named existing files. Hidden deterministic tests are materialized after patch application.

The scorer runs with no network, a read-only root filesystem, bounded memory and process counts, and no-new-privileges. Its root process retains only `SETUID` and `SETGID` so the generated-code subprocess can drop irreversibly to `nobody`; source and hidden tests are root-owned and read-only before generated code executes. The result records that exception as part of the sandbox policy. Dominant malformed-patch output is quarantined as a protocol mismatch, while a valid patch that fails hidden tests remains a real incorrect task.

This benchmark has zero Capability protocol v3.1 weight and is not selected by default. It becomes eligible for score-weight consideration only after a cross-family distribution audit shows adequate observations, repeatability, manageable malformed/timeout rates, and component headroom. It is not SWE-bench, LiveCodeBench, autonomous-agent, arbitrary-repository, gold, or leaderboard evidence.

`stateful_tool_loop_diagnostic_v1` is a distinct synthetic assistant diagnostic for behavior that single-turn structured-call checks cannot measure. It has twenty-four pinned cases across inventory, access control, service operations, budgeting, scheduling, data workflows, consent-aware communication, and release safety. Every eight-case tier increment spans all eight domains and mixes success, guarded-abstention, and idempotent already-complete outcomes, so even canary exercises action and no-action decisions rather than an easy success-only slice. Canary requires 19 separate model generations and gold requires 56 rather than treating a transcript as one answer. Reports preserve both domain and outcome-variant metrics so aggregate strength cannot hide systematic refusal or idempotency failures.

For each turn, Runner asks for one strict JSON call, verifies it against the current state, executes a deterministic side-effect-free local simulator result, and exposes only that executed call and result to the next generation. Success paths must carry opaque tokens, revisions, regions, channels, digests, or returned identifiers into the next operation and then close with an exact `finish` state. A canary tool result also contains an untrusted instruction string that must remain data instead of redirecting the next call. Wrong or malformed calls do not execute. The scorer reports complete-trajectory success, turn accuracy, malformed and wrong-call counts, simulator execution counts, and domain breakdowns; dominant malformed output is quarantined as a protocol mismatch.

This diagnostic has zero Capability protocol v3.1 weight and must remain separately identified from `bfcl_local_reference_v1`. It does not prove native runtime function calling, arbitrary external tools, real side effects, web access, recovery from arbitrary tool errors, long-horizon autonomy, BFCL/GAIA conformance, or leaderboard standing. Cross-family distributions, independent repeats, and ceiling audits are required before considering a harder fixture or any score-role change.

The first executable coding reference artifact path is `evalplus_humaneval`: when selected, it emits a validated `capability_run.json` beside `cases.jsonl`, `predictions.jsonl`, `samples.jsonl`, `benchmark_metadata.json`, `eval_results.json`, and `summary.json`. It preserves the pinned EvalPlus revision, sample policy, pass@1 base/plus scores, generated outputs, scoring outputs, and task-level classes such as `test_failed`, `timeout`, `malformed_output`, and `generation_failed` where available from generated outputs and EvalPlus status rows. A completion-normalization failure caused by the model remains in EvalPlus's denominator as an incorrect answer and is disclosed separately; a runtime or adapter generation failure remains missing evidence and degrades or suppresses the score. It remains experimental reference evidence, not gold evidence or a public leaderboard claim.

The first local reasoning artifact path is `reasoning_exact_answer_v1`: it emits a `capability_run.json` beside `cases.jsonl`, `predictions.jsonl`, and `summary.json`. It checks a compact synthetic exact-answer fixture set. It does not use GPQA, does not replace MMLU-Pro reference evidence, and does not support broad reasoning, expert knowledge, or gold-evidence claims.

The first sampled reasoning reference artifact path is `mmlu_pro_reference_v1`: when intentionally selected, it emits a validated `capability_run.json` beside `cases.jsonl`, `predictions.jsonl`, `benchmark_metadata.json`, and `summary.json`. It preserves the pinned dataset revision, sample policy, category breakdowns, and reference-sample claim boundaries. It remains experimental reference evidence, not gold evidence or a public leaderboard claim.

The first quant-fidelity reference artifact path is `perplexity_reference_v1`: when intentionally selected, it emits a validated `capability_run.json` beside `fidelity_raw.json` and `summary.json`. It preserves the pinned `infergrade_quantfidelity_v1` corpus revision, `infergrade_perplexity_v1` protocol parameters, perplexity, bits-per-byte where derivable, token/byte counts where available, duration, and same-family comparability key. It remains experimental reference evidence for comparing quants of the same model family/checkpoint/tokenizer/corpus/protocol only; it is not assistant, coding, reasoning, general model-quality, gold, or leaderboard evidence.

## Dogfood Evidence

The current reference-runnable stack is strong enough to dogfood the full product loop before adding new benchmark lanes. Maintainer dogfood should use [Local Evidence Dogfood](local_evidence_dogfood.md) to generate request files for a small Apple Silicon GGUF matrix, run thin local samples plus intentionally selected reference lanes, preserve provenance, and upload bundles to Hub only through token-safe pairing or upload paths.

Dogfood evidence is real local evidence from the named machine. It is not official validation, gold evidence, leaderboard-grade evidence, or a global model-quality proof. It exists to calibrate duration, token volume, memory behavior, failure modes, Hub display, and next-benchmark guidance.

## Capability Summary Artifact

Runner also emits `artifacts/capability/capability_summary.json` when local capability execution runs. This is a discoverability and import artifact, not a new benchmark lane.

The summary lists the capability artifacts produced in the bundle, keeps each surface separate, and records per-surface state, score where meaningful, evidence lane, confidence label, task count, failure count, repetition count, unsupported claim boundaries, and a cautious next benchmark action.

The summary may recommend actions such as running a missing assistant/coding/reasoning decision lane, retrying a failed or partial lane, or repeating local capability checks after all thin samples are present. It must not combine assistant, coding, reasoning, quant fidelity, and deployment fitness into a global intelligence score.

### Local Capability Scores v2 and Capability Protocol v3.1

Assistant, coding, and reasoning scores are separate, versioned task scores. A v2 score is headline-ready only when the selected surface has at least 50% of its configured benchmark weight, two scored components, two distinct score dimensions, and no component above 80% of the observed normalized weight. The Runner keeps an observed weighted score when a gate fails, but publishes the task score as `null` and names every failed gate.

Every v2 score includes configured component weights, coverage, leave-one-component-out sensitivity, dominant-component flags, and an inspectable confidence basis. That basis describes evidence coverage and sensitivity; it is not a probability, confidence interval, psychometric calibration, or global intelligence claim. Composite confidence conservatively uses the weakest evidence label on the capability surface, and consumers must not compare scores across score versions.

Capability protocol v3.1 changes the assistant mix and its meaning. IFEval carries 45% weight, the expanded compositional fixture carries 55%, and the saturated memory microcheck carries zero. Both weighted components and both dimensions must score, so protocol v3.1 requires 100% configured coverage. The value is a **benchmark-attainment index**, not a percentile, probability, IQ-like quantity, or percent of perfect general capability. `scripts/audit_capability_calibration.py --score-version local_assistant_score_v4 ...` audits only publication-ready composite scores; `--benchmark-id assistant_compositional_instruction_v2 ...` audits the component distribution separately. Neither mode alters raw scores. The compatibility identifier remains `local_assistant_score_v4` so existing evidence is not split into a false new cohort; it is not the public protocol name. Saturation requires benchmark replacement and another protocol revision.

The v3.1 headroom audit also guards campaign composition. Observation count alone is insufficient: the corpus must include eight exact model-plus-quant setups, four setups repeated across at least two distinct trusted evidence groups, and a 75% share from current or recent Runner-declared campaign targets, while preventing any exact setup from exceeding 25% of the sample. Same-source reruns remain useful repeatability evidence but cannot satisfy the independent-replication gate; missing group identity fails closed, and a claimed `evidence_group_id` counts only with `evidence_group_provenance: trusted_corpus_operator_v1`. Only aggregate group counts leave the audit. Current-model status is explicit catalog policy, not guessed from model-name strings in Hub. Historical controls remain comparable within the score version but cannot make the recent-model calibration campaign look complete by repetition.

That current/recent share and the three-band minimum do not by themselves prove the suite was challenged by a deliberately stressful model. Every surface must also include two complete observations of an explicit `headroom_challenge_eligible` campaign target, with the same exact setup independently repeated across two trusted evidence groups. Complete means every positive-weight component on that surface produced a usable component report; partial composites are counted as incomplete candidates but cannot close the challenger gate. Runner curates this role instead of inferring it from size or an observed high score, so future MoE or strong compact challengers can qualify without equating parameters with capability. The first task-scoped targets share the blocked Qwen3.6 27B setup across Assistant, Coding, and Reasoning. None can count until its artifact, fit, runtime, and relevant task protocol are qualified, and selection does not establish a frontier or leaderboard claim.

Distribution readiness also requires component-level headroom. Each weighted component needs eight score-ready observations, no more than 20% may hit that component's ceiling, and both the composite and sufficiently sampled components must retain at least ten points below their suite ceiling. The 2026-08-12 latest-300-result audit caught a failure that composite-only checks masked: `reasoning_exact_answer_v1` reached its three-case ceiling in 12 of 13 score-ready Reasoning observations even though MMLU-Pro kept the composite below its ceiling. `coding_static_repair_v1` also reached its ceiling in all four completed observations, but 38 of its 44 reports were partial, so it is presently both too thin and too fragile for a saturation conclusion. The Runner reports these facts and blocks distribution readiness; it does not curve scores or silently change component weights.

When every weighted component reaches its maximum, Runner records `suite_ceiling_reached`. Consumers should display that phrase instead of presenting the model as “100/100 perfect.” The result means the current suite cannot distinguish additional capability; the remedy is a harder or broader benchmark mix and a new protocol revision, not an arbitrary point penalty.

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
