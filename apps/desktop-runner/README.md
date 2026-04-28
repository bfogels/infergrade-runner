# InferGrade Desktop Runner Prototype

Sprint 72 preserves this prototype as the proposed starting point for the Runner companion app.

The app is intentionally small:

- Tauri 2 desktop shell
- vanilla JavaScript frontend
- sidecar wrapper that launches the existing `infergrade` CLI
- pair-code redemption through the sidecar, then process controls for start, stop, status, and log streaming
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

The primary UI redeems the one-time Hub code with:

```text
infergrade pair --api-url <hub url> --pair-code <pairing code> --label <runner label>
```

On success, the CLI saves the durable runner profile and the app immediately starts:

```text
infergrade start --api-url <hub url>
```

The app does not log the raw `pair` JSON because that response contains the durable runner token. The advanced token fallback can still pass `INFERGRADE_HUB_TOKEN` through the process environment; environment variables should still be treated as process-local secrets.

## Next Checks

1. Install Rust and platform prerequisites.
2. Run `npm run tauri dev`.
3. Confirm start/stop leaves no orphaned Runner processes.
4. Redeem a real Hub pairing code, confirm the app starts listening, and confirm Hub readiness updates.
5. Exercise secure storage in a live Tauri window.
6. Build a macOS package.
7. Attempt one Windows or Linux build artifact.
