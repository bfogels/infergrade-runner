# Stronger Evidence Lane Gates

InferGrade should add heavier third-party benchmarks deliberately. A benchmark becomes runnable only when it has a reproducible Runner harness, a clear score policy, bounded local cost, and product copy that explains what claim the result can support.

This document defines the next implementation stack after the first local-friendly decision lanes:

1. sampled MMLU-Pro reference
2. sampled GPQA reference
3. LiveCodeBench reference
4. SWE-bench Verified gold evidence

The maturity ladder and status matrix live in [Benchmark Legitimacy Program](benchmark_legitimacy_program.md) and `schemas/capability_catalog.json`. Those catalog fields are validated by tests so stronger-evidence work cannot land as undocumented prose only.

## Shared Acceptance Gates

Every new third-party evidence lane must land in stacked PRs:

1. **Catalog contract PR**
   - Add or update planned metadata only.
   - Include source, license, fixture/version pin, expected duration, token volume, and why it is not a quick default.
   - Keep the check non-runnable until the harness exists.

2. **Harness PR**
   - Use the Runner capability contract: `prepare` emits `cases.jsonl`, host generation writes `predictions.jsonl`, and `evaluate` emits `summary.json`.
   - Pin dataset revision or fixture snapshot.
   - Preserve raw scoring artifacts.
   - Never download mutable benchmark data at evaluation time without a pinned revision.
   - Provide canary/sample limits and an explicit full/reference limit.

3. **Truthfulness PR**
   - Report failed, partial, skipped, and not-comparable states distinctly.
   - Treat malformed benchmark input, scoring failure, sandbox failure, and model generation failure as structured failures.
   - Add tests that failures do not become zero scores unless the benchmark's official scoring policy says so.

4. **Hub import/UX PR**
   - Import the Runner contract.
   - Show the lane as runnable only after Runner owns the harness.
   - Explain expected time, machine load, comparability, and what claim the score can support.
   - Default to sampled/reference choices only when the runtime cost is acceptable for local users.

## Lane Order

### Phase A: MMLU-Pro Sampled Reference

MMLU-Pro is the best first heavier assistant lane because it is broad, recognized, and can be sampled for local use. It should be a reference check, not a quick default.

Status: Runner harness implemented as `mmlu_pro_reference_v1` with a pinned dataset snapshot, sampled local limits, exact answer-letter scoring, and category breakdowns.

Source candidates:

- Official code: https://github.com/TIGER-AI-Lab/MMLU-Pro
- Official dataset: https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro

Runner scope:

- Add a `capability-mmlu-pro` container. Done.
- Pin the dataset revision. Done: `54611cde22c74cca43dd78732198de6abe971398`.
- Prepare a sampled local split first, for example 100-300 questions, with full reference left as an intentional deeper path. Done for canary/standard/gold limits.
- Score exact multiple-choice accuracy. Done.
- Emit subject/category breakdowns. Done.
- Emit a validated `capability_run.json` and include it in `capability_summary.json`. Done.

Acceptance:

- `mmlu_pro_reference_v1` moves from planned to runnable only after the container can run offline against a pinned snapshot. Done.
- `summary.json` includes `accuracy`, `correct_count`, `total_count`, and per-category metrics.
- `capability_run.json` preserves dataset revision, sample policy, raw outputs, scoring outputs, task states, category metrics, and reference-sample claim boundaries.
- Local canary test uses tiny fixtures and does not require network.
- Full Runner test suite passes without pulling the real dataset.

Non-goals:

- No leaderboard claim from the sampled lane.
- No default quick-run inclusion.

### Phase A2: EvalPlus HumanEval+ Coding Reference

HumanEval+ is the first executable coding reference lane because it has a compact local shape, deterministic unit-test scoring, and a recognized EvalPlus harness without broad agentic repo-edit scope.

Status: Runner harness implemented as `evalplus_humaneval` with the EvalPlus upstream revision pinned in the container image, canary/full local sample limits, pass@1 base/plus scoring, and containerized generated-code execution.

Source:

- EvalPlus upstream: https://github.com/evalplus/evalplus
- Pinned revision: `26d6d00bb1fd0fa37f39c99d5290da67891d1c5e`

Runner scope:

- Keep generated-code execution inside the EvalPlus container path.
- Emit a validated `capability_run.json` and include it in `capability_summary.json`.
- Preserve `predictions.jsonl`, `samples.jsonl`, `eval_results.json`, `summary.json`, `cases.jsonl`, and `benchmark_metadata.json`.
- Preserve task-level `generation_failed`, `malformed_output`, `test_failed`, and `timeout` classes where available from generated outputs and EvalPlus status rows.
- Keep claim boundaries clear: HumanEval+ is executable coding reference evidence, not LiveCodeBench, SWE-bench, repo-edit proof, gold evidence, or public leaderboard evidence.

Acceptance:

- `evalplus_humaneval` is reference evidence with `reference_sample` confidence.
- It is not promoted to gold evidence.
- MBPP+ is a separate follow-up coding breadth reference lane with its own artifact, catalog, and review gates.
- Real dogfood runs still need to calibrate expected duration, token volume, and degraded behavior.

### Phase A3: EvalPlus MBPP+ Coding Breadth Reference

