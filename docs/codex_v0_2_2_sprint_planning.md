# Codex v0.2.2 Sprint Planning

Date: 2026-05-07

## Branch State

- Runner `origin/main`: v0.2.1 at `ecbe7bad880d667848d89f4b9bc518db192531b6`.
- Runner `origin/develop`: synced to `origin/main` at `ecbe7bad880d667848d89f4b9bc518db192531b6`.
- Runner open PRs at sprint start: none.
- Hub `origin/main`: `c9bb01b1e8566181365be94b2973fb1cb3807ec5`, including Desktop native first-run handoff and native-first-run evidence honesty guardrails.
- Hub open PRs at sprint start: none.

## Release Goal

v0.2.2 should move the macOS Apple Silicon lane from "selected existing llama.cpp runtime" toward "app-managed recommended runtime" without weakening supply-chain, privacy, or evidence honesty.

Target user promise:

> Install Desktop Runner. Pair with Hub. Install/select the recommended macOS Apple Silicon Metal llama.cpp runtime through InferGrade. Run native first-run. Upload evidence. No Homebrew, PATH edits, terminal, repo checkout, Python, Rust, or Docker for the normal Desktop path.

## Current Blocker/Risk

The latest upstream llama.cpp release inspected on 2026-05-07 is `b9050`. GitHub publishes a macOS arm64 archive:

- `llama-b9050-bin-macos-arm64.tar.gz`
- URL: `https://github.com/ggml-org/llama.cpp/releases/download/b9050/llama-b9050-bin-macos-arm64.tar.gz`
- GitHub asset digest: `sha256:d334fa44e42a143ec6e49924f9630136c0b5fedc5a615508636ba9c8d08eb5d3`
- Size: `8641914`

The GitHub release metadata does not expose an independent signature asset for that archive. v0.2.2 work can still add an explicit manifest and checksum-verification path, but docs and UI must not claim signed runtime provenance until an independent signature/minisign/cosign lane exists.

## Proposed PR Sequence

1. PR A: runtime manifest and engine install plan.
   - Add a Runner-owned managed runtime manifest in `runner-engine`.
   - Include macOS Apple Silicon upstream `b9050` metadata, checksum, expected binaries, compatibility notes, channel, and rollback relationship.
   - Keep actual download/install disabled in this PR.
   - Add CLI `runtime list` and `runtime status` on top of the shared engine manifest/status.

2. PR B: checksum-verified managed runtime install prototype, if supply-chain review accepts checksum-only for local explicit installs.
   - Download the archive only after explicit user action.
   - Verify SHA256 before extraction.
   - Extract into the runtime cache.
   - Verify `llama-cli` exists and is executable.
   - Smoke `--version`.
   - Write selected runtime record.
   - Roll back on failure.
   - Label provenance as checksum-verified GitHub release asset, not independently signed.

3. PR C: Desktop runtime install/status UI, only after the engine install path is reviewed.
   - Show missing/stale/selected runtime state.
   - Add explicit install recommended runtime action.
   - Render download/verify/select progress and provenance.
   - Keep select-existing as advanced.

4. PR D: v0.2.2 release promotion if PRs A-C produce a coherent, honest managed runtime lane.
   - Bump version only in the release PR.
   - Include managed-runtime install smoke, native first-run smoke using managed runtime, package smoke, token/privacy notes, and known limits.

If PR B is blocked by signature/provenance concerns, do not label v0.2.2 as complete. Land PR A only if it improves product truth, document the blocker, and continue to an independent v0.2.4 supportability slice or v0.2.5 release-hardening slice.

## Reviewer Checklist

- No Tauri/keychain/terminal rendering dependency enters `runner-engine`.
- Desktop remains an adapter over shared engine logic.
- CLI does not fork runtime-selection or native-first-run business logic.
- Runtime downloads are not silent and never auto-upgrade.
- Runtime manifest distinguishes checksum verification from independent signature verification.
- Docs/UI do not overclaim managed downloads, Windows/Linux, notarization, or decision-grade evidence.
- Docker/Podman remain optional advanced capabilities.
- Browser-visible Desktop state stays token-free.
- Tests include negative paths for unsafe/incomplete runtime manifest entries.

## Validation Plan

Use the relevant subset per PR:

```bash
cargo test --manifest-path crates/runner-engine/Cargo.toml --locked
cargo test --manifest-path apps/runner-cli/Cargo.toml --locked
cargo test --manifest-path apps/desktop-runner/src-tauri/Cargo.toml --locked
npm run check --prefix apps/desktop-runner
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
gitleaks detect --source=. --redact --no-banner --exit-code 0
git diff --check
```

For release promotion, run the full release validation set from `docs/codex_v0_2_1_sprint_planning.md`, plus a real runtime install/status smoke if v0.2.2 includes managed installation.

## Release Criteria

v0.2.2 can promote only if the release has a user-visible, reviewed, and validated runtime-management improvement that does not overclaim supply-chain strength. A manifest/status-only release is acceptable only if it clearly prepares the next install slice and documents why managed install remains blocked.
