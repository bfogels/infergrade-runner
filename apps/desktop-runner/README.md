# InferGrade Desktop Runner

InferGrade Desktop Runner is the local companion app for people who want to pair a machine, keep the Runner process alive, inspect logs, and recover from local setup problems without using a terminal.

The Hub remains the model selection, benchmark planning, recommendation, and results surface. This app should stay focused on pairing, readiness, Runner lifecycle, local runtime controls, logs, updates, and support export.

The desktop happy path is now native-first for macOS Apple Silicon: Docker will not be required for the first local benchmark, and the app can run a local GGUF through a Runner-pinned managed fallback, an exact build from the signed runtime catalog, or a selected existing `llama-cli` binary. Downloads are explicit and checksum-verified; signed catalog metadata authenticates InferGrade's build assertion, not an upstream artifact signature. Docker remains supported for advanced sandboxed benchmarks and container-friendly operator workflows.

## What It Includes

- Tauri 2 desktop shell with a vanilla JavaScript frontend
- Sidecar wrapper plus a pinned self-contained Python runtime for Runner-core bridge paths
- Pair-code redemption through the Rust/Tauri command adapter
- Start, stop, status, and log streaming controls for the local Runner process
- OS-backed token storage through the Rust `keyring` crate
- System, light, and dark UI modes
- Explicit `llama.cpp` runtime inspection and selection controls
- Native first-run model selection, progress events, local artifacts, and Hub upload handoff
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

The Tauri and platform package scripts build and copy the platform sidecar through a cross-platform Node hook, so a cold dev or package build does not require Bash or a separate preparation command. Run the script below directly only when testing or rebuilding the sidecar by itself.

Build the platform-specific sidecar wrapper for the current Rust host with:

```bash
../../scripts/build_desktop_sidecar.sh
```

Tauri expects the generated file to use the target-triple suffix, for example `src-tauri/binaries/infergrade-sidecar-aarch64-apple-darwin` on Apple Silicon macOS or `src-tauri/binaries/infergrade-sidecar-x86_64-pc-windows-msvc.exe` on 64-bit Windows. Packaged builds include the Runner core source and a digest-pinned Python 3.12 runtime as Tauri resources. The sidecar validates the runtime receipt plus the executable, CA bundle, and license digests before using it; a present but altered runtime fails closed rather than silently selecting system Python. Development builds without that resource may still fall back to `INFERGRADE_RUNNER_REPO`, walking back to the Runner repo root, or finally `infergrade` from `PATH`.

## Runtime Selection

The app does not install, upgrade, or switch `llama.cpp` silently. Open **Details and support → Runtime options** and choose one lane:

- **Managed fallback** installs the Runner-pinned compatibility build.
- **Signed runtime catalog** lists compatible reviewed upstream or specialized-fork builds and installs only the exact build the user selects.
- **Custom llama.cpp build** selects a local `llama-cli`, validates it, discovers sibling binaries, and derives the runtime identity from the executable digest.

Every selection is stored in the InferGrade runtime cache; each evidence-producing run then locks one exact immutable runtime. The same engine paths are available through the Rust CLI:

```text
infergrade-runner runtime plan
infergrade-runner runtime catalog-refresh
infergrade-runner runtime catalog-use --target <catalog-target> --consent-build <sha256>
infergrade-runner runtime select-existing --runtime-path /path/to/llama-cli
```

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
- The protected release workflow derives both the Developer ID Application name
  used by Tauri and its exact fingerprint used by direct `codesign` calls from
  the imported `APPLE_CERTIFICATE`; no separately maintained signing-identity
  variable is required.

The protected release lane also uses that Developer ID identity to sign every
Mach-O executable and library inside the bundled Python runtime before Tauri
packages the app. The signing transform is recorded in the runtime receipt;
local ad-hoc builds do not claim this protected-release evidence.

