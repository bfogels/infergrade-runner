# Codex v0.2.12 Sprint Planning

## Current Branch State

- Runner `origin/main`: v0.2.11 capability summary release.
- Runner `origin/develop`: hardening train ahead of `main`, including PRs #179, #180, #181, #183, and corrective PR #184.
- Runner open PRs at release-branch start: none after #184 merged.
- Working branch: `codex/runner-v0212-hardening-release`.
- Worktree: `/Users/brianfogelson/Desktop/Code/infergrade/.worktrees/runner-hardening-release`.
- Hub state checked during release prep: Hub `develop` had moved one commit ahead of `main` with separate mobile Recommend/disclosure work; this Runner release does not include Hub changes.

## Release Goal

Promote the reviewed Runner security, transport, extraction, token-handling, and CI hardening train to `main` without adding benchmark features.

Target maintainer promise:

> Runner v0.2.12 tightens security and CI posture before the benchmark legitimacy track continues.

## Included PRs

- #179: Desktop CSP, Tauri capability boundary, sidecar JSON transport, and CLI token handling hardening.
- #180: shared Hub HTTP clients/timeouts, runner id path validation, stdout/stderr caps, and runtime archive/tar extraction safety.
- #181: Rust CI coverage, cargo-deny baseline, strict clippy, and pinned gitleaks checksum.
- #183: corrective follow-up for `cloud_container` execution-mode vocabulary and loopback-only cleartext HTTP at the Tauri capability boundary.
- #184: corrective follow-up rejecting invalid execution modes in the shared Rust Hub claim request builder.
- Release PR: promote the reviewed hardening train from `develop` to `main` and bump version to `0.2.12` only in the release branch.

## Scope Boundaries

- No benchmark legitimacy features are included in this release.
- No new benchmark lane, maturity metadata, reference lane, or Hub display behavior is added here.
- No local dollar-cost estimation, adaptive head-to-head testing, public leaderboard mechanics, or gold evidence is added.
- Desktop remains an adapter; shared transport and validation logic live in `runner-engine` where appropriate.

## Reviewer Checklist

- `cloud_container` is the accepted cloud execution-mode vocabulary; `cloud_worker` is rejected.
- Tauri capability validation rejects cleartext non-loopback HTTP while preserving HTTPS and loopback development URLs.
- Hub claim request validation cannot send arbitrary execution-mode strings.
- Token handling does not expose bearer, upload, pairing, or runner tokens in browser-visible state or diagnostic output.
- Runtime archive extraction protects against unsafe paths and unexpected archive entries.
- CI hardening is configuration-only where intended and does not weaken local validation.
- The release contains no benchmark-feature contamination.

## Validation Plan

```bash
cargo fmt --all -- --check
cargo build --workspace --exclude infergrade_desktop_runner --locked
cargo test --workspace --exclude infergrade_desktop_runner --locked
bash ./scripts/build_desktop_sidecar.sh
cargo build -p infergrade_desktop_runner --lib --locked
cargo test -p infergrade_desktop_runner --lib --locked
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo deny check --hide-inclusion-graph
./scripts/test_all.sh
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
gitleaks detect --source=. --redact --no-banner --exit-code 0
```

If GitHub Actions continue to fail before job steps, local validation and reviewer evidence should be treated as the release evidence. Pre-step failures must be documented rather than treated as code-test failures.

## Evidence Honesty Notes

- v0.2.12 is a hardening release, not a benchmark capability release.
- It improves security, transport reliability, archive safety, and CI posture before stronger benchmark evidence work.
- It does not change the evidence lane semantics from v0.2.7-v0.2.11.

## Release Criteria

- #179, #180, #181, #183, and #184 are merged to `develop`.
- Corrective review confirms #183's vocabulary and cleartext HTTP fixes are complete across the shared claim path.
- Version declarations are synchronized at `0.2.12` only in the release branch.
- Strongest available local validation has run, with any environment blockers recorded exactly.
- Release PR receives a reviewer-agent pass before merge.

## Current Blockers

- GitHub Actions are still expected to fail before steps due to the account/billing/pre-run issue. This is a release risk, but not evidence of code failure when job metadata shows `steps: []`.
- `cargo deny` may be unavailable locally if the tool is not installed; if so, install/use it only if already available through the environment or document the blocker.

## Next Actions

- Run release validation.
- Open release PR from `codex/runner-v0212-hardening-release` to `main`.
- Spawn release reviewer.
- Merge only after review and documented validation.
- After release, continue with the benchmark legitimacy program as the next Runner release train.
