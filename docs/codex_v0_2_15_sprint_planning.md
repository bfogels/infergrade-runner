# Codex v0.2.15 Sprint Planning

## Current Branch State

- Runner `origin/main`: v0.2.14 MMLU-Pro sampled reference artifacts.
- Runner `origin/develop`: synced after v0.2.14 release.
- Runner open PRs at sprint start: none observed.
- Working branch: `codex/runner-evalplus-reference`.
- Worktree: `/Users/brianfogelson/Desktop/Code/infergrade/.worktrees/runner-evalplus-reference`.
- Hub state checked at sprint start: Hub has a small separate main/develop divergence; this release avoids Hub changes.

## Release Goal

Productize EvalPlus HumanEval+ as the first executable coding reference artifact path.

Target user promise:

> When HumanEval+ is selected, Runner preserves executable coding reference evidence as a validated capability artifact with pinned harness revision, pass@1 scoring metadata, raw outputs, scoring outputs, and explicit execution failure classes.

## Planned PRs

- EvalPlus HumanEval+ reference PR: emit validated `capability_run.json` for `evalplus_humaneval`, preserve EvalPlus revision, sample policy, raw outputs, scoring outputs, task-level pass/fail/error classes, and reference claim boundaries.
- Release PR: promote reviewed EvalPlus HumanEval+ reference work from `develop` to `main` and bump version only in the release branch.

## Implementation Notes

- Promote HumanEval+ to `reference` evidence with `reference_sample` confidence.
- Keep MBPP+ as a follow-up unless the generic EvalPlus helper safely covers it without changing its maturity claim.
- Preserve generated-code execution inside the existing EvalPlus container path.
- Preserve `generation_failed`, `malformed_output`, `timeout`, and `test_failed` separately where available from generated outputs and EvalPlus status rows.
- Do not add LiveCodeBench, SWE-bench, GPQA, adaptive head-to-head testing, leaderboard mechanics, or local dollar-cost estimates.

## Reviewer Checklist

- `evalplus_humaneval` emits a valid `capability_run.json` only after selected execution.
- Artifact evidence lane is `reference`, confidence label is `reference_sample`, and `experimental` remains true.
- EvalPlus upstream revision and sample policy are preserved in protocol metadata.
- Raw `predictions.jsonl` / `samples.jsonl` and scoring `summary.json` / `eval_results.json` are discoverable.
- Task states preserve generation, malformed, timeout, and test failure semantics where available from generated outputs and EvalPlus status rows.
- Unsupported claims explicitly block leaderboard, gold, LiveCodeBench, SWE-bench, repo-edit, and broad coding claims.
- Capability summary indexes the EvalPlus artifact under `local_coding_capability`.

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

- HumanEval+ reference evidence is executable coding evidence under an EvalPlus pass@1 protocol.
- It is not gold evidence, not leaderboard-grade, not LiveCodeBench, not SWE-bench, and not proof of repository-editing or broad agentic software engineering capability.
- MBPP+ remains a broader follow-up reference candidate until its productization and dogfood calibration are reviewed.

## Release Criteria

- HumanEval+ selected reference execution emits validated `capability_run.json`.
- Capability summary discovers and summarizes the HumanEval+ reference artifact.
- Tests cover artifact fields, EvalPlus revision, sample policy, task scoring, execution failure classes, and claim boundaries.
- Feature PR and release PR both receive reviewer-agent passes before merge.

## Current Blockers

- GitHub Actions may continue to fail before steps due to the known pre-run/account issue.
- Real observed duration/token-volume calibration still needs dogfood runs.

## Next Actions

- Finish HumanEval+ artifact tests and docs.
- Open the feature PR.
- After review and merge, release the EvalPlus HumanEval+ productization slice.
- Continue into MBPP+ if quality allows, then quant-fidelity reference productization.
