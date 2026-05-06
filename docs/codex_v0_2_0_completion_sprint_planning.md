# Codex v0.2.0 Completion Sprint Planning

Date: 2026-05-06

This is the live Codex planning file for the Runner v0.2.0 installer-and-go completion sprint. Keep it honest: do not relabel Runner as v0.2.0 until the Desktop install, pair, native first-run, upload, and Hub evidence loop has been proven.

## Current Branch State

- Runner `origin/main`: `d2f31b82a334d26f949c0a5e26a656d896f9174a` (`0.1.45`, PR #126).
- Runner `origin/develop`: `ff3c637b98d1392ed4ce44b3b68c514741004db8`.
- Runner open PRs: none at sprint start.
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
- Runner `main` does not contain the develop train after #126. v0.2.0 has not landed.
- Hub `origin/main`: `52e73d5182ea37a88da1ce977d5432e078a7d3d1`, including PR #203 (`Promote develop pairing UX to main`).
- Hub open PRs: none at sprint start.
- Hub code-first pairing is present on `main`: pairing code, regenerate, status polling, and advanced CLI command disclosure exist in `apps/web/app.js`.

## Completed v0.2.0 Criteria

- Hub pairing UX is code-first on the release lane.
- Shared `runner-engine` owns native first-run inputs/results, typed events, local artifact writer, bundle-preview writer, run-scoped upload request builders, and native Hub JSON executor.
- CLI can run local native first-run with `--no-upload`.
- CLI can explicitly upload native first-run evidence with a run-scoped token and complete the run.
- Desktop can run the native first-run engine and write local result and bundle-preview artifacts.
- In progress on `codex/runner-v020-desktop-upload`: Desktop can opt into a run-scoped native first-run upload by providing a Hub run ID; Rust loads the saved token and JS never receives an upload token field.
- Docker/Podman remain optional advanced capabilities in readiness surfaces.
- Token tests cover pairing, worker previews, Hub request previews, Hub executor errors, and CLI upload output redaction.

## Remaining Blockers

1. Desktop upload is not fully productized.
   - The current branch wires an explicit run-scoped upload adapter, but normal Hub-to-Desktop run handoff still needs to provide/preserve the run ID without asking the user to paste it manually.
   - The upload path still needs end-to-end validation against Hub and evidence display surfaces.

2. Real Apple Silicon Metal proof is missing.
   - Built-in llama.cpp adapter exists, but no current validation has run with a real GGUF model and real Metal `llama-cli`.
   - Runtime path may be selected/app-managed, but v0.2.0 needs proof that the normal Desktop path can find/use it without PATH assumptions.

3. Hub evidence display for uploaded native-first-run evidence is not yet validated.
   - Hub can validate/upload bundles through existing run-scoped routes, but the visual evidence/recommendation surfacing for native-first-run uploads needs an end-to-end smoke.

4. Package/fresh-machine proof is missing.
   - No clean macOS Apple Silicon proof yet for: no Docker, no user Python, no Rust, no global CLI, no repo checkout, no terminal, no `INFERGRADE_RUNNER_REPO`.

5. Release docs and UI support labels still need a final honesty pass.
   - Windows/Linux should remain preview unless package proof exists.
   - Runtime downloads/provisioning should not be overclaimed.

## Planned PR Sequence

1. Desktop run-scoped native first-run upload adapter.
   - Base: `origin/develop`.
   - Add Tauri command/UI fields for explicit run id/upload action or clear upload-unavailable state if no run token exists.
   - Rust loads token through `DesktopTokenStore`; JS never sees token.
   - Use shared engine upload request builders and executor.
   - Keep upload status and errors user-safe.

2. Hub local validation smoke for native-first-run upload evidence.
   - Prefer no product changes if existing Hub ingestion is sufficient.
   - Add narrow Hub test only if native-first-run evidence needs label/display support.

3. Real runtime/model validation and docs.
   - Locate or select a small supported GGUF and real `llama-cli`.
   - Run CLI and Desktop first-run smoke where possible.
   - Document missing local prerequisites honestly if not available.

4. macOS package candidate validation.
   - Build sidecar and Desktop package.
   - Run clean-environment package smoke as far as current machine allows.

5. Release promotion decision.
   - If all v0.2.0 gates are met, open `develop -> main`, bump to `0.2.0`, run full validation, and spawn release reviewer.
   - If any core promise remains unproven, keep work on `develop` and document the blocker instead of promoting.

## Validation Evidence

Current live checks before this file:

- Runner open PR list: none.
- Hub open PR list: none.
- Runner `origin/main` version: `0.1.45`.
- Runner `origin/develop` version: `0.1.45`.
- Hub `origin/main` includes PR #203 and code-first pairing helpers.
- Previous develop PR validations were local because GitHub Actions jobs were blocked before execution by account billing/spending-limit annotations.
- `codex/runner-v020-desktop-upload` local checks so far:
  - `npm run check --prefix apps/desktop-runner`: pass.
  - `cargo test --manifest-path crates/runner-engine/Cargo.toml --locked`: pass.
  - `cargo test --manifest-path apps/runner-cli/Cargo.toml --locked`: pass.
  - `cargo test --manifest-path apps/desktop-runner/src-tauri/Cargo.toml --locked`: pass.

## Reviewer Findings

- #133 reviewer caught backend provenance overclaim; fixed by keeping native preview backend version unverified and `backend_version_pinned: false`.
- #134 reviewer caught path-id trim/embedding mismatch; fixed by returning and using validated ids.
- #135 reviewer caught response Debug and redact-after-truncate token leaks; fixed with manual Debug and redact-before-truncate tests.
- #136 reviewer found no blockers and approved CLI run-scoped upload.

## Release-Gate Status

Not ready for v0.2.0.

The product has meaningful native first-run/upload primitives, but Desktop upload, real Apple Silicon Metal proof, Hub evidence display validation, and package/fresh-machine proof remain release blockers.

Desktop upload is moving from "not wired" to "explicit run-scoped adapter" on the current branch, but v0.2.0 remains blocked until the full Desktop-Hub upload/evidence loop and macOS package proof are validated.
