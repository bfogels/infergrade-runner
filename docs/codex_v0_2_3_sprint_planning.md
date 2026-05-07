# Codex v0.2.3 Sprint Planning

Date: 2026-05-07

## Branch State

- Runner `origin/main`: v0.2.2 at `ec154b5d4759baf6b34b246659830a507343205b`.
- Runner `origin/develop`: synced to `origin/main` at `ec154b5d4759baf6b34b246659830a507343205b`.
- Runner open PRs at sprint start: none.

## Release Goal

v0.2.3 should make runtime management more supportable without weakening the v0.2.2 managed macOS Apple Silicon lane.

Target user promise:

> Normal users stay on InferGrade Stable. Advanced users can intentionally inspect, select, or later update runtimes with clear provenance, no silent upgrades, and a rollback-aware recovery path.

## Planned PR Sequence

1. PR A: runtime channel/status groundwork.
   - Add shared engine channel metadata for `infergrade_stable`, `local_binary`, `upstream_release`, `previous_release`, and `experimental`.
   - Mark selected-existing runtimes as `local_binary`.
   - Expose channel policy through CLI `runtime channels` and status JSON.
   - Keep install/update behavior unchanged.

2. PR B: manual update-check status.
   - Report when selected managed runtime differs from the current stable manifest entry.
   - Do not download or upgrade automatically.
   - Keep warnings clear for local/experimental selections.

3. PR C: rollback command, if the current selected-runtime record has a known previous managed install.
   - Add only if the stored runtime layout can support rollback without pretending older upstream artifacts are available.

4. PR D: v0.2.3 release promotion if the status/update/rollback subset is coherent and reviewed.

## Reviewer Checklist

- No Tauri/keychain/terminal rendering dependency enters `runner-engine`.
- Desktop and CLI consume shared channel/status logic instead of forking policy.
- Runtime updates remain manual; no silent install, upgrade, or channel switch.
- Runtime provenance distinguishes checksum-verified managed archives from local binaries and experimental choices.
- Docs do not overclaim independent signatures, notarization, Windows/Linux, or CUDA/AMD support.
- Docker/Podman remain optional advanced capabilities.

## Validation Plan

Use the relevant subset per PR:

```bash
cargo test --manifest-path crates/runner-engine/Cargo.toml --locked
cargo test --manifest-path apps/runner-cli/Cargo.toml --locked
npm run check --prefix apps/desktop-runner
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
gitleaks detect --source=. --redact --no-banner --exit-code 0
git diff --check
```

## Release Criteria

v0.2.3 can promote when runtime channel/status behavior is shared, reviewed, and useful to users or maintainers without expanding platform claims.

## v0.2.3 Release Candidate Evidence

- Feature train landed in `develop`:
  - PR #154: shared runtime channel/status groundwork.
  - PR #155: Desktop runtime plan renders shared channel/update policy.
- Release branch `codex/runner-v023-release` bumps version to `0.2.3` only after those reviewed feature PRs landed in `develop`.
- GitHub Actions continued to fail before executing job steps/logs on feature PRs; local validation and reviewer approval were used for feature merges.

### Release Validation Snapshot

Planned release gates:

```bash
./scripts/build_desktop_sidecar.sh
cargo test --workspace --locked
cargo test --manifest-path crates/runner-engine/Cargo.toml --locked
cargo test --manifest-path apps/runner-cli/Cargo.toml --locked
cargo test --manifest-path apps/desktop-runner/src-tauri/Cargo.toml --locked
cargo test --manifest-path apps/desktop-runner/sidecar/Cargo.toml --locked
npm ci --prefix apps/desktop-runner
npm run check --prefix apps/desktop-runner
python3 -m unittest python/runner-core/tests/test_desktop_runner_capabilities.py python/runner-core/tests/test_release_ci.py
./scripts/test_all.sh
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
gitleaks detect --source=. --redact --no-banner --exit-code 0
git diff --check
```

### Release Limits

- v0.2.3 does not add runtime auto-updates, runtime rollback execution, or a second managed runtime archive.
- v0.2.3 does not broaden the v0.2.2 platform claim beyond macOS Apple Silicon managed Metal runtime support.
- Runtime archives remain SHA-256 verified, not independently signed.