Public release credentials should be configured only in the protected GitHub `release` environment. Do not copy Apple certificates, notary credentials, Tauri updater keys, or passwords into repository-level secrets, local docs, screenshots, or checked-in config files.

If CI reports that `APPLE_CERTIFICATE` could not be opened with `APPLE_CERTIFICATE_PASSWORD`, re-export the Developer ID Application certificate as a password-protected `.p12`, verify it locally with `openssl pkcs12 -passin env:APPLE_CERTIFICATE_PASSWORD`, then update the certificate and password secrets together in the protected GitHub release environment.

The release workflow publishes a versioned, immutable GitHub release and exposes
its updater manifest through GitHub's latest-release redirect:

```text
https://github.com/bfogels/infergrade-runner/releases/latest/download/infergrade-runner-desktop-latest.json
```

The workflow creates a draft for the exact `vX.Y.Z` tag, uploads and verifies the
complete checksummed asset set, and only then publishes it. GitHub makes the
published release immutable. The workflow then performs an unauthenticated
manifest read and archive `HEAD` check through the latest-release redirect. A
private repository or otherwise inaccessible release origin fails this gate even
when an authenticated maintainer can see the assets; updater clients cannot use
maintainer credentials.

For nontechnical beta users, the macOS DMG should be Developer ID signed and notarized. Ad-hoc signed DMGs are appropriate for local development and internal smoke testing only.

If a downloaded DMG opens with the macOS "`InferGrade Runner.app` is damaged and can't be opened" dialog, discard that artifact and rebuild it through the protected release workflow. Do not ask users to bypass Gatekeeper; the release candidate must be Developer ID signed, notarized, and verified on a clean macOS machine.

## Windows And Linux

GitHub-hosted Windows and Ubuntu runners build the matching platform sidecar,
package the app, execute the packaged sidecar self-test, install the native
package, and verify that the desktop process remains running after launch.
The smoke blocks system-Python discovery and requires the sidecar to report the
bundled runtime receipt, so end users do not need a separate Python installation
for the packaged Runner core.
Linux x86_64 `.deb` and AppImage assets may be published after this gate.
Windows MSI and NSIS packages remain unsigned workflow artifacts by default;
an explicitly approved unsigned technical preview uses filenames containing
`UNSIGNED-PREVIEW` and will trigger normal Windows publisher or SmartScreen
warnings.

These hosted checks do not contain an NVIDIA GPU. They do not prove CUDA
runtime selection, accelerated model execution, Hub upload, or the full
Windows/NVIDIA evidence loop. That support claim still requires a physical or
rented known-good NVIDIA host and a real benchmark receipt.

## Sidecar Contract

The primary UI redeems the one-time Hub pairing code with:

```bash
printf '%s\n' "$INFERGRADE_PAIR_CODE" | infergrade pair \
  --api-url "$HUB_URL" \
  --pair-code-stdin \
  --label "$RUNNER_LABEL"
```

The pairing code must be supplied through protected stdin or the dedicated
environment variable, not as a command-line argument that can appear in shell
history or process listings. Set `HUB_URL` and `RUNNER_LABEL` to the values
provided by the Hub before running the example.

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

## Native First-Run Status

The native first-run lane is intentionally narrow:

- macOS Apple Silicon with selected `llama.cpp` runtime: supported for local GGUF smoke and Hub upload.
- Docker/Podman: optional; missing containers only disable advanced sandboxed benchmarks.
- Python runner-core: still present for advanced execution bridge paths and runs through the package's pinned self-contained runtime; no system Python prerequisite is intended.
- Linux x86_64 Desktop: package install and launch are CI-proven; runtime and benchmark support remain best-effort CLI/technical-beta territory.
- Windows x64 Desktop: package install and launch are CI-proven, but public distribution remains gated by signing or an explicitly labeled unsigned preview; Windows/NVIDIA execution still needs real GPU proof.
- Managed runtime install: explicit macOS Apple Silicon Metal lane available; broader channels and independent signature verification are planned.
