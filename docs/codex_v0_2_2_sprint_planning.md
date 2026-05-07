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

2. PR B: checksum-verified managed runtime install prototype.
   - Download the archive only after explicit user action.
   - Verify SHA256 before extraction.
   - Extract into the runtime cache.
   - Verify `llama-cli` exists and is executable.
   - Smoke `--version`.
   - Write selected runtime record.
   - Roll back on failure.
   - Label provenance as checksum-verified GitHub release asset, not independently signed.
   - Status: implementation PR in progress after PR A landed. Local smoke installed the upstream `b9050` macOS arm64 runtime into a temporary cache, verified SHA-256, selected it, and ran native first-run against TinyLlama with `runtime_id=llama-cpp-b9050-macos-arm64-metal`.

3. PR C: Desktop runtime install/status UI, only after the engine install path is reviewed.
   - Show missing/stale/selected runtime state.
   - Add explicit install recommended runtime action.
   - Render download/verify/select progress and provenance.
   - Keep select-existing as advanced.
   - Status: in progress after PR B landed; first Desktop adapter slice adds an explicit install button and Tauri command over the shared engine installer.

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

## v0.2.2 Release Candidate Evidence

- Feature train landed in `develop`:
  - PR #150: managed runtime manifest/status groundwork.
  - PR #151: explicit checksum-verified managed runtime install and first-run runtime provenance.
  - PR #152: Desktop managed runtime install adapter/action.
- Release branch `codex/runner-v022-release` bumps version to `0.2.2` only after the feature PRs landed in `develop`.
- CI remained blocked by GitHub Actions jobs failing before steps/logs on feature PRs; local validation and reviewer approval were used for feature merges.

### Release Validation Snapshot

- `cargo test --workspace --locked` passed after rebuilding the Desktop sidecar for the Tauri bundle contract.
- Focused Rust gates passed:
  - `cargo test --manifest-path crates/runner-engine/Cargo.toml --locked`
  - `cargo test --manifest-path apps/runner-cli/Cargo.toml --locked`
  - `cargo test --manifest-path apps/desktop-runner/src-tauri/Cargo.toml --locked`
  - `cargo test --manifest-path apps/desktop-runner/sidecar/Cargo.toml --locked`
- Desktop web/package gates passed:
  - `npm ci --prefix apps/desktop-runner`
  - `npm run check --prefix apps/desktop-runner`
  - `./scripts/build_desktop_runner.sh --check-only`
  - `./scripts/build_desktop_runner.sh`
- Python/release compatibility gates passed:
  - `python3 -m unittest python/runner-core/tests/test_desktop_runner_capabilities.py python/runner-core/tests/test_release_ci.py`
  - `./scripts/test_all.sh`
  - `python3 ./scripts/sync_versions.py --check`
  - `python3 ./scripts/check_versions.py`
- Safety/format gates passed:
  - `gitleaks detect --source=. --redact --no-banner --exit-code 0`
  - `git diff --check`

### Managed Runtime Smoke

Release smoke used a fresh temporary `INFERGRADE_RUNTIME_CACHE_DIR`, installed the managed macOS arm64 Metal runtime, and ran native first-run with `--runtime auto` against the local TinyLlama GGUF model.

```text
install_runtime_id=llama-cpp-b9050-macos-arm64-metal
checksum_verified=True
signature_verified=False
server=True
perplexity=True
first_run_status=completed
first_run_runtime_id=llama-cpp-b9050-macos-arm64-metal
evidence_kind=native_first_run
generated_tokens=31
decode_tps=156.05
artifact=/tmp/infergrade-v022-first-run-release-72506/native-first-run-result.json
```

This proves the release branch can download, checksum-verify, extract, select, and use the managed runtime without Homebrew or PATH runtime discovery. It does not prove independent runtime signatures because upstream does not publish a separate signature asset for the selected archive.

### Local Package Smoke

`./scripts/build_desktop_runner.sh` emitted:

```text
artifact=target/release/bundle/dmg/InferGrade Runner_0.2.2_aarch64.dmg
size=7004499 bytes
sha256=c94f4eda1bd541053a828eea0ebd58b4e3beaa856673f37eae630ebaf0d4ea57
signing=ad-hoc local signing
notarization=skipped locally because Apple notarization credentials were not present
```

`scripts/smoke_desktop_dmg.sh --dmg "target/release/bundle/dmg/InferGrade Runner_0.2.2_aarch64.dmg"` passed:

```text
desktop_dmg_smoke=pass
desktop_dmg_codesign=pass
desktop_dmg_sidecar_version=infergrade 0.2.2
desktop_dmg_launch_observed=true
desktop_dmg_clean_path=/usr/bin:/bin
desktop_dmg_notarization=not_checked_by_local_smoke
```

The package smoke verifies the local DMG opens and carries the sidecar under a clean PATH. It does not replace public Developer ID signing, notarization, Gatekeeper, or clean-machine Desktop UI upload validation.
