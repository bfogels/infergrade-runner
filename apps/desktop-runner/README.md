# InferGrade Desktop Runner

InferGrade Desktop Runner is the local companion app for people who want to pair a machine, keep the Runner process alive, inspect logs, and recover from local setup problems without using a terminal.

The Hub remains the model selection, benchmark planning, recommendation, and results surface. This app should stay focused on pairing, readiness, Runner lifecycle, local runtime controls, logs, updates, and support export.

## What It Includes

- Tauri 2 desktop shell with a vanilla JavaScript frontend
- Sidecar wrapper for the existing `infergrade` CLI
- Pair-code redemption through the sidecar
- Start, stop, status, and log streaming controls for the local Runner process
- OS-backed token storage through the Rust `keyring` crate
- System, light, and dark UI modes
- Advanced `llama.cpp` runtime inspection and selection controls
- Signed Tauri updater wiring for the macOS release lane

## Local Development

Install JavaScript dependencies:

```bash
npm install
```

Run the browser preview:

```bash
npm run dev
```

Run the Tauri shell after installing Rust and platform prerequisites:

```bash
npm run tauri dev
```

The macOS Apple Silicon sidecar wrapper lives at:

```text
src-tauri/binaries/infergrade-sidecar-aarch64-apple-darwin
```

The sidecar first tries `infergrade` from `PATH`. If that is unavailable, it uses `INFERGRADE_RUNNER_REPO` or walks back to the Runner repo root and runs `python3 -m infergrade` with `python/runner-core/src` on `PYTHONPATH`.

## Runtime Selection

The app does not install or upgrade `llama.cpp` silently. The Runtime panel shells out through the existing CLI:

```text
infergrade install-runtime --runtime llama.cpp
infergrade install-runtime --runtime llama.cpp --runtime-id <runtime id>
infergrade install-runtime --runtime llama.cpp --select-existing
```

The default path stays on the Runner-pinned compatibility lane. Advanced support sessions can inspect a named runtime lane or select an existing `llama-cli` / `llama-server` binary.

## Build And Release

Build a local macOS DMG with:

```bash
./scripts/build_desktop_runner.sh
```

Local macOS builds default to ad-hoc code signing (`INFERGRADE_MACOS_SIGNING_IDENTITY=-`). This produces a sealed app bundle that passes local `codesign --verify --deep --strict`; it is not a substitute for Developer ID signing and notarization for public distribution.

Build macOS updater artifacts with:

```bash
TAURI_SIGNING_PRIVATE_KEY="$(cat ~/.tauri/infergrade-runner/infergrade-runner-updater.key)" \
TAURI_SIGNING_PRIVATE_KEY_PASSWORD="..." \
./scripts/build_desktop_runner.sh --with-updater
```

Tauri updater signing is separate from Apple code signing:

- `TAURI_SIGNING_PRIVATE_KEY` and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` sign the updater archive.
- `INFERGRADE_MACOS_SIGNING_IDENTITY=-` creates a local ad-hoc macOS signature.
- `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_ID`, `APPLE_PASSWORD`, and `APPLE_TEAM_ID` allow CI to use Developer ID signing and notarization when available.

The release workflow publishes the latest desktop release manifest at:

```text
https://github.com/bfogels/infergrade-runner/releases/download/desktop-runner-latest/infergrade-runner-desktop-latest.json
```

For nontechnical beta users, the macOS DMG should be Developer ID signed and notarized. Ad-hoc signed DMGs are appropriate for local development and internal smoke testing only.

If a downloaded DMG opens with the macOS "`InferGrade Runner.app` is damaged and can't be opened" dialog, discard that artifact and rebuild it through the protected release workflow. Do not ask users to bypass Gatekeeper; the release candidate must be Developer ID signed, notarized, and verified on a clean macOS machine.

## Windows And Linux

The current checked-in sidecar is macOS Apple Silicon only:

```text
src-tauri/binaries/infergrade-sidecar-aarch64-apple-darwin
```

Windows and Linux packaging need matching platform sidecars before those builds can be shipped. Tauri expects the same logical sidecar name with platform-specific suffixes. Once those sidecars exist, the next distribution decision is whether MSI/NSIS, AppImage, or `.deb` is the first beta lane.

## Sidecar Contract

The primary UI redeems the one-time Hub pairing code with:

```text
infergrade pair --api-url <hub url> --pair-code <pairing code> --label <runner label>
```

On success, the CLI saves the durable runner profile and the app starts:

```text
infergrade start --api-url <hub url>
```

The app does not log the raw `pair` JSON because that response contains the durable runner token. The browser preview does not persist tokens; the live app stores fallback tokens in the OS credential store and can pass `INFERGRADE_HUB_TOKEN` through the process environment.
