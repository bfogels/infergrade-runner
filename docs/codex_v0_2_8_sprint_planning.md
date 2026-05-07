# Codex v0.2.8 Sprint Planning

## Current Branch State

- Runner `origin/main` and `origin/develop`: `9ed70b5`, v0.2.7 release merged and branches in parity.
- Working branch: `codex/runner-v028-assistant-lane`.
- Initial slice: make the existing native multi-turn assistant decision check emit the v0.2.7 `capability_run` artifact.

## Release Goal

Turn the contract from v0.2.7 into a small, honest assistant decision artifact without broadening the benchmark suite. The first v0.2.8 feature should make a local user’s assistant-lane result reproducible and artifact-backed even before Hub display work exists.

## Planned PRs

- Assistant artifact PR: emit `capability_run.json` for `multiturn_chat_memory_v1`, validate it with the semantic contract helper, and preserve raw outputs plus scoring outputs.
- Follow-up only if low risk: CLI command/copy that points users to the artifact path.

## Evidence Honesty Notes

- This slice uses the existing native multi-turn memory/constraint fixture set as a thin local sample.
- The artifact remains `experimental` and `thin_local_sample`.
- It does not create a global assistant score, public leaderboard claim, subjective judge-model score, local dollar-cost estimate, or adaptive model comparison.
- IFEval remains a separate benchmark path; this PR does not claim to make IFEval native or newly runnable.
- Hub display remains out of scope unless it becomes clearly low-risk.

## Validation Evidence

- `python3 -m unittest python/runner-core/tests/test_capabilities.py python/runner-core/tests/test_capability_contract.py python/runner-core/tests/test_benchmark_catalog.py` passed: 44 tests after reviewer fixes.
- `python3 -m unittest python/runner-core/tests/test_runner.py python/runner-core/tests/test_request_resolution.py` passed: 13 tests.
- `python3 -m json.tool schemas/json/capability_run.schema.json >/tmp/capability_run.schema.json.check` passed.
- `python3 ./scripts/sync_versions.py --check` passed.
- `python3 ./scripts/check_versions.py` passed.
- `git diff --check` passed.
- `gitleaks detect --source=. --redact --no-banner --exit-code 0` passed.

## Reviewer Findings

- Reviewer P1: mixed generation failures could emit `summary.state=scored` while failed task rows existed. Addressed by marking partial generation failures as partial in benchmark summary, execution status, and `capability_run` artifact state.
- Reviewer P1: failed artifacts used success-shaped supported claims. Addressed by making supported claims state-aware for scored, partial, failed, and not-yet-scored artifacts.

## Known Limits

- The artifact records duration/token fields as null until the adapter supplies objective counts and timings.
- The hardware block points to the run-bundle environment rather than duplicating environment capture inside the capability helper.
- This is the assistant decision-lane artifact foundation, not the full v0.2.8 release by itself unless quality or time says to cut a narrow release.

## Next Actions

1. Emit and validate `capability_run.json` for the native assistant fixture.
2. Add positive and failed-generation tests.
3. Run focused validation.
4. Open a reviewed PR into `develop`.
