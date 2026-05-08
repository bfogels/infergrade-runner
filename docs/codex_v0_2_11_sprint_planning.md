# Codex v0.2.11 Sprint Planning

## Current Branch State

- Runner `origin/main`: v0.2.10 release merged.
- Runner `origin/develop`: one v0.2.10 sync merge ahead of `main` at sprint start.
- Runner open PRs at sprint start: none observed.
- Working branch: `codex/runner-v0211-capability-summary`.
- Worktree: `/Users/brianfogelson/Desktop/Code/infergrade/.worktrees/runner-v0211-capability-summary`.
- Hub state checked at sprint start: no open PRs observed; Hub `develop` is behind `main` by recent v3 promotion commits. This release avoids Hub changes.

## Release Goal

Make existing assistant, coding, and reasoning capability artifacts easier to find and interpret without adding broad benchmark claims.

Target user promise:

> Runner can emit a local capability summary that explains which local capability surfaces were run, which are missing, which failed or were partial, and what cautious next benchmark action follows.

## Planned PRs

- Capability summary PR: add a Runner-owned `capability_summary.json` artifact, conservative confidence/next-action helpers, schema/semantic validation, report discoverability, and tests for scored, failed, partial, and missing surfaces.
- Release PR: promote the reviewed summary work from `develop` to `main` and bump version to `0.2.11` only in the release branch.

## Implementation Notes

- Preserve existing `capability_run.json` artifacts from v0.2.8-v0.2.10.
- Add a distinct `capability_summary` artifact under `artifacts/capability/capability_summary.json`.
- Summaries must keep surfaces separate:
  - `local_assistant_capability`
  - `local_coding_capability`
  - `local_reasoning_capability`
  - `quant_fidelity`
  - `deployment_fitness`
- Do not compute a global intelligence score.
- Confidence labels stay conservative. Thin local samples do not become `stronger_local_sample`, `reference_sample`, or `gold` because the score is high.
- Next actions are rule-based and cautious, such as running a missing lane, retrying a failed/partial lane, or repeating local capability checks after all thin samples exist.

## Reviewer Checklist

- No local dollar-cost estimates, adaptive testing, public leaderboard claims, global scores, or gold evidence.
- Confidence labels cannot be over-promoted automatically from high scores.
- Failed, partial, skipped, not-yet-benchmarked, and not-comparable states remain distinct.
- The summary artifact points to raw `capability_run.json` paths and does not replace them.
- Browser-visible state and Hub behavior are unchanged in this release.
- Any concurrent bugfix changes on `develop` are preserved if they land before promotion.

## Validation Plan

```bash
python3 -m unittest python/runner-core/tests/test_capability_contract.py python/runner-core/tests/test_capability_summary.py python/runner-core/tests/test_capabilities.py
python3 -m unittest python/runner-core/tests/test_request_resolution.py python/runner-core/tests/test_runner.py python/runner-core/tests/test_end_to_end_proof_path.py
python3 -m json.tool schemas/capability_catalog.json >/tmp/capability_catalog.json.check
python3 -m json.tool schemas/json/capability_run.schema.json >/tmp/capability_run.schema.json.check
python3 -m json.tool schemas/json/capability_summary.schema.json >/tmp/capability_summary.schema.json.check
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
gitleaks detect --source=. --redact --no-banner --exit-code 0
```

## Evidence Honesty Notes

- v0.2.11 summarizes existing thin local samples; it does not add a new benchmark lane.
- A summary may say a surface is scored, partial, failed, skipped, not yet benchmarked, or not comparable.
- A summary must not say the model is globally best, leaderboard-grade, decision-grade, or broadly proven.

## Release Criteria

- A user or maintainer can locate capability artifacts without reading implementation details.
- `capability_summary.json` explains mixed assistant/coding/reasoning evidence without creating a global score.
- Report output includes capability artifact discoverability.
- Tests cover scored, failed, partial, mixed, and missing-surface summaries.
- The feature PR and release PR both receive reviewer-agent passes before merge.

## Current Blockers

- None for Runner-owned local summary artifacts.
- Hub display remains deferred to v0.2.12 because Hub `develop` is currently behind `main`.
