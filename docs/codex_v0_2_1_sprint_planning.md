# Codex v0.2.1 Sprint Planning

Date: 2026-05-06

## Branch State

- Runner `origin/main`: v0.2.0 at `33e7a44b9a081abd088e1ea269e253d583649307`.
- Runner `origin/develop`: contains the reviewed v0.2.1 stabilization train through PR #148.
- Hub `origin/main`: includes code-first pairing, token-free Desktop handoff, and native-first-run evidence honesty/visibility guardrails.
- Open Runner PRs at sprint start: none.

## Release Goal

v0.2.1 should stabilize the v0.2.0 promise instead of broadening it:

> Install app. Pair with Hub. Select or confirm a llama.cpp runtime. Select a GGUF model. Run native first-run. Upload evidence. See honest Hub results. No hidden Docker/Python/Rust/global CLI/repo-checkout dependency for normal Desktop users.

## Must-Fix

1. Scripted Desktop UI first-run smoke
   - Exercise token-free handoff parsing, paired-token loading boundary, model/runtime readiness, first-run progress, local artifact path, upload status, and success/failure state as far as local automation can.
   - Keep browser-visible state token-free.

2. CLI upload credential naming and UX
   - Rename or alias `--run-token` toward `--runner-token` / profile-token loading language without breaking existing debug workflows.
   - Help text must not imply a browser run token is required for normal handoff.

3. Runtime readiness copy and diagnostics
   - Make missing selected runtime failures extremely clear: native benchmark available, runtime selection required, no Docker needed.
   - Surface selected-runtime provenance and validation failure reasons without overwhelming users.

4. Package smoke runbook
   - Turn the v0.2.0 ad-hoc DMG smoke into a repeatable script or checklist that records artifact path, size, sha256, code signature, sidecar clean-PATH version, app launch, and cleanup.

## Should-Fix

- Add a Desktop support export field for native first-run readiness and selected-runtime manifest path.
- Add Hub browser visual smoke notes/screenshots for owner-visible native-first-run evidence.
- Add profile-token based CLI upload path so local/headless users do not need to put a token in argv.
- Improve selected-runtime compatibility warnings for old/missing `llama-completion` sibling binaries.

## Nice-To-Have

- Begin managed runtime manifest download design, but do not implement silent downloads.
- Add a small release-note template for scoped platform support.
- Add CI-safe smoke that skips gracefully when llama.cpp/model are unavailable.

## Proposed PR Sequence

1. PR A: post-release review and v0.2.1 sprint plan docs. Landed as PR #145.
2. PR B: CLI upload credential naming/profile-token cleanup. Landed as PR #146: prefer `--runner-token`, keep `--run-token` as a deprecated debug alias, and validate upload credentials before runtime execution.
3. PR C: package smoke script/runbook. Landed as PR #147: add repeatable local DMG mount/codesign/clean-PATH sidecar/app-launch smoke.
4. PR D: Desktop first-run smoke/static test improvements. Landed as PR #148: pin token-free handoff, secure Rust upload, progress/artifact rendering, and selected-runtime guidance with static tests.
5. PR E: v0.2.1 release bump and promotion. In progress on `codex/runner-v021-release`.

## Reviewer Checklist For v0.2.1 PRs

- No Tauri/keychain/terminal rendering dependency enters `runner-engine`.
- Desktop remains an adapter over shared engine logic.
- CLI does not fork native-first-run business logic.
- No browser-visible upload token or paired runner token.
- Evidence remains experimental/informational/needs-confirmation unless stronger gates are actually added.
- Docker/Podman stay optional for native first-run.
- Docs do not overclaim managed runtime downloads, Windows/Linux, or public notarization.
- Tests are meaningful and include negative/error paths where possible.

## Validation Plan

Use the relevant subset per PR, and full release validation before v0.2.1 promotion:

```bash
cargo test --workspace --locked
cargo test --manifest-path crates/runner-engine/Cargo.toml --locked
cargo test --manifest-path apps/desktop-runner/src-tauri/Cargo.toml --locked
cargo test --manifest-path apps/desktop-runner/sidecar/Cargo.toml --locked
cargo test --manifest-path apps/runner-cli/Cargo.toml --locked
npm ci --prefix apps/desktop-runner
npm run check --prefix apps/desktop-runner
python3 -m unittest python/runner-core/tests/test_desktop_runner_capabilities.py python/runner-core/tests/test_release_ci.py
./scripts/test_all.sh
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
./scripts/build_desktop_sidecar.sh
./scripts/build_desktop_runner.sh --check-only
./scripts/build_desktop_runner.sh
gitleaks detect --source=. --redact --no-banner --exit-code 0
git diff --check
```

