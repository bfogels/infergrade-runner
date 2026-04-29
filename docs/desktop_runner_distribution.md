# Desktop Runner Distribution

Sprint 74 adds a repeatable unsigned local build lane before making the desktop Runner app public.

The first release lane should be boring:

1. build a macOS Apple Silicon DMG locally
2. record the artifact path, size, and SHA-256 digest
3. sign and notarize only after the unsigned build lane is stable
4. add update manifests only after signing keys and rollback policy are settled

## Current Build Lane

From the Runner repo root:

```bash
./scripts/build_desktop_runner.sh
```

The script runs:

- `npm ci`
- `npm run build`
- `npm audit --audit-level=moderate`
- `cargo check --locked`
- clear the previous DMG output directory
- `npm run tauri -- build -- --locked`

It then prints any macOS DMG artifacts under:

```text
apps/desktop-runner/src-tauri/target/release/bundle/dmg/
```

with file sizes and SHA-256 digests. The digest identifies the emitted artifact for that candidate build; it is not a bit-for-bit reproducibility guarantee until the toolchain and packaging timestamps are pinned.

## Current App Surface

The dogfood app now exposes the pieces that a non-terminal user needs first:

- pair with a Hub code and start listening
- inspect process logs without a shell
- switch between light and dark modes
- inspect or select the explicit managed `llama.cpp` runtime through the existing Runner CLI

The runtime controls are deliberately conservative. They run the same inspect/select commands a terminal user would run and do not install or upgrade anything without the existing CLI confirmation path. A true version dropdown should wait for a broader managed-runtime manifest with per-platform support, compatibility labels, signed artifacts, checksums, and rollback policy.

## Windows And Linux Build Prerequisites

The repository currently contains a macOS Apple Silicon sidecar wrapper only:

```text
apps/desktop-runner/src-tauri/binaries/infergrade-sidecar-aarch64-apple-darwin
```

Before claiming Windows or Linux support, add matching sidecar binaries for the target triples and run at least one package attempt per platform. The first expected additions are:

- Windows: sidecar wrapper for `x86_64-pc-windows-msvc` or `aarch64-pc-windows-msvc`, then choose NSIS/MSI and an Authenticode signing path.
- Linux: sidecar wrapper for `x86_64-unknown-linux-gnu` or `aarch64-unknown-linux-gnu`, then choose AppImage or `.deb` as the beta lane.

The sidecar contract should remain the same: call the existing `infergrade` CLI when available, otherwise resolve the bundled or repo-local Runner core.

## Signing Gates

Do not treat an unsigned local DMG as a user-ready release.

Before a public beta:

- create an Apple Developer signing identity for the project
- sign the macOS app bundle and DMG
- notarize the DMG
- verify Gatekeeper behavior on a clean macOS machine
- document how signing credentials are injected in CI without exposing them to forks

Windows needs a separate Authenticode signing path and SmartScreen reputation plan. Linux needs a packaging decision before update behavior is promised.

## Update Channel Gates

Tauri updates should not be enabled until:

- release artifacts are signed
- update signing keys are generated and stored outside the repo
- release channels are named and documented
- rollback behavior is tested
- the app can report its current version and update channel in the UI

The first likely channels are:

- `dogfood`: internal builds for trusted testers
- `beta`: signed builds for early external users
- `stable`: later public releases

## Release Candidate Checklist

For each candidate build, record:

- git commit and PR stack
- platform and architecture
- artifact name
- artifact size
- SHA-256 digest
- signing status
- notarization status
- whether the app launched on a clean machine
- whether token save/load/clear was exercised
- whether Runner start/stop left orphaned processes

## Non-Goals For This Sprint

- no signing secrets in the repo
- no auto-update keys in the repo
- no claim that Windows/Linux installers are supported until a build has been attempted
- no rewrite of Runner execution inside the app
