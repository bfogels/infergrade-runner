# Native runtime and updater validation

This candidate continues `codex/native-runtime-060` and Hub `codex/native-default`.
It is private-beta implementation work, not a release or hardware qualification.

## Runtime policy

Local llama.cpp requests default to native on Windows, Linux and macOS.
Explicit containers remain available; vLLM/TGI retain container defaults.
Docker and WSL are optional advanced sandbox tools. Python compatibility
`install-runtime --execute` delegates to `infergrade-runner runtime install`
on PATH; Desktop uses that same Rust engine. Explicit legacy Homebrew/manual
runtime IDs remain available.

The bundled official semantic release is `v0.6.0`, resolved through its
checksum-verified `nightly-tag.txt` to binary release `b11429`. The binary reports
`0.6.0-dev`, build `11429`, commit `d81235049`; preserve both identities.
Archives and CUDA companions have exact lengths and SHA-256 pins. Dependencies
are recorded in source assertions. Linux CUDA libraries are colocated for
upstream `$ORIGIN` loader paths. Managed CUDA execution must prove CUDA device
use and nonzero layer offload; CPU fallback is not CUDA evidence.

Runtime installation is explicit and separate from desktop app updates.
Immutable builds and selection history remain available for rollback. Failed
extraction or version smoke cannot replace the active selection. Unsupported
CUDA recommendations do not silently select CPU.

## Automatic memory fitting

Native Python benchmarks probe each resolved completion/server/perplexity binary's
`--help` for the exact `--fit` option. With no explicit backend flags, supported
binaries use `--fit on` instead of forcing a GPU-layer count. Help probes have a
10-second timeout and are cached by executable path, size and modification time.
Unsupported or failed probes retain legacy defaults. The older pinned container
image keeps its existing arguments; no new flag is assumed for that image.

Benchmark context sizes stay explicit. Desktop first-run uses a fixed 4096-token
context and probes its actual completion binary before choosing fitting or legacy
layer flags. Explicit Python backend flags are preserved, and explicit CPU
selection still forces zero GPU layers. Commands and runtime allocation logs
remain in benchmark artifacts; requested CUDA must still prove positive offload.
Fitting targets memory capacity, not a guaranteed speed improvement. Windows /
NVIDIA performance requires an actual hardware comparison.

## Local evidence

Receipts, archives and downloaded models remain outside Git under `output/`:

- `runtime-060/managed-install.json`, `macos-receipt.json`, `legacy-canary.json`,
  and `minicpm5-canary.json`: macOS install and exact-artifact generation.
- `native-ci-local-review-final/receipt.json`: managed install, selected binary
  version checks, tiny public GGUF generation, Rust native first-run and exact
  build reselection passed locally on macOS.
- Observed macOS build ID:
  `cc66bce135a8b984c445410e18ad5dfac2ad066c42117c606bef347ffbd8a8aa`.

`Managed Native Runtime Smoke` exercises the real CPU installer and generation
on native Windows and Linux CI hosts. CPU CI cannot qualify NVIDIA hardware,
broad model support, desktop packages, signing, or app replacement.

## Remaining acceptance

Track source tests, native CI, packaging, platform code signing, Tauri updater
signatures, publication and actual old-to-new updates separately.
Prior Windows signing validation run `37361260492` remained queued with no jobs
when checked during this work. Published v0.3.61 lacked Windows installers and
its updater manifest covered only macOS. Candidate source does not change that.

Before calling the friend's issue fixed, exercise the resulting Windows
package: install, pair, managed runtime setup, public-model generation, native
Hub job execution and upload. Prove actual GPU offload on NVIDIA hardware.
Exercise old-to-new updates, restart and version confirmation on Windows and
Linux AppImage. Linux .deb installations use the system package installer.
See `desktop_runner_distribution.md` for artifact and updater verification.
