# Runner v0.2.0 Baseline Audit

Date: 2026-05-06

This audit starts the v0.2.0 installer-and-go workstream from the released `0.1.38` baseline. Do not label any release `v0.2.0` until the native first-run acceptance criteria below are proven on a clean macOS Apple Silicon lane.

## Baseline

- Runner `origin/main`: `bb32c84ac94189aa122f4708665cdc84861fce34` (`Release Runner 0.1.38`).
- Runner `origin/develop`: `07b8200d654b1605ac11ee56484f2de33697de60`.
- `VERSION`: `0.1.38`.
- The root Cargo workspace exists and includes `apps/desktop-runner/sidecar`, `apps/desktop-runner/src-tauri`, `apps/runner-cli`, and `crates/runner-engine`.
- `crates/runner-engine` exists as the shared Rust engine crate.
- `apps/runner-cli` exists as an early Rust CLI frontend.
- `apps/desktop-runner` remains the Tauri frontend and adapter.
- Python runner-core still exists and remains the execution bridge for non-native-migrated work.

## Verified Healthy

- `runner-engine` has no Tauri, keychain, updater, shell, CLI, or terminal-rendering dependency. `cargo tree -p infergrade_runner_engine --locked` shows only `serde`, `serde_json`, `url`, and their transitive parsing/serialization dependencies.
- Desktop browser JavaScript does not have a `load_runner_token` Tauri command and only stores theme/API URL in `localStorage`.
- Pairing, pairing status, reset, listener start plans, worker protocol preview/ping, and redaction are covered by Rust/desktop tests.
- Runner tokens are saved through the Desktop `TokenStore` adapter and pairing/status payloads expose only sanitized profile/token presence.
- Workspace-root desktop artifact paths are used by the release workflow and tests: `target/release/bundle/...`.
- macOS local DMG build succeeds from the 0.1.38 baseline.
- The protected `release` GitHub environment has a `main` deployment branch policy.
- Gitleaks found no current leaks in the 0.1.38 baseline.

## Verified Blockers

1. No native first-run benchmark command exists yet.
   - `apps/runner-cli` only exposes `doctor`, `runtime plan`, and `help`.
   - `cargo run --manifest-path apps/runner-cli/Cargo.toml -- containers check` returns `unknown command`.
   - There is no `first-run` command, model path selection flow, typed benchmark progress stream, or upload path in the Rust CLI/Desktop stack.

2. The Desktop packaged execution bridge still requires a Python interpreter.
   - `tauri.conf.json` bundles `python/runner-core/src` as a resource, but the sidecar invokes it with `python3`/`python`.
   - Simulated no-Python smoke failed:
     ```bash
     env -i PATH=/nonexistent HOME="$HOME" \
       apps/desktop-runner/src-tauri/binaries/infergrade-sidecar-$(rustc -Vv | awk '/host:/ {print $2}') \
       desktop-self-test
     ```
     Result: `could not find a Python interpreter to run the bundled Runner core`.
   - This blocks the v0.2.0 requirement: no user-installed Python for first run.

3. Desktop readiness can overstate native first-run readiness.
   - `desktop-readiness` reports `native_benchmark_suite: ready` and `first_run: ready` when `llama-cli`/`llama-server` are present.
   - The actual native first-run benchmark executor is not implemented yet, so this should be tightened before public installer messaging.

4. Hub main is not code-first enough for the v0.2 Desktop path.
   - Current Hub `origin/main` still renders pairing guidance around copying/running the full pair command.
   - v0.2 needs code-first pairing in the release lane: pairing code first, Copy Code, Regenerate Code, and full CLI command behind advanced disclosure.

5. Public readiness is present only as a stale draft PR.
   - PR #107 (`[codex] Prepare runner for public release`) is draft and `CONFLICTING` against current `main`.
   - It adds useful public-readiness assets (`LICENSE`, `SECURITY.md`, issue templates, PR template, secret scan workflow, public release checklist), but must be refreshed/recreated before landing.

6. Windows/Linux installer-and-go is unproven.
   - Package smoke workflows exist and point to `target/release/bundle/...`, but clean install/launch and first-run behavior are not validated.
   - Until proven, Windows/Linux should remain preview/partial in docs and UI.

7. `cargo test --workspace --locked` fails in a fresh worktree until the desktop sidecar binary is generated.
   - Failure: Tauri build script cannot find `apps/desktop-runner/src-tauri/binaries/infergrade-sidecar-<target>`.
   - Running `./scripts/build_desktop_sidecar.sh` first resolves it.
   - This is manageable but should be made less surprising before v0.2 release gates.

8. Runtime management is still inspect/select oriented.
   - Runtime planning and manifest guardrails exist.
   - There is no app-managed Metal runtime provisioning lane yet, and no runtime download/install is enabled.
   - This is acceptable for 0.1.x, but v0.2 requires a proven Apple Silicon Metal runtime path that does not silently install or upgrade.

## Public-Readiness State

PR #107 should be superseded or rebased after the baseline audit lands. Required retained pieces:

- Apache-2.0 license metadata if still intended.
- `SECURITY.md`.
- `CONTRIBUTING.md` refresh.
- Issue templates and PR template.
- Gitleaks/secret scan workflow.
- Read-only workflow permissions by default.
- Public release checklist, including release-environment reviewer follow-up after public conversion if private-plan limits block reviewer enforcement.

