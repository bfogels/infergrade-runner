# InferGrade Desktop Runner Prototype

Sprint 72 preserves this prototype as the proposed starting point for the Runner companion app.

The app is intentionally small:

- Tauri 2 desktop shell
- vanilla JavaScript frontend
- sidecar wrapper that launches the existing `infergrade` CLI
- pair-code redemption through the sidecar, then process controls for start, stop, status, and log streaming
- OS-backed token storage through the Rust `keyring` crate
- light/dark UI modes that follow the system preference until the user chooses one
- explicit managed `llama.cpp` runtime inspection and selection controls for advanced users

The Hub should remain the model, benchmark, recommendation, and result surface. This app should stay focused on pairing, readiness, Runner lifecycle, logs, and recovery.

## Local Development

Install the JavaScript dependencies:

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

The preserved macOS Apple Silicon sidecar wrapper lives at:

```text
src-tauri/binaries/infergrade-sidecar-aarch64-apple-darwin
```

It first tries `infergrade` from `PATH`. If that is unavailable, it uses `INFERGRADE_RUNNER_REPO` or walks back to the Runner repo root and runs `python3 -m infergrade` with `python/runner-core/src` on `PYTHONPATH`.

## Prototype Status

Verified in this PR:

- frontend builds through Vite
- Runner lifecycle UI renders without the Tauri runtime
- Tauri shell plugin is configured for the `binaries/infergrade-sidecar` sidecar
- sidecar command path matches `bundle.externalBin`
- sidecar wrapper can resolve the local Runner CLI and print `infergrade --help`
- Rust compile passes with `cargo check`
- macOS Apple Silicon DMG build completes locally
- token storage commands compile against the OS credential-store abstraction

Not yet verified in this PR:

- `npm run tauri dev`
- macOS Keychain save/load/clear through the live Tauri window
- Windows or Linux packaging

## Runtime Selection

The app intentionally does not install or upgrade `llama.cpp` silently. The Runtime panel shells out through the existing CLI:

```text
infergrade install-runtime --runtime llama.cpp
infergrade install-runtime --runtime llama.cpp --runtime-id <runtime id>
infergrade install-runtime --runtime llama.cpp --select-existing
```

That means a user can inspect the pinned managed runtime plan or select already-installed `llama-cli` / `llama-server` binaries without touching a terminal. A richer version picker is feasible, but it should wait until the Runner has a curated cross-platform runtime manifest with signed artifacts, compatibility labels, checksums, and rollback guidance.

The app now exposes an advanced runtime ID field. It intentionally defaults to blank so ordinary users stay on
the Runner-pinned compatibility lane, while support/debug sessions can inspect a named runtime lane when the
Runner manifest grows beyond the first Apple Silicon Homebrew entry.

## Release And Update Scripts

The package keeps platform bundle commands named even before every platform is distributable:

```bash
npm run build:mac
npm run build:windows
npm run build:linux
```

Only the macOS Apple Silicon lane currently has a checked-in sidecar. The Windows and Linux commands are
readiness targets for CI/build-machine work once matching sidecar artifacts and signing credentials exist.
Automatic app updates should use signed Tauri update artifacts only after OS code signing/notarization and the
Runner sidecar artifact matrix are in place.

## Windows And Linux Status

The current checked-in sidecar is macOS Apple Silicon only:

```text
src-tauri/binaries/infergrade-sidecar-aarch64-apple-darwin
```

Windows and Linux builds need matching sidecar binaries before they can be packaged or dogfooded. Tauri expects the same logical sidecar name with platform-specific suffixes, for example Windows and Linux artifacts generated from the same wrapper contract. After those exist, the next step is to add platform build attempts and record whether MSI/NSIS, AppImage, or `.deb` is the right first beta lane.

Sprint 73 should continue by running `npm run tauri dev`, exercising the Keychain prompt on macOS, and adding a Windows or Linux build attempt before any beta distribution.

## Sidecar Contract

The primary UI redeems the one-time Hub code with:

```text
infergrade pair --api-url <hub url> --pair-code <pairing code> --label <runner label>
```

On success, the CLI saves the durable runner profile and the app immediately starts:

```text
infergrade start --api-url <hub url>
```

The app does not log the raw `pair` JSON because that response contains the durable runner token. The browser preview does not persist tokens; the live app stores fallback tokens in the OS credential store and can pass `INFERGRADE_HUB_TOKEN` through the process environment. Environment variables should still be treated as process-local secrets.

## Next Checks

1. Install Rust and platform prerequisites.
2. Run `npm run tauri dev`.
3. Confirm start/stop leaves no orphaned Runner processes.
4. Redeem a real Hub pairing code, confirm the app starts listening, and confirm Hub readiness updates.
5. Exercise secure storage in a live Tauri window.
6. Build a macOS package.
7. Attempt one Windows or Linux build artifact.
