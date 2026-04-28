# Desktop Runner App Discovery

Sprint 72 decision memo for making InferGrade Runner installable without terminal knowledge.

## Recommendation

Use **Tauri 2** for the first preserved Runner companion prototype.

The app should wrap the existing Runner worker as a sidecar process instead of rewriting execution. The first durable prototype should prove pairing, token storage, start/stop lifecycle, log streaming, and app close/reopen behavior on macOS first, then attempt one Windows build.

Why Tauri first:

- It keeps the app small by using system webviews instead of bundling Chromium.
- Its sidecar model matches the Runner requirement: launch and monitor an existing executable.
- The official updater, signing, and sidecar docs cover the major distribution paths we need to de-risk.
- Rust complexity is real, but the app's native surface is mostly process lifecycle, secure storage, tray/startup behavior, and installer integration.

Do not commit to a polished app until the prototype proves sidecar packaging, secure token storage, and update signing. The hard part is distribution trust, not the UI shell.

## Candidate Comparison

| Candidate | Best fit | Main strength | Main risk | Sprint 72 verdict |
| --- | --- | --- | --- | --- |
| Tauri 2 | Lightweight Runner companion with sidecar process | Small app, explicit sidecar support, cross-platform bundling | Rust/build pipeline, webview differences, updater/signing setup still non-trivial | Recommended prototype |
| Electron | Fastest mature desktop path with broad packaging ecosystem | Mature installers, auto-update patterns, large ecosystem | Larger app, Chromium bundle, broader attack/update surface | Prototype only if Tauri sidecar packaging blocks |
| BeeWare Briefcase | Python-native packaging path | Natural fit for Python projects and Python packaging | UI maturity and native dependency packaging risk; Runner sidecar/control still needs proof | Secondary prototype if Python packaging is the key risk |

## Prototype Matrix

PR 2 should preserve only useful prototype scaffolding. Disposable spikes can live on throwaway branches.

1. Tauri sidecar prototype

   Prove:

   - app can bundle or locate an `infergrade` sidecar
   - app can start `infergrade start`
   - app can stop the process cleanly
   - stdout/stderr logs stream into the window
   - runner token can be stored through an OS-backed secure-storage path or a clearly documented placeholder
   - app relaunch can recover last known listening/running state
   - macOS package builds locally

2. Electron fallback prototype

   Prove the same lifecycle and log streaming path using Node's process APIs. Use this only to compare speed-to-MVP, installer size, and update/signing ergonomics.

3. Briefcase packaging probe

   Prove whether a Python-native app can package the Runner control shell and its dependencies without fighting native/binary packaging. This can remain a research branch unless it looks easier than expected.

## Distribution Findings

### Tauri

Tauri supports external sidecar binaries through `bundle.externalBin` and the shell plugin. The JavaScript API expects the sidecar name declared in config, and Rust can launch it through `app.shell().sidecar(...)`. That is a direct fit for wrapping `infergrade start`.

Tauri's updater plugin uses signed update artifacts and platform keys in the form `linux|darwin|windows` plus architecture. The signing-key workflow is separate from OS code signing, so we must plan both update signatures and platform signing.

Tauri macOS signing/notarization is still required for browser-downloaded apps to avoid scary launch warnings. Windows signing also needs an Authenticode path; cross-signing Windows installers from macOS/Linux may require a custom sign command.

Primary references:

- Tauri sidecars: https://tauri.app/develop/sidecar/
- Tauri shell plugin: https://v2.tauri.app/reference/javascript/shell/
- Tauri updater: https://v2.tauri.app/plugin/updater/
- Tauri macOS signing: https://tauri.app/distribute/sign/macos/
- Tauri Windows signing: https://v2.tauri.app/distribute/sign/windows/

### Electron

Electron is the fastest mature desktop ecosystem if we decide app size is acceptable. Official docs state macOS and Windows unsigned apps trigger OS warnings, and signed/notarized macOS builds are expected for distribution. Electron's built-in `autoUpdater` supports macOS and Windows, not Linux; Linux updates are usually delegated to distro package managers unless using external tooling such as electron-builder's updater.

Primary references:

- Electron code signing: https://www.electronjs.org/docs/latest/tutorial/code-signing
- Electron autoUpdater: https://www.electronjs.org/docs/latest/api/auto-updater
- Electron publishing/updating: https://www.electronjs.org/docs/latest/tutorial/tutorial-publishing-updating

### BeeWare Briefcase

Briefcase can package Python apps for macOS, Windows, and Linux, including macOS app/DMG/PKG, Windows zip/MSI, and Linux Flatpak/rpm/deb/pkg.zip outputs. macOS package builds default to signed and notarized release artifacts when configured. This is promising for a Python-native control utility, but the risk is whether Runner dependencies and process-control ergonomics are cleaner than a webview shell with sidecar execution.

Primary references:

- Briefcase overview: https://beeware.org/project/briefcase/
- Briefcase macOS platform docs: https://briefcase.beeware.org/en/latest/reference/platforms/macOS/
- Briefcase how-to guides: https://briefcase.beeware.org/en/latest/how-to/

## Decision Criteria For Sprint 72 Closeout

Choose the app foundation only after the prototype answers:

- Can the app start/stop Runner without orphaned processes?
- Can logs be streamed and copied without terminal access?
- Can a runner token be stored in an OS-appropriate secure store?
- Can a packaged macOS app run on a clean machine?
- Can we produce at least one Windows or Linux artifact without heroic setup?
- Does the update/signing path look compatible with a small team?
- Does the app preserve the current Runner contract boundary instead of inventing a second execution engine?

## Known Risks

- macOS signing/notarization and Windows SmartScreen reputation are the largest user-trust risks.
- Bundling Python, Docker/native runtime checks, and managed llama.cpp/vLLM helpers may dominate installer size and support complexity.
- Sidecar process lifecycle must handle sleep, reboot, app close, network loss, and stale tokens.
- Secure token storage must be resolved before beta; plaintext config is acceptable only for a spike.
- The Hub should remain the model/benchmark/result UX. The desktop app should focus on pairing, readiness, process state, logs, and recovery.

## Next PR

Sprint 72 PR 2 should preserve a minimal Tauri prototype if it proves:

- `infergrade start` can be launched as a sidecar
- stdout/stderr stream to the UI
- a token placeholder can be saved and read through the chosen storage abstraction
- the app can be packaged locally on macOS

If Tauri blocks on sidecar packaging or build setup, create an Electron fallback branch with the same proof points before moving to Sprint 73.
