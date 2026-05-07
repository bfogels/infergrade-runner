# Codex v0.2.7 Sprint Planning

## Current Branch State

- Runner `origin/main` and `origin/develop`: `0bc8a58`, v0.2.6 release merged.
- Working branch: `codex/runner-v027-capability-contract`.
- Open Runner PRs at planning start: none.
- Hub was checked earlier in this train before Runner release work; this slice does not touch Hub.

## Release Goal

Define the local capability evidence contract before adding broader benchmark lanes. v0.2.7 should make it harder for thin local benchmark samples, first-run smoke, deployment telemetry, and future gold evidence to be confused with each other.

## Planned PRs

- Contract PR: add `capability_run` artifact schema, semantic validation helpers, negative-state tests, capability surfaces, and benchmark methodology docs.
- Optional follow-up PR: wire CLI artifact export if it can be done narrowly without changing benchmark execution behavior.

## Evidence Honesty Notes

- Evidence lanes are `smoke`, `decision`, `reference`, and `gold`.
- `gold/curated` and `curated/gold` are not valid lane names.
- `native_first_run` remains separate from `capability_run`.
- v0.2.7 does not add public leaderboard mechanics, adaptive head-to-head testing, local dollar-cost estimation, or broad benchmark execution.
- Existing compatibility breadth labels such as `canary`, `standard`, and `gold` remain legacy selection terms, not the user-facing evidence-lane model.

## Release Criteria

- `capability_run` artifact schema is included in the Runner contract bundle.
- Validation preserves `scored`, `partial`, `failed`, `skipped`, `not_yet_benchmarked`, and `not_comparable` as distinct states.
- Catalog metadata declares the five capability surfaces.
- Benchmark docs use `gold` terminology consistently.
- Local validation passes for the new contract tests and existing benchmark catalog tests.

## Validation Evidence

- `python3 -m unittest python/runner-core/tests/test_capability_contract.py python/runner-core/tests/test_benchmark_catalog.py` passed: 26 tests after reviewer fixes.
- `python3 -m unittest python/runner-core/tests/test_contracts.py python/runner-core/tests/test_capabilities.py python/runner-core/tests/test_request_resolution.py python/runner-core/tests/test_runner.py` passed: 34 tests.
- `python3 -m json.tool` passed for `schemas/capability_catalog.json`, `schemas/json/capability_run.schema.json`, and `schemas/contract_manifest.json`.
- `python3 ./scripts/sync_versions.py --check` passed.
- `python3 ./scripts/check_versions.py` passed.
- `git diff --check` passed.
- `gitleaks detect --source=. --redact --no-banner --exit-code 0` passed.

## Reviewer Findings

- Reviewer P1: exported JSON schema allowed scored/failed artifacts that the semantic validator rejected. Addressed by adding JSON Schema conditionals for scored and failed/skipped/not-comparable score semantics plus failed task `error_class`.
- Reviewer P1: scorer metadata was documented as required but not required by schema or semantic validation. Addressed by requiring `protocol.scorer_type` and scored task scorer metadata.

## Known Limits

- This slice defines the artifact contract and validation semantics. It does not make new assistant, coding, reasoning, or quant-fidelity lanes runnable.
- `result_record.schema.json` remains the product-facing normalized result record. `capability_run.schema.json` is the local artifact contract.
- Hub import/display support remains a later low-risk follow-up.

## Next Actions

1. Finish the contract/docs patch.
2. Run focused validation.
3. Open a feature PR into `develop`.
4. Request reviewer pass.
5. Address findings, land to `develop`, then decide whether v0.2.7 needs a second feature PR before release.
