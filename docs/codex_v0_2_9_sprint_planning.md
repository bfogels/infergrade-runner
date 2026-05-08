# Codex v0.2.9 Sprint Planning

## Current Branch State

- Runner `origin/main` and `origin/develop`: `3af9c52`, v0.2.8 release merged and branches in parity.
- Runner open PRs at sprint start: none.
- Working branch: `codex/runner-v029-coding-lane`.
- Worktree: `/Users/brianfogelson/Desktop/Code/infergrade/.worktrees/runner-v029-coding-lane`.
- Hub state checked at sprint start: open PR #213 (`codex/hub-v3-route-state-20260508` -> `main`); Hub `develop` is behind current Hub `main`, so this slice avoids Hub changes.

## Release Goal

Add the first small coding decision lane without requiring unsafe local code execution or broad third-party benchmark suites.

Target user promise:

> Runner can produce a validated, artifact-backed local coding capability result that is clearly separate from assistant, deployment, and first-run smoke evidence.

## Planned PRs

- Coding lane PR: add a pinned native coding static-repair fixture set, deterministic static scoring, catalog metadata, `capability_run.json` emission, positive and failure/partial tests, and honest docs.
- Release PR: promote the reviewed coding lane from `develop` to `main` and bump version to `0.2.9` only in the release branch.

## Implementation Notes

- The first lane should use `surface=local_coding_capability`, `lane=decision`, `grade=thin_local_sample`, `confidence_label=thin_local_sample`, and `experimental=true`.
- The scorer should be deterministic static checks over generated text, not unit-test execution.
- Malformed or missing required output should remain a scored task failure only where the scoring policy explicitly treats static constraint misses as task-level score failures.
- Generation/runtime failures should remain failed task rows, not zero-score rows.
- Partial generation failures should produce a partial artifact and execution state.
- No Docker/Podman requirement is added for this default native coding microcheck.

## Reviewer Checklist

- No local dollar-cost estimate, adaptive head-to-head testing, public leaderboard mechanics, or global coding score claim.
- `gold` terminology is used only as an evidence lane, not as `gold/curated`.
- The coding lane declares fixture/task versions, scoring policy, scorer type, evidence lane, surface, and claim boundary.
- Unsafe arbitrary code execution is not introduced.
- Failed, partial, malformed, skipped, not-yet-benchmarked, and not-comparable states remain distinct.
- Thin local sample copy cannot be mistaken for SWE-bench, LiveCodeBench, or public leaderboard evidence.
- No Tauri/keychain/browser dependency enters Runner engine or Python core.

## Validation Plan

Focused validation:

```bash
python3 -m unittest python/runner-core/tests/test_capabilities.py python/runner-core/tests/test_benchmark_catalog.py python/runner-core/tests/test_capability_contract.py
python3 -m json.tool schemas/capability_catalog.json >/tmp/capability_catalog.json.check
python3 -m json.tool schemas/json/capability_run.schema.json >/tmp/capability_run.schema.json.check
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
gitleaks detect --source=. --redact --no-banner --exit-code 0
```

Broader release validation will be selected after the feature PR lands in `develop`.

## Evidence Honesty Notes

- v0.2.9 is a thin local coding decision lane, not a broad coding benchmark suite.
- It does not run generated code, execute tests, sandbox repositories, or claim SWE-bench/LiveCodeBench equivalence.
- It records deterministic static constraints and raw outputs so the artifact remains useful without Hub.
- Coding capability, assistant capability, quant fidelity, deployment fitness, and native first-run smoke remain separate evidence surfaces.

## Release Criteria

- A local native coding check can emit a validated `capability_run.json` artifact.
- The artifact is `local_coding_capability` decision evidence with thin-local-sample confidence and explicit claim boundaries.
- Tests cover passing, failed-generation, and partial-generation paths.
- Catalog/docs explain what the lane measures and what it does not measure.
- The feature PR and release PR both receive reviewer-agent passes before merge.

## Current Blockers

- None for the static native coding microcheck.
- Broader coding lanes that execute generated code remain blocked on explicit sandbox design and task-window pinning.

## Coding Lane PR Local Evidence

Branch: `codex/runner-v029-coding-lane`
PR: pending

Implemented:

- Added `coding_static_repair_v1`, a native local coding decision check with three pinned fenced-Python static repair fixtures.
- Added deterministic static scoring with explicit `malformed_output` and `generation_failed` task error classes.
- Generalized native `capability_run.json` artifact emission for assistant and coding native checks while preserving the assistant fixture revision.
- Added catalog metadata for the `local_coding_capability` decision lane and `coding_static_constraints_v1` score policy.
- Documented that this lane is a thin local sample and does not execute generated code, run unit tests, sandbox repositories, or support SWE-bench/LiveCodeBench claims.

Validation passed locally:

```bash
python3 -m unittest python/runner-core/tests/test_capabilities.py python/runner-core/tests/test_benchmark_catalog.py python/runner-core/tests/test_capability_contract.py
python3 -m unittest python/runner-core/tests/test_request_resolution.py python/runner-core/tests/test_runner.py python/runner-core/tests/test_end_to_end_proof_path.py
python3 -m json.tool schemas/capability_catalog.json >/tmp/capability_catalog.json.check
python3 -m json.tool schemas/json/capability_run.schema.json >/tmp/capability_run.schema.json.check
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
gitleaks detect --source=. --redact --no-banner --exit-code 0
```

Known limits:

- The v0.2.9 coding lane scores static output constraints only.
- It does not provide pass@1 execution, compile/run results, unit-test results, repository patch application, sandbox proof, or broad coding benchmark coverage.

Reviewer findings:

- P1: static scoring initially checked the full response rather than the fenced Python output. Fixed by requiring one closed Python fence and scoring only its captured code block.
- P2: the initial fence detector accepted unclosed fences. Fixed with closed-fence extraction and regression coverage.
- Re-review P1: multiple closed Python fences were accepted as one scored blob. Fixed by enumerating fenced blocks, requiring exactly one Python block, and rejecting non-whitespace outside it.
