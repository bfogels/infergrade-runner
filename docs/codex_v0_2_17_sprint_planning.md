# Codex v0.2.17 Sprint Planning

## Current Branch State

- Runner `origin/main`: v0.2.16 MBPP+ reference artifacts.
- Runner `origin/develop`: synced after v0.2.16 release.
- Runner open PRs at sprint start: none observed.
- Working branch: `codex/runner-quant-fidelity-reference`.
- Worktree: `/Users/brianfogelson/Desktop/Code/infergrade/.worktrees/runner-quant-fidelity-reference`.
- Hub note: Hub PR #225 landed reference-evidence display polish into `develop`; this Runner slice only changes Runner contracts/artifacts/docs.

## Release Goal

Productize `perplexity_reference_v1` as the first quant-fidelity reference artifact path.

Target user promise:

> When quant fidelity is intentionally selected, Runner preserves same-family quant-fidelity reference evidence as a validated capability artifact with pinned corpus/protocol metadata, a comparability key, raw/scoring outputs, and explicit claim boundaries.

## Planned PRs

- Quant-fidelity artifact PR: emit validated `capability_run.json` for `perplexity_reference_v1`, preserve `fidelity_raw.json`, `summary.json`, perplexity, bits-per-byte where available, token/byte counts, duration, same-family comparability key, and summary discovery under `quant_fidelity`.
- Release PR: promote reviewed quant-fidelity reference work from `develop` to `main` and bump version only in the release branch.

## Implementation Notes

- Do not change quick/default first-run paths.
- Keep `perplexity_reference_v1` intentionally selected.
- Use `reference` lane, `reference_sample` confidence, and `experimental=true`.
- Same-family comparability requires model family, checkpoint, tokenizer id, corpus id/revision, and protocol id/parameters.
- Perplexity is lower-is-better quant-fidelity evidence only; it is not a general model-quality or capability score.
- Do not add adaptive quant racing, dollar-cost estimates, leaderboard mechanics, GPQA, LiveCodeBench, SWE-bench, or gold claims.

## Reviewer Checklist

- `perplexity_reference_v1` emits a valid `capability_run.json` only when the lane is intentionally selected.
- Artifact preserves raw fidelity payload and scoring summary.
- Artifact includes corpus id/revision, protocol id/parameters, and same-family comparability key.
- `capability_summary.json` discovers the artifact under `quant_fidelity`.
- Catalog maturity moves to `reference_runnable` without changing quick/default inclusion.
- Claim boundaries reject cross-family ranking, general model quality, assistant/coding/reasoning capability, gold, and leaderboard claims.

## Validation Plan

```bash
python3 -m unittest python/runner-core/tests/test_llama_cpp_adapter.py python/runner-core/tests/test_runner.py python/runner-core/tests/test_capability_summary.py python/runner-core/tests/test_benchmark_catalog.py
python3 -m unittest discover python/runner-core/tests
python3 -m json.tool schemas/capability_catalog.json >/tmp/capability_catalog.json.check
python3 -m json.tool schemas/json/capability_run.schema.json >/tmp/capability_run.schema.json.check
python3 -m json.tool schemas/json/capability_summary.schema.json >/tmp/capability_summary.schema.json.check
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
gitleaks detect --source=. --redact --no-banner --exit-code 1
```

## Validation Evidence

- Targeted suite passed: 75 tests across llama.cpp adapter, Runner orchestration, capability summary, catalog, and capability contract.
- Broad runner-core suite passed: 290 tests.
- JSON parse checks passed for `schemas/capability_catalog.json`, `schemas/json/capability_run.schema.json`, and `schemas/json/capability_summary.schema.json`.
- Version checks passed before release bump.
- `cargo fmt --all -- --check` passed.
- `git diff --check` passed.
- `gitleaks detect --source=. --redact --no-banner --exit-code 1` found no leaks.

## Reviewer Findings

- Pending.

## Evidence Honesty Notes

- Quant-fidelity reference evidence is same-family evidence only.
- Direct comparisons require matching comparability keys.
- The lane is not gold evidence, not leaderboard-grade, not general model-quality proof, and not assistant/coding/reasoning capability evidence.
- Real dogfood runs and reference-precision baselines are still needed for quality-retention deltas.

## Release Criteria

- `perplexity_reference_v1` selected execution emits validated `capability_run.json`.
- Capability summary discovers and summarizes quant fidelity under `quant_fidelity`.
- Tests cover artifact fields, comparability key, summary indexing, and catalog maturity.
- Feature PR and release PR both receive reviewer-agent passes before merge.

## Current Blockers

- GitHub Actions may continue to fail before steps due to the known pre-run/account issue.
- Real observed duration/token-volume calibration and reference-precision baseline runs are follow-up work.

## Next Actions

- Finish feature implementation and validation.
- Open feature PR to `develop`.
- Spawn reviewer before merge.
- If merged cleanly, open release PR and then sync `develop` after release.
