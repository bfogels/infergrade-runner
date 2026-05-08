# Codex v0.2.14 Sprint Planning

## Current Branch State

- Runner `origin/main`: v0.2.13 benchmark legitimacy gates.
- Runner `origin/develop`: post-release sync after v0.2.13.
- Runner open PRs at sprint start: none observed.
- Working branch: `codex/runner-mmlu-reference-productization`.
- Worktree: `/Users/brianfogelson/Desktop/Code/infergrade/.worktrees/runner-mmlu-reference-productization`.
- Hub state checked at sprint start: Hub has separate UI work ahead of `main`; this release avoids Hub changes.

## Release Goal

Productize MMLU-Pro sampled reference evidence so it emits a validated Runner-owned `capability_run.json` artifact and appears in local capability summaries.

Target user promise:

> When MMLU-Pro reference is intentionally selected, Runner preserves the reference evidence as a validated capability artifact with category breakdowns and clear claim boundaries.

## Planned PRs

- MMLU-Pro artifact PR: emit validated `capability_run.json` for `mmlu_pro_reference_v1`, preserve category metrics, dataset revision, sample policy, raw outputs, scoring outputs, and reference claim boundaries.
- Release PR: promote reviewed MMLU-Pro artifact work from `develop` to `main` and bump version only in the release branch.

## Implementation Notes

- Keep MMLU-Pro out of `quick_default`.
- Keep it as `reference` evidence and `reference_sample` confidence, not gold evidence.
- Preserve invalid/malformed outputs separately from valid wrong answers.
- Do not add GPQA, LiveCodeBench, SWE-bench, broad leaderboard mechanics, or local dollar-cost estimates.
- Hub display already understands capability summaries; no Hub code is required for this slice.

## Reviewer Checklist

- `mmlu_pro_reference_v1` emits a valid `capability_run.json` only after the selected reference run executes.
- Artifact evidence lane is `reference`, confidence label is `reference_sample`, and `experimental` remains true.
- Dataset revision and sample policy are preserved in protocol metadata.
- Category metrics remain available in the artifact summary.
- Unsupported claims explicitly block leaderboard, gold, and global intelligence claims.
- Capability summary indexes the MMLU-Pro capability run under `local_reasoning_capability`.

## Validation Plan

```bash
python3 -m unittest python/runner-core/tests/test_capabilities.py
python3 -m unittest python/runner-core/tests/test_capability_container_runners.py python/runner-core/tests/test_benchmark_catalog.py python/runner-core/tests/test_capability_summary.py
python3 -m json.tool schemas/capability_catalog.json >/tmp/capability_catalog.json.check
python3 -m json.tool schemas/json/capability_run.schema.json >/tmp/capability_run.schema.json.check
python3 -m json.tool schemas/json/capability_summary.schema.json >/tmp/capability_summary.schema.json.check
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
```

## Evidence Honesty Notes

- MMLU-Pro sampled reference evidence is useful as a broad knowledge/reasoning reference signal.
- It is intentionally selected, not a first-run quick default.
- It is not leaderboard-grade, gold evidence, GPQA, or proof of global intelligence.

## Release Criteria

- MMLU-Pro selected reference execution emits validated `capability_run.json`.
- Capability summary discovers and summarizes the MMLU-Pro reference artifact.
- Tests cover artifact fields, dataset revision, category metrics, task scoring, and claim boundaries.
- Feature PR and release PR both receive reviewer-agent passes before merge.

## Current Blockers

- GitHub Actions may continue to fail before steps due to the known pre-run/account issue.
- Real observed duration/token-volume calibration still needs dogfood runs.

## Next Actions

- Open the feature PR.
- After review and merge, release the MMLU-Pro productization slice.
- Continue into EvalPlus reference and quant-fidelity reference productization.
