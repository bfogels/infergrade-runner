# Codex v0.2.0 Completion Sprint Planning

Date: 2026-05-06

This is the live Codex planning file for the Runner v0.2.0 installer-and-go completion sprint. Keep it honest: do not relabel Runner as v0.2.0 until the Desktop install, pair, native first-run, upload, and Hub evidence loop has been proven.

## Current Branch State

- Runner `origin/main`: `d2f31b82a334d26f949c0a5e26a656d896f9174a` (`0.1.45`, PR #126).
- Runner `origin/develop`: `b810cf359b5420c064e98e0e249d2c689b792746`.
- Runner open PRs: #141 (`Select existing llama runtime through runner engine`) into `develop`.
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
  - #140 Add Desktop first-run deep link handoff.
- Runner `main` does not contain the develop train after #126. v0.2.0 has not landed.
- Hub `origin/main`: `c9bb01b1e8566181365be94b2973fb1cb3807ec5`, including PR #203 (`Promote develop pairing UX to main`), PR #204 (`Keep native first-run evidence informational`), and PR #205 (`Open Desktop for native first-run handoff`).
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
- Packaged Desktop now registers `infergrade-runner://` and consumes token-free first-run handoff URLs from Hub.
- Hub now emits/opens token-free Desktop handoff URLs for local-native queues and requests no browser execution token for that normal path. Explicit advanced run-token minting remains available through the run execution-token endpoint.
- Docker/Podman remain optional advanced capabilities in readiness surfaces.
- Token tests cover pairing, worker previews, Hub request previews, Hub executor errors, and CLI upload output redaction.

## Remaining Blockers

1. Desktop upload needs full end-to-end smoke.
   - A real local Hub smoke now proves token-free run creation, runner-session claim, native first-run upload, run completion, owner-visible evidence, and public 404 privacy through the Rust CLI path.
   - The Desktop adapter uses the same runner-engine claim/upload/complete helpers and secure token-loading path; packaged app UI smoke is still needed.

2. Runtime selection/provisioning is not yet installer-and-go.
   - A real Apple Silicon Metal CLI smoke succeeded using `/opt/homebrew/bin/llama-cli` and `/Users/brianfogelson/Desktop/Code/ext/models/open_llama_3b_v2/ggml-model-f16-q4_0.gguf`.
   - In progress on PR #141: Desktop and Rust CLI can select an explicit existing llama.cpp runtime through `runner-engine` without shelling through Python. Managed downloads remain planned.

3. Hub evidence display for uploaded native-first-run evidence needs browser validation.
   - Hub API tests prove privacy and informational labeling, but the visual evidence/recommendation surfaces still need an end-to-end smoke with uploaded native-first-run evidence.

4. Package/fresh-machine proof is missing.
   - No clean macOS Apple Silicon proof yet for: no Docker, no user Python, no Rust, no global CLI, no repo checkout, no terminal, no `INFERGRADE_RUNNER_REPO`.

5. Release docs and UI support labels still need a final honesty pass.
   - Windows/Linux should remain preview unless package proof exists.
   - Runtime downloads/provisioning should not be overclaimed.

## Planned PR Sequence

1. Land PR #141: runtime selection without Python/PATH assumptions.
   - Move selected existing llama.cpp runtime selection into `runner-engine`.
   - Let Desktop and Rust CLI select or inspect the runtime without shelling to Python runner-core.
   - Keep downloads/provisioning explicit and provenance-gated.

2. Desktop + Hub end-to-end first-run upload smoke.
   - Land the claim-before-upload fix so token-free Hub handoff runs can complete through runner-session credentials.
   - Use a real paired runner profile, token-free Hub run ID, selected runtime, and GGUF.
   - Confirm artifact path, upload status, Hub owner-visible evidence, and public/private boundaries.

3. macOS package candidate validation.
   - Build sidecar and Desktop package.
   - Run clean-environment package smoke as far as current machine allows.

4. Release promotion decision.
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
- #140 reviewer added stricter handoff identifier validation, reran local checks, and landed #140 into `develop` as `b810cf359b5420c064e98e0e249d2c689b792746`.
- #205 Hub reviewer landed the Hub handoff/no-browser-token path into Hub `main` as `c9bb01b1e8566181365be94b2973fb1cb3807ec5`.
- PR #141 local checks so far:
  - `cargo test --manifest-path crates/runner-engine/Cargo.toml --locked`: pass.
  - `cargo test --manifest-path apps/runner-cli/Cargo.toml --locked`: pass.
  - `npm ci --prefix apps/desktop-runner`: pass.
  - `npm run check --prefix apps/desktop-runner`: pass.
  - `./scripts/build_desktop_sidecar.sh`: pass.
  - `cargo test --manifest-path apps/desktop-runner/src-tauri/Cargo.toml --locked`: pass after building the sidecar.
  - `cargo run --manifest-path apps/runner-cli/Cargo.toml -- runtime select-existing --runtime-path /opt/homebrew/bin/llama-cli`: pass; wrote canonical selected Homebrew llama.cpp binary paths to `~/.cache/infergrade/runtimes/llama.cpp/selected_runtime.json`.
  - Reviewer follow-up validation:
    - `cargo test --manifest-path crates/runner-engine/Cargo.toml --locked`: pass after rejecting non-executable/non-llama selections.
    - `cargo test --manifest-path apps/runner-cli/Cargo.toml --locked`: pass after updating CLI test runtime shim.
    - `cargo test --manifest-path apps/desktop-runner/src-tauri/Cargo.toml --locked`: pass after updating Desktop test runtime shim.
    - `npm run check --prefix apps/desktop-runner`: pass.
    - `cargo run --manifest-path apps/runner-cli/Cargo.toml -- runtime select-existing --runtime-path /etc/hosts; test $? -ne 0`: pass; `/etc/hosts` is rejected before selection.
    - `cargo run --manifest-path apps/runner-cli/Cargo.toml -- runtime select-existing --runtime-path /opt/homebrew/bin/llama-cli`: pass with runnable llama.cpp validation.
    - `gitleaks detect --source=. --redact --no-banner --exit-code 0`: pass.
  - `cargo fmt --all --check`: pass.
  - `git diff --check`: pass.
  - `gitleaks detect --source=. --redact --no-banner --exit-code 0`: pass.
- `codex/runner-v020-release-gates` local checks for the claim-before-upload fix:
  - `cargo test --manifest-path crates/runner-engine/Cargo.toml --locked`: pass; includes `build_run_claim_request` coverage.
  - `cargo test --manifest-path apps/runner-cli/Cargo.toml --locked`: pass; upload now posts claim, bundle, then completion.
  - `npm ci --prefix apps/desktop-runner`: pass.
  - `npm run check --prefix apps/desktop-runner`: pass after adding static assertion for Desktop claim wiring.
  - `./scripts/build_desktop_sidecar.sh`: pass.
  - `cargo test --manifest-path apps/desktop-runner/src-tauri/Cargo.toml --locked`: pass after building sidecar.
  - Real local Hub upload smoke using `/opt/homebrew/bin/llama-cli` and `/Users/brianfogelson/Desktop/Code/ext/models/open_llama_3b_v2/ggml-model-f16-q4_0.gguf`: pass. The smoke created a signed-in Hub user, created and redeemed a pairing code, queued a `local_native` run with `include_execution_token: false`, ran native first-run through the Rust CLI binary with the runner-session token, claimed the run, uploaded `nfr_unix1778117631_ggml_model_f16_q4_0`, completed the run, verified owner-visible result `nfr_unix1778117631_ggml_model_f16_q4_0_interactive_chat_v1`, verified public 404, and verified Recommend wizard `personal_informational_count: 1`.
  - `cargo fmt --all --check`: pass.
  - `git diff --check`: pass.
  - `gitleaks detect --source=. --redact --no-banner --exit-code 0`: pass.

## Reviewer Findings

- #133 reviewer caught backend provenance overclaim; fixed by keeping native preview backend version unverified and `backend_version_pinned: false`.
- #134 reviewer caught path-id trim/embedding mismatch; fixed by returning and using validated ids.
- #135 reviewer caught response Debug and redact-after-truncate token leaks; fixed with manual Debug and redact-before-truncate tests.
- #136 reviewer found no blockers and approved CLI run-scoped upload.
- #137 reviewer caught upload failure being allowed to mask successful local artifact creation; fixed by preserving result success and reporting upload failure separately.
- #138 reviewer caught stale worker handoff reuse; fixed by clearing old worker IDs when a new run-only handoff arrives.
- #139 reviewer caught prompt echo leakage and generated-token overclaim; fixed by exact prompt redaction, sibling `llama-completion` preference, and rejecting summary-only output without observed token counts.
- #140 reviewer caught unsafe handoff identifier acceptance; fixed by requiring safe Hub identifier-shaped run/worker values and rejecting token/secret/authorization/bearer-like values.
- #205 reviewer found no blockers and validated that normal local-native browser queueing returns no `execution_token` while explicit advanced minting still works.
- #141 reviewer caught runtime selection accepting arbitrary regular files such as `/etc/hosts` and mixing explicit CLI selections with PATH-discovered optional binaries. Fixed by requiring executable/runnable llama.cpp binaries before persisting selection and by resolving optional binaries from the explicit CLI sibling directory unless explicitly provided.
- Release-gate smoke caught that token-free Hub-created runs remained `awaiting_execution` while Desktop/CLI upload paths tried to complete without claiming first. Fixed by adding a shared `build_run_claim_request` helper and making CLI/Desktop claim the run with runner-session credentials before bundle upload and completion.

## Release-Gate Status

Not ready for v0.2.0.

The product has meaningful native first-run/upload primitives, and the Rust CLI can now complete a real local Apple Silicon Metal llama.cpp first-run with a GGUF model against a token-free Hub handoff run. Runtime selection without PATH assumptions is on `develop`; owner-visible Hub evidence display is validated through API/read-model smoke.

v0.2.0 remains blocked until packaged Desktop UI smoke and macOS package/fresh-environment proof are validated, and final release docs/UI honesty are updated.
