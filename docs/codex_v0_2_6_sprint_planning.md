# Codex v0.2.6 Sprint Planning

Date: 2026-05-07

## Branch State

- Runner `origin/main`: v0.2.5 at `1010e26`.
- Runner `origin/develop`: two reviewed v0.2.6 Desktop UX PRs ahead of `origin/main` at `251191c`.
- Runner open PRs at sprint start: none.
- Hub open PRs at sprint start: none checked for this Desktop-only slice.

## Release Goal

v0.2.6 should make the app -> runtime -> model -> Hub result loop easier for a normal Mac user to understand without changing the evidence claim.

Target user promise:

> The Desktop app tells me where I am in the first-run path and what the next safe action is.

## Planned PR Sequence

1. PR A: guided first-run checklist in Desktop.
   - Show the user journey as paired with Hub, managed/runtime selected, model selected, first-run ready, upload ready, and result available.
   - Reuse existing pairing/runtime/model/upload state.
   - Keep tokens out of browser-visible state.

2. PR B: first-run action polish if PR A lands cleanly.
   - Improve "Run again", "Run another model", "Retry upload", "Open result in Hub", and "Reveal artifact" affordances where supported by existing safe APIs.

3. PR C: v0.2.6 release promotion if the Desktop loop has a coherent reviewed improvement.

## Reviewer Checklist

- No upload, runner, bearer, paired runner, or Hub handoff token appears in browser state or copy.
- The checklist reflects existing state and does not imply a benchmark is decision-grade.
- Desktop remains an adapter; benchmark execution truth stays in `runner-engine`.
- Runtime install/update copy stays explicit and manual.
- Hub result availability is described only when an upload succeeds or when Hub supplies a result URL in a future safe payload.
- Tests cover stale/partial states rather than only happy paths.

## Validation Plan

Use the relevant subset per PR:

```bash
npm run check --prefix apps/desktop-runner
cargo test --manifest-path apps/desktop-runner/src-tauri/Cargo.toml --locked
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
gitleaks detect --source=. --redact --no-banner --exit-code 0
```

## Evidence Honesty Notes

- v0.2.6 is first-run UX polish, not a benchmark methodology or capability release.
- Native first-run remains smoke/informational evidence.
- A completed upload means a Hub run can receive the native-first-run bundle; it does not mean the result is public or decision-grade.
- Docker/Podman remain optional advanced support.

## Release Criteria

v0.2.6 can promote when a normal Mac user can understand the first-run loop state from the Desktop app without reading docs, and reviewer validation agrees the UI does not expand evidence claims.

## PR A Local Evidence

Branch: `codex/runner-v026-guided-checklist`
PR: #164, merged to `develop` as `45d38e2`.

Implemented:

- Added a Desktop "First-run path" checklist that tracks paired with Hub, runtime selected, model selected, first-run ready, upload ready, and result available.
- The checklist reuses existing state only: pairing status, runtime status, model input, local artifact availability, Hub run ID, and upload result.
- Fixed first-run/runtime field reads to use direct DOM element references because those inputs live outside the pairing form; this makes model selection and runtime ID state update in the actual Desktop page.
- Browser-visible copy continues to state that tokens stay out of the browser UI and that results become available only after successful upload.

Validation passed locally:

```bash
npm ci --prefix apps/desktop-runner
npm run check --prefix apps/desktop-runner
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
gitleaks detect --source=. --redact --no-banner --exit-code 0
./scripts/build_desktop_sidecar.sh
cargo test --manifest-path apps/desktop-runner/src-tauri/Cargo.toml --locked
```

Browser smoke:

- Playwright opened `http://127.0.0.1:1423/`.
- Desktop viewport rendered the new `First-run path` with all six steps and no page errors.
- Mobile viewport at `390px` had no horizontal overflow.
- Typing `/tmp/model.gguf` updated the model step to `done` and the local readiness model path text to the selected path.

## PR B Local Evidence

Branch: `codex/runner-v026-repeat-actions`
PR: #165, merged to `develop` as `251191c`.

Implemented:

- Added `Run again` and `Run another model` actions beside the existing first-run controls.
- `Run again` is available after a completed local first-run payload and reuses the existing native first-run path.
- `Run another model` clears local first-run result state and the model input without touching pairing, Hub handoff, or credential state.
- The buttons do not add Hub URLs, file reveal permissions, or browser-visible token surfaces.

Validation passed locally:

```bash
npm ci --prefix apps/desktop-runner
npm run check --prefix apps/desktop-runner
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
gitleaks detect --source=. --redact --no-banner --exit-code 0
```

Browser smoke:

- Playwright opened `http://127.0.0.1:1424/`.
- Typing `/tmp/model.gguf` marks the model step `done`.
- `Run another model` becomes enabled after model input is present; `Run again` remains disabled until a completed first-run payload exists.
- Mobile viewport at `390px` had no horizontal overflow.

## PR C Release Promotion

Branch: `codex/runner-v026-release`
PR: pending

Scope:

- Promote the reviewed v0.2.6 first-run UX polish slice from `develop` to `main`.
- Bump version declarations from `0.2.5` to `0.2.6` only in the release branch.
- Preserve the release boundary: Desktop first-run guidance and repeat actions, not benchmark methodology, capability scoring, Hub recommendation changes, or stronger evidence claims.

Branch-distance proof before release branch:

```bash
git rev-list --left-right --count origin/main...origin/develop
# 0 2

git diff --name-status origin/main...origin/develop
# M apps/desktop-runner/index.html
# M apps/desktop-runner/src/main.js
# M apps/desktop-runner/src/static.test.mjs
# M apps/desktop-runner/src/styles.css
# A docs/codex_v0_2_6_sprint_planning.md
```

Evidence honesty:

- v0.2.6 does not add benchmark methodology, capability lanes, public result claims, decision-grade evidence, Hub recommendation integration, or new upload/result tokens.
- `Open result in Hub` and `Reveal artifact` remain follow-ups until safe token-free result URLs and root-validated file reveal APIs exist.
- The first-run checklist reflects existing local state and does not change Runner-owned execution truth.

Validation passed locally on the release branch:

```bash
npm ci --prefix apps/desktop-runner
npm run check --prefix apps/desktop-runner
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
gitleaks detect --source=. --redact --no-banner --exit-code 0
./scripts/build_desktop_sidecar.sh
cargo test --manifest-path apps/desktop-runner/src-tauri/Cargo.toml --locked
```
