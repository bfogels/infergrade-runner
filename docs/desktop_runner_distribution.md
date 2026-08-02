# Desktop Runner Distribution

The desktop Runner distribution lane defines how the local companion app is built, signed, published, and updated.

The current release lane is intentionally staged by platform:

1. build and verify the signed/notarized macOS Apple Silicon release
2. build, install, self-test, and launch-smoke Linux x86_64 `.deb` and AppImage packages
3. build, install, self-test, and launch-smoke Windows x64 MSI and NSIS packages
4. publish the macOS and Linux packages only after every platform build gate passes
5. retain unsigned Windows packages as short-lived workflow artifacts unless an operator explicitly publishes a clearly named unsigned technical preview
6. use Tauri updater signing for macOS app-update integrity

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
- digest verification and extraction of the pinned platform Python runtime
- clear the previous DMG output directory
- `npm run tauri -- build -- --locked`

It then prints any macOS DMG artifacts under:

```text
target/release/bundle/dmg/
```

with file sizes and SHA-256 digests. The digest identifies the emitted artifact for that candidate build; it is not a bit-for-bit reproducibility guarantee until the toolchain and packaging timestamps are pinned.

## Current App Surface

The desktop app exposes the pieces that a non-terminal user needs first:

- pair with a Hub code and start listening
- inspect process logs without a shell
- switch between light and dark modes
- inspect, install, or select a `llama.cpp` runtime through `runner-engine`
- select a local GGUF model and run the native first-run lane without Docker
- upload native-first-run evidence to Hub through the saved paired runner token

The runtime controls are deliberately conservative. The macOS Apple Silicon lane can explicitly install the recommended checksum-verified `llama.cpp` Metal runtime from the Runner-owned manifest, or validate and record an existing runnable `llama-cli` path. The app does not silently install, upgrade, or switch runtimes. The current managed runtime provenance is SHA-256 verified against the pinned manifest; it is not independently signed until a separate signature/minisign/cosign lane exists.

## Windows And Linux Build Prerequisites

The desktop sidecar is source-built from:

```text
apps/desktop-runner/sidecar/
```

`scripts/build_desktop_sidecar.sh` builds the wrapper for the current Rust host and copies it to Tauri's expected platform filename under:

```text
apps/desktop-runner/src-tauri/binaries/infergrade-sidecar-<target-triple>[.exe]
```

Pull requests that change the desktop, Runner engine, packaged core, schemas, or packaging scripts run a read-only Windows/Linux package workflow. It builds the actual installer formats, verifies their contents, installs them, invokes the installed sidecar against its packaged Runner core, launches the GUI briefly, and removes the install. The protected release workflow repeats those gates from the immutable release commit.

Successful pull-request package jobs retain the checksummed Linux candidates
and explicitly named unsigned Windows candidates for seven days. These are
review artifacts tied to one commit, not a versioned public release. Each
bundle carries a checksummed `CI-CANDIDATE-NOT-A-RELEASE.txt`; proposed-code
artifacts must be treated as untrusted until their source is reviewed and the
protected release lane rebuilds them from `main`.

- Windows: the verified MSI/NSIS files remain seven-day workflow artifacts by default. Public release requires either Authenticode signing or explicit opt-in to filenames containing `UNSIGNED-PREVIEW`. Hosted CI does not prove CUDA, NVIDIA inference, pairing, upload, or SmartScreen reputation.
- Linux: the verified AppImage/`.deb` files join the next versioned release with stable names and checksums. This is package acceptance on Ubuntu, not proof of every Linux distribution, GPU backend, desktop environment, or full Hub loop.

The package jobs use Python while building, but the installed application does not rely on it. Each package carries the reviewed `python-build-standalone` archive selected in `runtime/desktop_python_runtime.json`. The preparer verifies the exact archive size and SHA-256, rejects unsafe archive paths and links, preserves the included license files, and writes a receipt containing the executable, CA bundle, and license digests. Package smoke blocks system-Python discovery and requires both the installed sidecar and GUI to remain functional with the bundled runtime.