MBPP+ is the second executable coding reference lane. It broadens coding coverage beyond HumanEval+-style tasks while keeping the same pinned EvalPlus revision, containerized execution boundary, and pass@1 base/plus scoring semantics.

Status: Runner harness implemented as `evalplus_mbpp` with the EvalPlus upstream revision pinned in the container image, MBPP input serialization, canary/full local sample limits, pass@1 base/plus scoring, and containerized generated-code execution.

Source:

- EvalPlus upstream: https://github.com/evalplus/evalplus
- Pinned revision: `26d6d00bb1fd0fa37f39c99d5290da67891d1c5e`

Runner scope:

- Keep generated-code execution inside the EvalPlus container path.
- Preserve MBPP dataset semantics, including serialized base/plus inputs for EvalPlus JSONL overrides.
- Emit a validated `capability_run.json` and include it in `capability_summary.json` under `local_coding_capability` without flattening it into HumanEval+.
- Preserve `predictions.jsonl`, `samples.jsonl`, `eval_results.json`, `summary.json`, `cases.jsonl`, `benchmark_metadata.json`, and `mbpp_override.jsonl`.
- Preserve task-level `generation_failed`, `malformed_output`, `test_failed`, and `timeout` classes where available from generated outputs and EvalPlus status rows.
- Keep claim boundaries clear: MBPP+ is executable coding breadth reference evidence, not LiveCodeBench, SWE-bench, repo-edit proof, gold evidence, broad agentic software-engineering proof, or public leaderboard evidence.

Acceptance:

- `evalplus_mbpp` is reference evidence with `reference_sample` confidence.
- It is not promoted to gold evidence.
- HumanEval+ and MBPP+ remain separate catalog checks, artifact protocol entries, summary artifact pointers, and Hub-facing evidence rows.
- Real dogfood runs still need to calibrate expected duration, token volume, and degraded behavior.

### Phase B: GPQA Sampled Reference

GPQA is harder and more differentiating, but it should reuse the multiple-choice harness shape from MMLU-Pro.

Status: planned and explicitly access-gated. The official dataset card requires users to accept access conditions, so Runner must not ship real GPQA examples or silently download the dataset before the user has access and the harness has redaction-safe artifact handling.

Source candidates:

- Official code: https://github.com/idavidrein/gpqa
- Official dataset card: https://huggingface.co/datasets/Idavidrein/gpqa

Runner scope:

- Keep `gpqa_reference_v1` non-runnable until dataset access, leakage controls, and local snapshot pinning are implemented.
- Generalize shared multiple-choice scoring helpers after MMLU-Pro lands.
- Add `capability-gpqa` container or a shared `capability-mcq` container if the abstraction is clean.
- Pin the dataset revision only after the access flow is defined.
- Start with synthetic shape-only fixtures for tests; do not commit or log real GPQA questions.
- Start with a local sampled reference lane only after explicit user consent and local dataset availability are proven.

Acceptance:

- Catalog metadata marks GPQA as access-gated and non-runnable.
- Exact answer accuracy is reported with question count and category metadata where available.
- The Hub explains that GPQA is a hard reasoning reference signal, not a first-run confidence shortcut.
- Generation failures remain separate from wrong answers.

### Phase C: LiveCodeBench Reference

LiveCodeBench is useful, but execution safety and task-window pinning matter more than speed of implementation.

Source candidate:

- Official code: https://github.com/LiveCodeBench/LiveCodeBench

Runner scope:

- Pin task window and upstream version.
- Run generated code in a constrained sandbox.
- Store task metadata, generated code, pass/fail, timeout, and error class.
- Start with generation/pass@1 tasks before broader agentic modes.

Acceptance:

- Sandbox limits are explicit and tested.
- Timeouts and runtime errors are structured benchmark failures or task failures according to the score policy.
- The Hub warns that it is a heavier reference lane.

### Phase D: SWE-bench Verified Gold

SWE-bench Verified should begin as gold evidence with curated provenance and maintainer review, not as a general laptop default.

Catalog id: `swebench_verified_gold_v1`.

Source candidates:

- Official dataset: https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified
- Release note: https://openai.com/index/introducing-swe-bench-verified/

Runner scope:

- Treat it as a gold lane candidate until runtime, dependency, and sandboxing costs are understood.
- Require pinned task IDs and environment preparation metadata.
- Emit patch artifacts and task-resolution metrics.

Acceptance:

- No default local laptop preset includes this lane.
- Result metadata distinguishes maintainer-reviewed gold evidence from self-run local evidence.
- The Hub explains why this is gold evidence and why most users should not start here.

## Product Copy Rule

Use plain human questions for benchmark cards:

- MMLU-Pro: "Does this model answer broad, harder knowledge and reasoning questions?"
- GPQA: "Does this model handle difficult expert-level reasoning questions?"
- LiveCodeBench: "Does this model solve contemporary coding problems under execution tests?"
- SWE-bench Verified: "Can this setup resolve real repository issues?"

## Third-Party Dependency Rule

Third-party tools are allowed when they are the benchmark's official or de facto trusted implementation, but every import must be pinned and reviewed. If the official harness is too heavy or unsafe, InferGrade should wrap a pinned fixture subset first rather than exposing an unstable broad run.