Do not mix public-readiness with the v0.2 native first-run implementation. It can ship as a 0.1.x release.

## Proposed PR Sequence

1. Baseline audit and release-doc cleanup.
   - Add this audit.
   - Fix stale desktop artifact path documentation.
   - No product behavior change.

2. Refresh public readiness.
   - Recreate/supersede PR #107 from current `main`.
   - Land as 0.1.x if validation and review pass.

3. Tighten readiness truth.
   - Stop reporting `first_run: ready` solely because `llama-cli` and `llama-server` exist.
   - Distinguish runtime readiness from implemented first-run executor readiness.
   - Add tests for truthful no-executor state.

4. Add shared container detection to `runner-engine`.
   - Model Docker/Podman detection in engine.
   - Add `infergrade-runner containers check`.
   - Keep Docker/Podman optional and advanced.

5. Write the first-run execution strategy decision record.
   - Choose Rust-native first-run for v0.2 macOS Apple Silicon unless investigation finds a lower-risk packaged Python bridge that truly avoids external Python.
   - Keep Python runner-core as legacy/advanced bridge.

6. Implement native first-run benchmark skeleton in `runner-engine`.
   - Types for model path, runtime path, benchmark result, metrics, and events.
   - No upload in the first slice.
   - Tests with a fake runtime command.

7. Add CLI `first-run`.
   - `infergrade-runner first-run --model ./model.gguf --runtime auto --no-upload`.
   - JSON/JSONL output mode.
   - Writes local result artifact to `--output-dir`.

8. Add Desktop first-run adapter.
   - Model picker/confirmation.
   - Runs the engine first-run path.
   - Streams typed progress events.
   - Shows success/failure and next step.

9. Add Hub-compatible evidence/upload.
   - Use existing bundle/upload contracts if sufficient.
   - Otherwise make minimal Runner contract and Hub ingestion changes.
   - Keep first-run evidence distinct from sample/demo/reference evidence.

10. Add app-managed Apple Silicon Metal runtime lane.
    - Provenance, checksum/signature manifest, compatibility, rollback metadata.
    - No silent runtime install/upgrade.
    - Clean diagnostics when runtime is absent.

11. Package/fresh-machine smoke.
    - macOS Apple Silicon clean-environment proof: no Docker, no Python, no Rust, no global infergrade, no repo checkout, no terminal.
    - Windows/Linux remain preview unless equivalent proof exists.

## Validation Evidence

Commands run against `/Users/brianfogelson/Desktop/Code/infergrade/.worktrees/runner-v0.2-baseline-audit`:

```bash
git rev-parse HEAD origin/main
cargo tree -p infergrade_runner_engine --locked
npm install --prefix apps/desktop-runner
npm run check --prefix apps/desktop-runner
./scripts/test_all.sh
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
bash -n scripts/build_desktop_runner.sh scripts/notarize_desktop_dmg.sh scripts/verify_desktop_macos_release.sh
ruby -e 'require "yaml"; ARGV.each { |f| YAML.load_file(f); puts "ok #{f}" }' .github/workflows/*.yml
git diff --check
./scripts/build_desktop_sidecar.sh
cargo test --workspace --locked
cargo test --manifest-path crates/runner-engine/Cargo.toml --locked
cargo test --manifest-path apps/runner-cli/Cargo.toml --locked
cargo test --manifest-path apps/desktop-runner/sidecar/Cargo.toml --locked
./scripts/build_desktop_runner.sh --check-only
cargo run --manifest-path apps/runner-cli/Cargo.toml -- --help
cargo run --manifest-path apps/runner-cli/Cargo.toml -- doctor --api-url api.infergrade.com
cargo run --manifest-path apps/runner-cli/Cargo.toml -- runtime plan
cargo run --manifest-path apps/runner-cli/Cargo.toml -- containers check || true
apps/desktop-runner/src-tauri/binaries/infergrade-sidecar-$(rustc -Vv | awk '/host:/ {print $2}') --version
apps/desktop-runner/src-tauri/binaries/infergrade-sidecar-$(rustc -Vv | awk '/host:/ {print $2}') desktop-self-test
apps/desktop-runner/src-tauri/binaries/infergrade-sidecar-$(rustc -Vv | awk '/host:/ {print $2}') desktop-readiness
gitleaks detect --source=. --redact --no-banner --exit-code 0
./scripts/build_desktop_runner.sh
```

Notable outputs:

- Full Python runner-core suite: `Ran 235 tests ... OK`.
- Desktop web check: Node tests passed and Vite build succeeded.
- `cargo test --workspace --locked`: passed after generating the sidecar.
- Full local macOS DMG artifact:
  `target/release/bundle/dmg/InferGrade Runner_0.1.38_aarch64.dmg`.
- DMG SHA-256:
  `134cc383d87227249aac30fd4fbaf5b6d908851db9e1f586bcf7d697ffeed692`.
- Gitleaks: `no leaks found`.

## v0.2.0 Non-Claim

The 0.1.38 baseline is a healthy control-plane/release baseline, but it is not installer-and-go native first-run. The missing native first-run executor, external Python dependency, code-first Hub pairing gap, and unproven runtime provisioning are release blockers for v0.2.0.