This proves the packaged Runner core is self-contained on the hosted Windows and Ubuntu images. It does not prove CUDA execution, all Linux distributions, Windows SmartScreen acceptance, or the complete Hub contribution loop.

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
https://github.com/bfogels/infergrade-runner/releases/latest/download/infergrade-runner-desktop-latest.json
```

The signed and notarized Apple Silicon installer has a stable public URL so the Hub can link directly to GitHub without proxying installer bytes:

```text
https://github.com/bfogels/infergrade-runner/releases/latest/download/InferGrade.Runner.macOS-arm64.dmg
```

Maintainers deliberately dispatch the protected GitHub Actions workflow from
`main` for a reviewed, already-tagged release. The workflow creates a draft for
the exact `vX.Y.Z` tag, attaches and verifies the complete asset set, and only
then publishes the release. Published releases and their assets are immutable;
GitHub's `releases/latest` redirect selects the current version without requiring
an overwriteable release asset. The workflow publishes the DMG, updater
artifacts, and verified Linux packages only after Developer ID signing,
notarization, Gatekeeper verification, stapled-ticket checks, and both hosted
package gates pass. Windows installers are excluded from the public asset set
unless the dispatch explicitly enables the clearly labeled unsigned preview.

Before creating the draft, the publisher also records Sigstore-backed GitHub
build provenance for the exact final asset set. It verifies that provenance
against this repository, the protected desktop release workflow, and the
`main` source ref before publication, then repeats checksum and provenance
verification after downloading the immutable public release.

The protected workflow also runs `scripts/verify_desktop_macos_release.sh` before upload. That script verifies the built app bundle with `codesign`, assesses the app and DMG with Gatekeeper, and validates stapled notarization tickets for both artifacts. If any of those checks fail, the workflow must stop before updating the downloadable release.

After downloading release artifacts from GitHub, maintainers can verify the published files against the checksum and updater manifests:

```bash
scripts/verify_desktop_release_artifacts.py \
  --directory /path/to/downloaded/vX.Y.Z \
  --require-dmg \
  --required-dmg-name InferGrade.Runner.macOS-arm64.dmg \
  --require-updater \
  --require-linux \
  --reject-unexpected
```

This verifies `SHA256SUMS`, confirms the updater manifest references local updater archives and signature artifacts, and prints stable evidence lines. It does not check Developer ID signing, notarization, or Gatekeeper behavior; use `scripts/verify_desktop_macos_release.sh` on the built macOS artifacts and clean-machine DMG smoke before treating a release as public-user-ready.

The updater manifest writer can already emit a multi-platform Tauri manifest when separate signed updater archives exist:

```bash
python3 ./scripts/write_desktop_update_manifest.py \
  --version "$(cat VERSION)" \
  --base-url "https://github.com/bfogels/infergrade-runner/releases/download/vX.Y.Z" \
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

## Latest Local Candidate Evidence

The current local macOS Apple Silicon candidate was built from the v0.2.2 managed-runtime train with ad-hoc signing:

```text
artifact: target/release/bundle/dmg/InferGrade Runner_0.2.2_aarch64.dmg
size: 7004499 bytes
sha256: c94f4eda1bd541053a828eea0ebd58b4e3beaa856673f37eae630ebaf0d4ea57
signing: ad-hoc local signing
notarization: skipped locally because Apple notarization credentials were not present
```

Local package smoke mounted the DMG, verified the app with `codesign --verify --deep --strict`, launched `InferGrade Runner.app`, observed the packaged `infergrade_desktop_runner` process, and confirmed the bundled sidecar responds under a clean shell environment with only `/usr/bin:/bin` on `PATH`:

```text
infergrade 0.2.2
```

This proves the local package opens and carries the sidecar without a global `infergrade` command, repo checkout, or Docker. It does not replace public-release gates: Developer ID signing, notarization, Gatekeeper assessment, clean-machine token storage, and full Desktop UI first-run upload smoke still need protected-release validation.

To repeat the local DMG smoke for a release candidate, run:

```bash
scripts/smoke_desktop_dmg.sh --dmg "target/release/bundle/dmg/InferGrade Runner_0.2.2_aarch64.dmg"
```

The script prints stable `desktop_dmg_*` evidence lines for the artifact path, size, SHA-256 digest, code-signature verification, clean-`PATH` sidecar version, app launch observation, and the fact that local smoke does not check notarization.

## Same-account clean-profile acceptance

Use the public-installer acceptance harness when a second macOS user account or
spare machine is unavailable:

```bash
scripts/accept_desktop_release.sh \
  --report-dir /path/to/acceptance-report
```

By default it downloads the latest public DMG, verifies the DMG and app with
Gatekeeper and stapled notarization checks, runs the packaged self-test and
readiness command, copies the app into an isolated Applications directory, and
launches that installed copy briefly. The process receives isolated home,
config, runtime-cache, temporary-directory, install, and OS credential-store
namespaces. The normal app and `com.infergrade.runner` keychain item are neither
replaced, read, nor modified.

For a personal walkthrough, add `--interactive`. The script keeps the isolated
app open until Enter is pressed:

```bash
scripts/accept_desktop_release.sh --interactive --report-dir /path/to/report
```

The generated JSON and Markdown reports deliberately leave pairing,
recommendation handoff, runtime resolution, a real benchmark, upload, and the
signed-out Result page marked as manual work. An automated launch is not
evidence that those user actions succeeded. `--capture-screen` is explicit
because a full-display screenshot may contain unrelated private UI.

## Non-Goals

- no signing secrets in the repo
- no auto-update keys in the repo
- no claim that hosted package smoke proves real Windows/NVIDIA or Linux GPU execution
- no claim that managed runtime downloads are independently signed until a signature verification lane is implemented
