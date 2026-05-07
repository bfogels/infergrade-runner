# Codex v0.2.4 Sprint Planning

Date: 2026-05-07

## Branch State

- Runner `origin/main`: v0.2.3 at `9e5da5c`.
- Runner `origin/develop`: synced to `origin/main` at `9e5da5c`.
- Runner open PRs at sprint start: none.
- Hub `origin/main`: `0a29bfa`.
- Hub `origin/develop`: `5ec41b2`, one commit ahead of `main` and one behind after the secondary-surface routing work.
- Hub open PR at sprint start: #210, `codex/hub-v3-recommend-answer-flow` into `develop`, merge state `UNSTABLE`.

## Release Goal

v0.2.4 should make failed runtime install, first-run, pairing, and upload states more recoverable without broadening the platform or benchmark claim.

Target user promise:

> If the Desktop Runner cannot install the runtime, pair, run the first local benchmark, or upload the result, the app and CLI leave the user with a clear next action and a secret-free support summary.

## Planned PR Sequence

1. PR A: support summary contract and first-run recovery hints.
   - Add a Runner-owned support summary JSON in `runner-engine`.
   - Include app/runner version, runtime status/channel/provenance, pairing profile status, first-run artifact/upload status when provided, and safe recent errors.
   - Exclude runner tokens, upload tokens, bearer tokens, pairing codes, and authorization headers.
   - Expose the summary through the Rust CLI for local support capture.
   - Add tests for token redaction and stale/missing runtime next actions.

2. PR B: Desktop support actions.
   - Add Desktop actions to copy the support summary and reveal/copy local artifacts.
   - Surface retry upload after a completed local run with failed/missing upload.
   - Keep all browser-visible state token-free.

3. PR C: runtime recovery actions.
   - Add explicit remove/reinstall/retry affordances for stale selected managed runtimes.
   - Keep update and channel changes manual; no silent runtime switching.

4. PR D: v0.2.4 release promotion.
   - Bump version only after reviewed feature PRs land in `develop`.
   - Include local support-summary validation, Desktop static checks, Rust tests, and release-honesty notes.

## Reviewer Checklist

- No Tauri/keychain/browser dependency enters `runner-engine`.
- Desktop remains an adapter over Runner-owned support and runtime truth.
- Support summaries contain no tokens, bearer headers, upload tokens, pairing codes, or command-line secrets.
- Browser-visible Desktop state stays token-free.
- Runtime recovery does not silently install, upgrade, remove, or switch runtime channels.
- Missing, stale, failed, partial, skipped, and not-comparable evidence states remain distinct.
- Native first-run evidence remains experimental/informational.
- Docs do not overclaim signing, notarization, Windows/Linux support, CUDA/ROCm support, or decision-grade evidence.
- Docker/Podman remain optional advanced support for native first-run.

## Validation Plan

Use the relevant subset per PR:

```bash
cargo test --manifest-path crates/runner-engine/Cargo.toml --locked
cargo test --manifest-path apps/runner-cli/Cargo.toml --locked
npm run check --prefix apps/desktop-runner
python3 -m unittest python/runner-core/tests/test_support.py
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
gitleaks detect --source=. --redact --no-banner --exit-code 0
git diff --check
```

For release promotion, run the full v0.2.3 release validation set plus the new support-summary smoke.

## Evidence Honesty Notes

- v0.2.4 is a supportability release, not a benchmark legitimacy release.
- Managed runtime archives remain SHA-256 verified but not independently signed.
- Native first-run output remains smoke evidence.
- A support summary is diagnostic context only; it is not a result bundle and must never be used as Hub evidence.

## Release Criteria

v0.2.4 can promote when failed runtime/first-run/upload paths have clearer recovery actions, support export is demonstrably secret-free, and reviewer validation agrees the release improves user supportability without expanding product claims.

## Current Blockers

- Public Developer ID signing and notarization are v0.2.5 scope.
- Hub benchmark display changes are deferred while Hub PR #210 is active unless a Runner contract import requires them.

## Next Actions

- PR A is open as PR #157 from `codex/runner-v024-supportability` into `develop`.
- Independent reviewer completed initial review, two targeted re-reviews, and final privacy re-review.
- Land PR #157 into `develop` if GitHub allows the merge despite the known pre-run CI failure shape.

## PR A Local Evidence

Branch: `codex/runner-v024-supportability`
PR: #157

Implemented:

- Runner-owned support summary contract in `runner-engine`.
- Rust CLI `support summary` command for secret-free local support capture.
- Runtime, pairing, first-run artifact, upload retry, and recent-error fields with redaction.
- Negative tests proving runner/upload/bearer token echoes are excluded.

Validation passed:

```bash
cargo test --manifest-path crates/runner-engine/Cargo.toml --locked
cargo test --manifest-path apps/runner-cli/Cargo.toml --locked
python3 -m unittest python/runner-core/tests/test_support.py
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
cargo run --manifest-path apps/runner-cli/Cargo.toml -- support summary --error 'Authorization: Bearer qbhr_manual_secret'
```

Reviewer findings:

- P1: first-run artifact fields such as upload reason/run ID/bundle ID could leak token-shaped values. Fixed by redacting copied first-run fields and adding regression coverage.
- P1: recent-error redaction missed hyphenated uppercase pairing codes such as `IGRP-8421`. Fixed with case-insensitive pairing-code redaction coverage.
- Re-review P1: token-shaped values embedded inside artifact paths could leak. Fixed by redacting support token and pairing-code patterns anywhere inside copied strings, with artifact-path regression coverage.
- Final re-review reported no remaining findings in the privacy fixes.

GitHub Actions:

- PR #157 checks failed before executing workflow steps:
  - CI `test` run `25523863138`, job `74914593302`, `steps: []`, `log not found`.
  - Secret Scan `Gitleaks` run `25523863029`, job `74914593228`, `steps: []`, `log not found`.
- This matches the existing Runner infra/pre-run failure shape from v0.2.3; local validation and reviewer re-review are the current merge evidence.

Known limits:

- The Rust CLI support summary does not read OS credential storage, so pairing status is marked `not_loaded_by_cli`.
- Desktop copy/reveal/retry-upload actions remain PR B scope.
- Runtime remove/reinstall recovery actions remain PR C scope.
