# Codex v0.2.1 Sprint Planning

Date: 2026-05-06

## Branch State

- Runner `origin/main`: v0.2.0 at `33e7a44b9a081abd088e1ea269e253d583649307`.
- Runner `origin/develop`: synced to `origin/main` after v0.2.0 promotion.
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

1. PR A: post-release review and v0.2.1 sprint plan docs.
2. PR B: CLI upload credential naming/profile-token cleanup.
3. PR C: package smoke script/runbook.
4. PR D: Desktop first-run smoke/static test improvements.
5. PR E: v0.2.1 release bump and promotion if the train is coherent.

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
