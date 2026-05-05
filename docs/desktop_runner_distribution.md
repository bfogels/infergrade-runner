# Desktop Runner Distribution

The desktop Runner distribution lane defines how the local companion app is built, signed, published, and updated.

The current release lane is intentionally narrow:

1. build a macOS Apple Silicon DMG
2. publish the DMG, updater archive, updater signature, and updater manifest from GitHub Actions
3. use Tauri updater signing for app-update integrity
4. use ad-hoc macOS signing only as a development fallback
5. require Developer ID signing and notarization before treating the DMG as public-user-ready

## Local Build Lane

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

The desktop app exposes the pieces that a non-terminal user needs first:

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

### macOS "Damaged App" Triage

If macOS shows "`InferGrade Runner.app` is damaged and can't be opened", treat the artifact as not release-ready. For a downloaded DMG, that symptom usually means Gatekeeper could not verify the distribution path: the bundle or DMG is unsigned, ad-hoc signed, not notarized, modified after signing, or missing a clean stapled/notarized ticket.

Do not ask users to bypass Gatekeeper. Build a new artifact from the protected desktop release workflow, confirm the workflow used Developer ID signing plus Apple notarization, and verify the DMG on a clean macOS machine before sharing it again. Local ad-hoc builds remain useful for development smoke tests, but they are not a supported public download lane.

## Update Channel

The macOS app reads the latest updater manifest from:

```text
https://github.com/bfogels/infergrade-runner/releases/download/desktop-runner-latest/infergrade-runner-desktop-latest.json
```

The GitHub Actions workflow publishes the latest DMG and updater artifacts on each push to `main`. That makes release artifacts available quickly, but it does not replace the signing gates above: public distribution still needs Developer ID signing, notarization, clean-machine Gatekeeper verification, and a rollback policy.

The protected workflow also runs `scripts/verify_desktop_macos_release.sh` before upload. That script verifies the built app bundle with `codesign`, assesses the app and DMG with Gatekeeper, and validates stapled notarization tickets for both artifacts. If any of those checks fail, the workflow must stop before updating the downloadable release.

The updater manifest writer can already emit a multi-platform Tauri manifest when separate signed updater archives exist:

```bash
python3 ./scripts/write_desktop_update_manifest.py \
  --version "$(cat VERSION)" \
  --base-url "https://github.com/bfogels/infergrade-runner/releases/download/desktop-runner-latest" \
  --artifact darwin-aarch64=/path/to/InferGrade.Runner.app.tar.gz \
  --artifact windows-x86_64=/path/to/InferGrade.Runner.setup.zip \
  --artifact linux-x86_64=/path/to/infergrade-runner.AppImage.tar.gz \
  --output /path/to/infergrade-runner-desktop-latest.json
```

Each archive must have a sibling `.sig` file produced by Tauri updater signing. Adding Windows or Linux entries to the public manifest still requires a successful package attempt, platform-specific signing decision, and launch smoke on that platform.

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

## Non-Goals

- no signing secrets in the repo
- no auto-update keys in the repo
- no claim that Windows/Linux installers are supported until a build has been attempted
- no rewrite of Runner execution inside the app
