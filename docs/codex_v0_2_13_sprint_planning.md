# Codex v0.2.13 Sprint Planning

## Current Branch State

- Runner `origin/main`: v0.2.12 hardening release.
- Runner `origin/develop`: post-release sync merge ahead of `main`.
- Runner open PRs at sprint start: none observed.
- Working branch: `codex/runner-benchmark-legitimacy`.
- Worktree: `/Users/brianfogelson/Desktop/Code/infergrade/.worktrees/runner-benchmark-legitimacy`.
- Hub state checked at sprint start: Hub `develop` is one commit ahead of `main` with separate UI work, and draft PR #222 is open. This release avoids Hub changes.

## Release Goal

Make benchmark legitimacy explicit and enforceable before adding broader reference or gold benchmark work.

Target maintainer promise:

> Runner can no longer add or present benchmark checks without declaring maturity, runnable status, fixture/dataset status, harness status, sample policy, claim boundary, and promotion blockers.

## Planned PRs

- Benchmark legitimacy PR: add catalog maturity levels, status matrix, validation helpers, tests, and methodology docs.
- Release PR: promote reviewed legitimacy metadata from `develop` to `main` and bump version only in the release branch.

## Implementation Notes

- Do not make new broad benchmarks runnable in this release.
- Keep thin local samples labeled as `thin_local_sample`.
- Keep MMLU-Pro sampled reference separate from quick decision lanes.
- Keep SWE-bench Verified as a non-runnable `gold_candidate`, not a gold-runnable lane.
- Use `gold`, never `gold/curated` or `curated/gold`.

## Reviewer Checklist

- Every runnable and planned benchmark has a status-matrix entry.
- Maturity levels are conservative and do not promote thin local samples to reference or gold evidence.
- Planned GPQA, LiveCodeBench, repository edit smoke, and SWE-bench Verified entries remain non-runnable.
- EvalPlus and quant fidelity metadata call out remaining blockers before stronger reference claims.
- No local dollar-cost estimation, adaptive head-to-head testing, public leaderboard mechanics, or global intelligence score is introduced.
- Tests fail if new benchmark checks or planned candidates omit legitimacy metadata.

## Validation Plan

```bash
python3 -m unittest python/runner-core/tests/test_benchmark_catalog.py
python3 -m unittest python/runner-core/tests/test_capability_contract.py python/runner-core/tests/test_capability_summary.py python/runner-core/tests/test_capabilities.py
python3 -m json.tool schemas/capability_catalog.json >/tmp/capability_catalog.json.check
python3 -m json.tool schemas/json/capability_run.schema.json >/tmp/capability_run.schema.json.check
python3 -m json.tool schemas/json/capability_summary.schema.json >/tmp/capability_summary.schema.json.check
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
```

## Evidence Honesty Notes

- This release defines legitimacy gates; it does not add benchmark-lab credibility by itself.
- Thin local samples remain useful setup guidance but do not support reference, gold, leaderboard, or broad capability claims.
- Reference and gold lanes must earn their status through pinned datasets, harness controls, scoring controls, artifact preservation, and review.

## Release Criteria

- `docs/benchmark_legitimacy_program.md` exists and explains the maturity ladder.
- `schemas/capability_catalog.json` contains benchmark maturity levels and a status matrix covering implemented and planned lanes.
- Catalog tests validate maturity metadata and fail on missing status entries.
- No new broad benchmark is made runnable.
- Feature PR and release PR both receive reviewer-agent passes before merge.

## Current Blockers

- GitHub Actions may continue failing before steps due to the known account/billing/pre-run issue. Local validation must remain explicit until Actions are healthy.
- The next serious reference-lane releases still need deeper productization work for MMLU-Pro, EvalPlus, and quant fidelity artifacts.

## Next Actions

- Finish docs and catalog validation.
- Open benchmark legitimacy PR into `develop`.
- After review and merge, prepare a release PR.
- Continue into MMLU-Pro sampled reference productization.
