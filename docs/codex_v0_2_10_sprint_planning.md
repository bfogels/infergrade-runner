# Codex v0.2.10 Sprint Planning

## Current Branch State

- Runner `origin/main`: `cdc7c27`, v0.2.9 release merged.
- Runner `origin/develop`: `eac0e8f`, synced with v0.2.9 release content and one sync merge commit ahead of `main`.
- Runner open PRs at sprint start: none.
- Working branch: `codex/runner-v0210-reasoning-lane`.
- Worktree: `/Users/brianfogelson/Desktop/Code/infergrade/.worktrees/runner-v0210-reasoning-lane`.
- Hub state checked at sprint start: open Hub PR #214; this slice avoids Hub changes.

## Release Goal

Add a compact local reasoning signal without shipping restricted datasets, broad MMLU-Pro defaults, runnable GPQA, or heavy long-context work.

Target user promise:

> Runner can produce a small, validated local reasoning capability artifact that is separate from assistant, coding, deployment, quant-fidelity, and first-run smoke evidence.

## Planned PRs

- Reasoning lane PR: add a pinned native exact-answer reasoning fixture set, deterministic answer scoring, catalog metadata, `capability_run.json` emission, positive and failed/partial tests, and honest docs.
- Release PR: promote the reviewed reasoning lane from `develop` to `main` and bump version to `0.2.10` only in the release branch.

## Implementation Notes

- The first lane should use `surface=local_reasoning_capability`, `lane=decision`, `grade=thin_local_sample`, `confidence_label=thin_local_sample`, and `experimental=true`.
- The scorer should be deterministic exact-answer or answer-letter scoring over generated text.
- Restricted or gated datasets must not be committed.
- MMLU-Pro remains reference evidence; GPQA remains access-gated and non-runnable.
- Quant fidelity is already represented by `perplexity_reference_v1`; this slice should not overclaim quant fidelity as general capability.

## Reviewer Checklist

- No GPQA, restricted dataset contents, public leaderboard mechanics, local dollar-cost estimates, or adaptive testing.
- No global reasoning or intelligence score claim.
- Evidence lanes remain `smoke`, `decision`, `reference`, and `gold`.
- The lane declares fixture/task versions, scoring policy, scorer type, evidence lane, surface, and claim boundary.
- Failed, partial, malformed, skipped, not-yet-benchmarked, and not-comparable states remain distinct.
- Thin local sample copy cannot be mistaken for MMLU-Pro/GPQA reference evidence or gold evidence.

## Validation Plan

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

## Evidence Honesty Notes

- v0.2.10 should add a thin local reasoning sample, not a broad reasoning benchmark suite.
- It does not add runnable GPQA, broad MMLU-Pro defaults, long-context defaults, public leaderboard claims, or gold evidence.
- Quant fidelity remains a separate surface and is not a general capability score.

## Release Criteria

- A local native reasoning check can emit a validated `capability_run.json` artifact.
- The artifact is `local_reasoning_capability` decision evidence with thin-local-sample confidence and explicit claim boundaries.
- Tests cover passing and failed/partial generation paths.
- Catalog/docs explain what the lane measures and what it does not measure.
- The feature PR and release PR both receive reviewer-agent passes before merge.

## Current Blockers

- None for the synthetic/pinned exact-answer reasoning microcheck.
- Runnable GPQA remains blocked on access, leakage, and local snapshot controls.

## Reasoning Lane PR Local Evidence

Branch: `codex/runner-v0210-reasoning-lane`
PR: pending

Implemented:

- Added `reasoning_exact_answer_v1`, a native local reasoning decision check with three synthetic exact-answer fixtures.
- Added deterministic exact-answer scoring with generation failures preserved as failed task rows.
- Added `capability_run.json` artifact emission for the `local_reasoning_capability` surface.
- Added catalog metadata for the `reasoning_exact_answer` group and `reasoning_exact_answer_v1` score policy.
- Documented that the lane is a thin local sample and does not use GPQA, replace MMLU-Pro reference evidence, or support broad reasoning/gold claims.

Validation passed locally:

```bash
python3 -m unittest python/runner-core/tests/test_capabilities.py python/runner-core/tests/test_benchmark_catalog.py python/runner-core/tests/test_capability_contract.py
python3 -m json.tool schemas/capability_catalog.json >/tmp/capability_catalog.json.check
python3 -m json.tool schemas/json/capability_run.schema.json >/tmp/capability_run.schema.json.check
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
gitleaks detect --source=. --redact --no-banner --exit-code 0
```

Known limits:

- The v0.2.10 reasoning lane scores a small synthetic exact-answer set only.
- It does not provide GPQA, MMLU-Pro default coverage, long-context reasoning, broad factual coverage, reference evidence, or gold evidence.

Reviewer findings:

- P1: reasoning initially appeared in the assistant suite defaults. Fixed by keeping reasoning explicit so assistant and reasoning surfaces are not averaged by default.
- P2: exact-answer scoring initially required the entire normalized response to equal the answer. Fixed by extracting one unambiguous yes/no, numeric, or option-letter answer and rejecting ambiguous multi-answer text.

## v0.2.10 Release Candidate Evidence

Branch: `codex/runner-v0210-release`
PR: pending

Scope:

- Promote the reviewed v0.2.10 reasoning lane feature from `develop` to `main`.
- Bump version declarations from `0.2.9` to `0.2.10` only in the release branch.
- Preserve the release boundary: native exact-answer reasoning decision evidence, not GPQA, broad MMLU-Pro defaults, quant-fidelity expansion, Hub display, or stronger evidence claims.

Branch-distance proof before release branch:

```bash
git rev-list --left-right --count origin/main...origin/develop
# 0 2

git diff --name-status origin/main...origin/develop
# M docs/capability_benchmarks.md
# A docs/codex_v0_2_10_sprint_planning.md
# M python/runner-core/src/infergrade/capabilities.py
# M python/runner-core/tests/test_benchmark_catalog.py
# M python/runner-core/tests/test_capabilities.py
# M schemas/capability_catalog.json
```

Validation passed locally on the release branch:

```bash
python3 -m unittest python/runner-core/tests/test_capabilities.py python/runner-core/tests/test_benchmark_catalog.py python/runner-core/tests/test_capability_contract.py python/runner-core/tests/test_request_resolution.py python/runner-core/tests/test_runner.py python/runner-core/tests/test_end_to_end_proof_path.py
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
python3 -m json.tool schemas/capability_catalog.json >/tmp/capability_catalog.json.check
python3 -m json.tool schemas/json/capability_run.schema.json >/tmp/capability_run.schema.json.check
cargo test --manifest-path crates/runner-engine/Cargo.toml --locked
cargo test --manifest-path apps/runner-cli/Cargo.toml --locked
gitleaks detect --source=. --redact --no-banner --exit-code 0
npm ci --prefix apps/desktop-runner
npm run check --prefix apps/desktop-runner
./scripts/build_desktop_sidecar.sh
```

Release evidence honesty:

- v0.2.10 does not add runnable GPQA, broad MMLU-Pro defaults, public leaderboard mechanics, local dollar-cost estimates, adaptive testing, or global reasoning/intelligence claims.
- Quant fidelity remains represented as a separate reference surface by `perplexity_reference_v1`; it is not generalized in this release.
- GitHub Actions may still show the known pre-step `steps: []` failure shape; local validation and reviewer passes are the release evidence if that infra issue persists.