## Release Criteria

v0.2.1 can promote to `main` when it improves release confidence without changing the scoped platform claim, has reviewer sign-off, and passes local validation. GitHub Actions billing/spending-limit failures may be documented if jobs still cannot start.

## v0.2.1 Release Candidate Evidence

- Version sync: `python3 ./scripts/sync_versions.py --check` and `python3 ./scripts/check_versions.py` pass with all checked versions at `0.2.1`.
- Rust tests:
  - `cargo test --workspace --locked`
  - `cargo test --manifest-path crates/runner-engine/Cargo.toml --locked`
  - `cargo test --manifest-path apps/desktop-runner/src-tauri/Cargo.toml --locked`
  - `cargo test --manifest-path apps/desktop-runner/sidecar/Cargo.toml --locked`
  - `cargo test --manifest-path apps/runner-cli/Cargo.toml --locked`
- Desktop web/package checks:
  - `npm ci --prefix apps/desktop-runner`
  - `npm run check --prefix apps/desktop-runner`
  - `./scripts/build_desktop_sidecar.sh`
  - `./scripts/build_desktop_runner.sh --check-only`
  - `./scripts/build_desktop_runner.sh`
- Python/repo checks:
  - `python3 -m unittest python/runner-core/tests/test_desktop_runner_capabilities.py python/runner-core/tests/test_release_ci.py`
  - `./scripts/test_all.sh`
- CLI smoke:
  - `cargo run --manifest-path apps/runner-cli/Cargo.toml -- --help`
  - `cargo run --manifest-path apps/runner-cli/Cargo.toml -- doctor --api-url api.infergrade.com`
  - `cargo run --manifest-path apps/runner-cli/Cargo.toml -- runtime plan`
  - `cargo run --manifest-path apps/runner-cli/Cargo.toml -- containers check || true`
- Real native first-run smoke:
  - Command: `cargo run --manifest-path apps/runner-cli/Cargo.toml -- first-run --model /Users/brianfogelson/Desktop/Code/ext/models/open_llama_3b_v2/ggml-model-f16-q4_0.gguf --runtime auto --runtime-path /opt/homebrew/bin/llama-cli --no-upload --max-tokens 4 --json --output-dir /tmp/infergrade-v021-release-cli-smoke`
  - Result: completed with `local_native` / `native_first_run`, `generated_tokens=3`, `decode_tokens_per_second=38.34`, `time_to_first_token_ms=1325`, `load_time_ms=1139`, artifact at `/tmp/infergrade-v021-release-cli-smoke/native-first-run-result.json`.
- Package smoke:
  - Artifact: `target/release/bundle/dmg/InferGrade Runner_0.2.1_aarch64.dmg`
  - Size: `6900725`
  - SHA256: `90755cdb91efc255d22ae8c978887d6087649fcf95a862cdb6371cf5613c8041`
  - `scripts/smoke_desktop_dmg.sh --dmg "target/release/bundle/dmg/InferGrade Runner_0.2.1_aarch64.dmg"` passed: DMG verified, app code signature verified, bundled sidecar reported `infergrade 0.2.1` under clean `PATH=/usr/bin:/bin`, app launch observed.
- Security/style:
  - `gitleaks detect --source=. --redact --no-banner --exit-code 0` found no leaks.
  - `git diff --check` passed.

## v0.2.1 Release Limits

- The local DMG smoke does not check notarization. The Tauri build emitted the expected local-build warning that no Apple notarization credentials were available.
- The real native smoke used explicit selected runtime path `/opt/homebrew/bin/llama-cli`; managed runtime downloads remain planned and disabled.
- A stale selected-runtime record pointing to a removed temp file makes `runtime auto` fail clearly before execution. That is recoverable by selecting a valid runtime or passing `--runtime-path`, and should be improved in a follow-up by surfacing stale-selection recovery more prominently.
- Windows/Linux remain preview/partial unless their package smoke and native runtime lanes are proven separately.
