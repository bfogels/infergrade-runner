# InferGrade Desktop Runner

InferGrade Desktop Runner is the local companion app for people who want to pair a machine, keep the Runner process alive, inspect logs, and recover from local setup problems without using a terminal.

The Hub remains the model selection, benchmark planning, recommendation, and results surface. This app should stay focused on pairing, readiness, Runner lifecycle, local runtime controls, logs, updates, and support export.

Docker is not required for your first local benchmark. The desktop happy path should pair, validate a native `llama.cpp` runtime, and start a first local run without asking the user to install Docker, Python, Rust, clone a repo, edit `PATH`, or use a terminal. Docker remains supported for advanced sandboxed benchmarks and container-friendly operator workflows.

## What It Includes

- Tauri 2 desktop shell with a vanilla JavaScript frontend
- Sidecar wrapper for the existing `infergrade` CLI
- Pair-code redemption through the sidecar
- Start, stop, status, and log streaming controls for the local Runner process
- OS-backed token storage through the Rust `keyring` crate
- System, light, and dark UI modes
- Advanced `llama.cpp` runtime inspection and selection controls
- Signed Tauri updater wiring for the macOS release lane
- Source-built sidecar wrapper that can emit Tauri platform-specific binaries for macOS, Windows, and Linux build hosts

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

Build the platform-specific sidecar wrapper for the current Rust host with:

```bash
../../scripts/build_desktop_sidecar.sh
```

Tauri expects the generated file to use the target-triple suffix, for example `src-tauri/binaries/infergrade-sidecar-aarch64-apple-darwin` on Apple Silicon macOS or `src-tauri/binaries/infergrade-sidecar-x86_64-pc-windows-msvc.exe` on 64-bit Windows. Packaged builds include the Runner core source as a Tauri resource and the sidecar prefers that bundled/app-managed path. Development builds can still fall back to `INFERGRADE_RUNNER_REPO`, walking back to the Runner repo root, or finally `infergrade` from `PATH`.

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
- `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, and `APPLE_TEAM_ID` allow CI to use Developer ID signing.
- Either `APPLE_ID` plus `APPLE_PASSWORD` or `APPLE_API_KEY`, `APPLE_API_ISSUER`, and `APPLE_API_PRIVATE_KEY` allow CI to notarize protected release artifacts.
- `INFERGRADE_MACOS_SIGNING_IDENTITY` can be configured as a release environment variable; CI also accepts the `APPLE_SIGNING_IDENTITY` secret for the same value.

Public release credentials should be configured only in the protected GitHub `release` environment. Do not copy Apple certificates, notary credentials, Tauri updater keys, or passwords into repository-level secrets, local docs, screenshots, or checked-in config files.

If CI reports that `APPLE_CERTIFICATE` could not be opened with `APPLE_CERTIFICATE_PASSWORD`, re-export the Developer ID Application certificate as a password-protected `.p12`, verify it locally with `openssl pkcs12 -passin env:APPLE_CERTIFICATE_PASSWORD`, then update the certificate and password secrets together in the protected GitHub release environment.

The release workflow publishes the latest desktop release manifest at:

```text
https://github.com/bfogels/infergrade-runner/releases/download/desktop-runner-latest/infergrade-runner-desktop-latest.json
```

For nontechnical beta users, the macOS DMG should be Developer ID signed and notarized. Ad-hoc signed DMGs are appropriate for local development and internal smoke testing only.

If a downloaded DMG opens with the macOS "`InferGrade Runner.app` is damaged and can't be opened" dialog, discard that artifact and rebuild it through the protected release workflow. Do not ask users to bypass Gatekeeper; the release candidate must be Developer ID signed, notarized, and verified on a clean macOS machine.

## Windows And Linux

The sidecar source can now generate matching platform sidecars on Windows and Linux build hosts. Windows and Linux packaging still need successful package attempts before those builds can be shipped. The next distribution decision is whether MSI/NSIS, AppImage, or `.deb` is the first beta lane, plus the matching signing and launch-smoke gate for each platform.

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

Run the startup self-test from the Runtime status panel, or directly with:

```text
infergrade-sidecar desktop-self-test
```

The self-test reports whether the desktop app can find its bundled/app-managed Runner core without relying on a globally installed `infergrade` command.
