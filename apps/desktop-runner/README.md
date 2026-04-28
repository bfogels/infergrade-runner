# InferGrade Desktop Runner Prototype

Sprint 72 preserves this prototype as the proposed starting point for the Runner companion app.

The app is intentionally small:

- Tauri 2 desktop shell
- vanilla JavaScript frontend
- sidecar wrapper that launches the existing `infergrade` CLI
- process controls for start, stop, status, and log streaming
- OS-backed token storage through the Rust `keyring` crate

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

Sprint 73 should continue by running `npm run tauri dev`, exercising the Keychain prompt on macOS, and adding a Windows or Linux build attempt before any beta distribution.

## Sidecar Contract

The UI starts the sidecar with:

```text
infergrade start --api-url <hub url>
```

If a token is present, the prototype passes it through `INFERGRADE_HUB_TOKEN`. That keeps token handling outside command arguments, but it is still prototype-only token handling and does not replace OS-backed secure storage.

## Next Checks

1. Install Rust and platform prerequisites.
2. Run `npm run tauri dev`.
3. Confirm start/stop leaves no orphaned Runner processes.
4. Add secure storage.
5. Build a macOS package.
6. Attempt one Windows or Linux build artifact.
