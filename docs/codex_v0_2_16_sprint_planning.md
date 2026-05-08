# Codex v0.2.16 Sprint Planning

## Current Branch State

- Runner `origin/main`: v0.2.15 HumanEval+ reference artifacts.
- Runner `origin/develop`: synced after v0.2.15 release.
- Runner open PRs at sprint start: none observed.
- Working branch: `codex/runner-evalplus-mbpp-reference`.
- Worktree: `/Users/brianfogelson/Desktop/Code/infergrade/.worktrees/runner-evalplus-mbpp-reference`.
- Hub state checked at sprint start: Hub has a small separate main/develop divergence; this release avoids Hub changes.

## Release Goal

Productize EvalPlus MBPP+ as its own coding breadth reference artifact path, separate from HumanEval+.

Target user promise:

> When MBPP+ is intentionally selected, Runner preserves executable coding breadth reference evidence as a validated capability artifact with pinned EvalPlus revision, MBPP sample policy, generated samples, scoring outputs, and explicit task-level status classes.

## Planned PRs

- MBPP+ reference PR: emit validated `capability_run.json` for `evalplus_mbpp`, preserve EvalPlus revision, MBPP sample policy, raw outputs, generated samples, scoring outputs, pass@1 base/plus metrics, task status classes, and MBPP-specific claim boundaries.
- Release PR: promote reviewed MBPP+ reference work from `develop` to `main` and bump version only in the release branch.

## Implementation Notes

- Do not alter or destabilize the HumanEval+ artifact path.
- Keep MBPP+ as `local_coding_capability`, `reference` lane, `reference_sample` confidence, and `experimental=true`.
- Keep HumanEval+ and MBPP+ separate in artifacts, summaries, docs, and catalog metadata.
- Preserve MBPP dataset identity and serialized-input handling through the existing EvalPlus container.
- Keep generated-code execution inside the existing EvalPlus container path.
- Do not add GPQA, LiveCodeBench, SWE-bench, adaptive head-to-head testing, leaderboard mechanics, local dollar-cost estimates, or Hub changes.

## Reviewer Checklist

- `evalplus_mbpp` emits a valid `capability_run.json` only after selected execution.
- HumanEval+ and MBPP+ are distinguishable in artifact protocol metadata, task ids, sample policy, and summary indexing.
- EvalPlus upstream revision and MBPP sample policy are preserved.
- Raw `predictions.jsonl`, generated `samples.jsonl`, scoring `summary.json` / `eval_results.json`, `cases.jsonl`, and `benchmark_metadata.json` are discoverable.
- Wrong code/test failures remain scored task failures, while generation and malformed output remain failed task rows.
- Unsupported claims explicitly block leaderboard, gold, LiveCodeBench, SWE-bench, repo-edit, and broad agentic software-engineering claims.
- MBPP+ remains out of quick/default first-run paths.

## Validation Plan

```bash
python3 -m unittest python/runner-core/tests/test_capabilities.py python/runner-core/tests/test_capability_container_runners.py python/runner-core/tests/test_benchmark_catalog.py python/runner-core/tests/test_capability_summary.py
python3 -m json.tool schemas/capability_catalog.json >/tmp/capability_catalog.json.check
python3 -m json.tool schemas/json/capability_run.schema.json >/tmp/capability_run.schema.json.check
python3 -m json.tool schemas/json/capability_summary.schema.json >/tmp/capability_summary.schema.json.check
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
```

## Evidence Honesty Notes

- MBPP+ reference evidence is executable coding breadth evidence under an EvalPlus pass@1 protocol.
- It is not gold evidence, not leaderboard-grade, not LiveCodeBench, not SWE-bench, and not proof of repository-editing or broad agentic software engineering capability.
- Real dogfood runs are still required for observed duration, token volume, and failure behavior.

## Release Criteria

- MBPP+ selected reference execution emits validated `capability_run.json`.
- Capability summary discovers and summarizes MBPP+ under `local_coding_capability` without flattening it into HumanEval+.
- Tests cover artifact fields, EvalPlus revision, MBPP sample policy, task scoring, status classes, and claim boundaries.
- Feature PR and release PR both receive reviewer-agent passes before merge.

## Current Blockers

- GitHub Actions may continue to fail before steps due to the known pre-run/account issue.
- Real observed duration/token-volume calibration still needs dogfood runs.

## Next Actions

- Finish MBPP+ artifact tests and docs.
- Open the feature PR.
- After review and merge, release the MBPP+ productization slice if quality remains high.
- Continue into quant-fidelity reference productization.
