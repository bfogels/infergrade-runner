# Codex v0.2.0 Completion Sprint Planning

Date: 2026-05-06

This is the live Codex planning file for the Runner v0.2.0 installer-and-go completion sprint. Keep it honest: do not relabel Runner as v0.2.0 until the Desktop install, pair, native first-run, upload, and Hub evidence loop has been proven.

## Current Branch State

- Runner `origin/main`: `d2f31b82a334d26f949c0a5e26a656d896f9174a` (`0.1.45`, PR #126).
- Runner `origin/develop`: `96d4f28b25a2e4721d329dc4676d65523cab3f92`.
- Runner open PRs: none after #139 landed.
- Runner recent develop train:
  - #127 Add CLI first-run local artifact output.
  - #128 Harden native command first-run boundary.
  - #129 Add built-in llama.cpp first-run adapter.
  - #130 Add first-run progress events.
  - #131 Add Desktop native first-run adapter.
  - #132 Share native first-run artifact writing.
  - #133 Add native first-run bundle preview.
  - #134 Add run-scoped bundle upload request builder.
  - #135 Add native Hub JSON executor.
  - #136 Add explicit CLI native first-run upload.
  - #137 Add Desktop native first-run upload adapter.
  - #138 Prefill Desktop first-run Hub handoff.
  - #139 Harden llama.cpp native first-run proof.
- Runner `main` does not contain the develop train after #126. v0.2.0 has not landed.
- Hub `origin/main`: `fd9a70ee4ed37196eae3a804446e7f5dca3c52cc`, including PR #203 (`Promote develop pairing UX to main`) and PR #204 (`Keep native first-run evidence informational`).
- Hub open PRs: none at sprint start.
- Hub code-first pairing is present on `main`: pairing code, regenerate, status polling, and advanced CLI command disclosure exist in `apps/web/app.js`.

## Completed v0.2.0 Criteria

- Hub pairing UX is code-first on the release lane.
- Shared `runner-engine` owns native first-run inputs/results, typed events, local artifact writer, bundle-preview writer, run-scoped upload request builders, and native Hub JSON executor.
- CLI can run local native first-run with `--no-upload`.
- CLI can explicitly upload native first-run evidence with a run-scoped token and complete the run.
- Desktop can run the native first-run engine and write local result and bundle-preview artifacts.
- Desktop can upload native first-run evidence for a Hub run handoff; Rust loads the saved token and JS never receives an upload token field.
- Hub keeps native first-run evidence experimental, informational-only, and private to the run owner across the tested read surfaces.
- Built-in llama.cpp first-run now avoids unbounded preview scans, redacts prompt echoes, prefers the sibling `llama-completion` measurement binary when available, requests Apple Silicon Metal offload, exits after a single turn, and rejects summary-only output when an observed token count is missing.
- Docker/Podman remain optional advanced capabilities in readiness surfaces.
- Token tests cover pairing, worker previews, Hub request previews, Hub executor errors, and CLI upload output redaction.

## Remaining Blockers

1. Normal Hub-to-Desktop run handoff is incomplete.
   - Desktop can prefill upload run ids from URL query parameters, but packaged Desktop did not yet register an app URL scheme at this refresh.
   - In progress on `codex/runner-v020-deep-link-handoff`: register `infergrade-runner://` and consume token-free first-run handoff URLs.

2. Desktop upload needs full end-to-end smoke.
   - The normal browser-to-packaged-Desktop path still needs validation with a real run, real saved token, real local artifact, and Hub evidence display.

3. Runtime selection/provisioning is not yet installer-and-go.
   - A real Apple Silicon Metal CLI smoke succeeded using `/opt/homebrew/bin/llama-cli` and `/Users/brianfogelson/Desktop/Code/ext/models/open_llama_3b_v2/ggml-model-f16-q4_0.gguf`.
   - v0.2.0 still needs proof that the normal Desktop path can find/use a selected or app-managed runtime without PATH assumptions.

4. Hub evidence display for uploaded native-first-run evidence needs browser validation.
   - Hub API tests prove privacy and informational labeling, but the visual evidence/recommendation surfaces still need an end-to-end smoke with uploaded native-first-run evidence.

5. Package/fresh-machine proof is missing.
   - No clean macOS Apple Silicon proof yet for: no Docker, no user Python, no Rust, no global CLI, no repo checkout, no terminal, no `INFERGRADE_RUNNER_REPO`.

6. Release docs and UI support labels still need a final honesty pass.
   - Windows/Linux should remain preview unless package proof exists.
   - Runtime downloads/provisioning should not be overclaimed.

## Planned PR Sequence

1. Land `codex/runner-v020-deep-link-handoff`.
   - Register the packaged Desktop `infergrade-runner://` URL scheme.
   - Accept token-free Hub handoff URLs and prefill only run/worker IDs.
   - Keep upload token loading inside Rust/Tauri.

2. Add Hub first-run open/copy handoff URL.
   - After a local native run is queued, emit/open `infergrade-runner://first-run?...`.
   - Keep manual run ID/token machinery out of the normal Hub flow.
   - Assert the browser never receives upload tokens in the handoff.

3. Runtime selection without Python/PATH assumptions.
   - Move selected existing llama.cpp runtime selection into `runner-engine`.
   - Let Desktop and Rust CLI select or inspect the runtime without shelling to Python runner-core.
   - Keep downloads/provisioning explicit and provenance-gated.

4. Desktop + Hub end-to-end first-run upload smoke.
   - Use a real paired Desktop profile, Hub handoff run ID, selected runtime, and GGUF.
   - Confirm artifact path, upload status, Hub owner-visible evidence, and public/private boundaries.

5. macOS package candidate validation.
   - Build sidecar and Desktop package.
   - Run clean-environment package smoke as far as current machine allows.

6. Release promotion decision.
   - If all v0.2.0 gates are met, open `develop -> main`, bump to `0.2.0`, run full validation, and spawn release reviewer.
   - If any core promise remains unproven, keep work on `develop` and document the blocker instead of promoting.

## Validation Evidence

Current live checks before this file:

- Runner open PR list: none.
- Hub open PR list: none.
- Runner `origin/main` version: `0.1.45`.
- Runner `origin/develop` version: `0.1.45`.
- Hub `origin/main` includes PR #203 code-first pairing and PR #204 native-first-run evidence/privacy helpers.
- Previous develop PR validations were local because GitHub Actions jobs were blocked before execution by account billing/spending-limit annotations.
- #137 local checks included `npm run check --prefix apps/desktop-runner`, desktop sidecar build, runner-engine/CLI/Desktop cargo tests, Python desktop capability unittest, CLI help, gitleaks, and `git diff --check`.
- #138 local checks included `npm ci --prefix apps/desktop-runner`, `npm run check --prefix apps/desktop-runner`, desktop sidecar build, runner-engine/CLI/Desktop cargo tests, Python desktop capability unittest, CLI help, gitleaks, and `git diff --check`.
- #139 local checks:
  - `cargo test --manifest-path crates/runner-engine/Cargo.toml --locked`: pass.
  - Real native CLI smoke: `cargo run --manifest-path apps/runner-cli/Cargo.toml -- first-run --model /Users/brianfogelson/Desktop/Code/ext/models/open_llama_3b_v2/ggml-model-f16-q4_0.gguf --runtime auto --runtime-path /opt/homebrew/bin/llama-cli --prompt PRIVATE_PROMPT_DO_NOT_SHOW_12345 --max-tokens 4 --no-upload --output-dir /tmp/infergrade-pr139-prompt-echo --json`: pass, produced `/tmp/infergrade-pr139-prompt-echo/native-first-run-result.json`, loaded Metal backend through `llama-completion`, did not persist the exact prompt, and reported 3 observed eval tokens at about 27.8 tokens/sec.
- `codex/runner-v020-deep-link-handoff` local checks so far:
  - `node --test apps/desktop-runner/src/static.test.mjs`: pass after adding deep-link handoff guards.
  - `npm run check --prefix apps/desktop-runner`: pass.

## Reviewer Findings

- #133 reviewer caught backend provenance overclaim; fixed by keeping native preview backend version unverified and `backend_version_pinned: false`.
- #134 reviewer caught path-id trim/embedding mismatch; fixed by returning and using validated ids.
- #135 reviewer caught response Debug and redact-after-truncate token leaks; fixed with manual Debug and redact-before-truncate tests.
- #136 reviewer found no blockers and approved CLI run-scoped upload.
- #137 reviewer caught upload failure being allowed to mask successful local artifact creation; fixed by preserving result success and reporting upload failure separately.
- #138 reviewer caught stale worker handoff reuse; fixed by clearing old worker IDs when a new run-only handoff arrives.
- #139 reviewer caught prompt echo leakage and generated-token overclaim; fixed by exact prompt redaction, sibling `llama-completion` preference, and rejecting summary-only output without observed token counts.

## Release-Gate Status

Not ready for v0.2.0.

The product has meaningful native first-run/upload primitives, and the Rust CLI can now complete a real local Apple Silicon Metal llama.cpp first-run with a GGUF model. Desktop end-to-end upload, visual Hub evidence validation, runtime selection without PATH assumptions, and package/fresh-machine proof remain release blockers.

v0.2.0 remains blocked until the full Desktop-Hub upload/evidence loop and macOS package proof are validated.
