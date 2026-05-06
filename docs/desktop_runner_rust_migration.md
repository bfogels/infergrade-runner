# Desktop Runner Rust Migration

InferGrade Runner should become an installer-and-go desktop product. A normal user should be able to install the app, pair it with Hub, select a model/runtime, and run a first useful local benchmark without Docker, Python, Rust, a repo checkout, PATH edits, or a terminal.

## Architecture Recommendation

Keep Hub as the decision and evidence surface. Keep Runner as execution truth. Make Desktop Runner a narrow native control plane:

- Tauri UI for pairing, readiness, runtime selection, lifecycle, logs, diagnostics, and recovery.
- Rust supervisor for URL normalization, pairing, token storage, runner registration, job polling, claiming, heartbeats, process lifecycle, log streaming, upload routing, runtime detection, container detection, and diagnostics.
- Native benchmark execution as the first-run default.
- Python runner-core as a packaged transition sidecar only where existing benchmark logic has not moved yet.
- Docker or Podman as optional sandbox providers for advanced/code/reference benchmarks.

The default user-facing promise is: Docker is not required for your first local benchmark.

## Migration Plan

1. Current bridge: keep the sidecar resolving bundled Runner core first, then dev fallbacks. The desktop self-test must prove invocation, not just file discovery.
2. Rust readiness: add Rust-owned desktop readiness probes for hardware, native runtime, first-run eligibility, Docker, and Podman.
3. Rust supervisor: move pairing, token load/save/clear, runner registration, poll/claim/heartbeat, start/stop, and support export into Rust commands behind explicit Tauri permissions.
4. Python transition execution: keep Python runner-core packaged for benchmark execution while Rust owns orchestration and process supervision.
5. Native first-run suite: add a Docker-free benchmark path for load time, TTFT, decode tokens/sec, memory footprint, short generation, and simple output sanity.
6. Runtime manager: add curated llama.cpp runtime manifests with platform selectors, checksums, signatures, provenance, compatibility labels, and rollback.
7. Sandboxed suite: keep Docker/Podman optional for code-execution and reproducibility-sensitive benchmarks.

## Native First-Run Benchmark Plan

Tier 1 must run without Docker:

- model load time
- time to first token
- decode tokens/sec
- peak memory or unified-memory pressure where available
- short interactive-chat prompt
- basic output sanity checks
- local artifact/runtime compatibility checks

This tier can produce useful Hub evidence, but it should be labeled as decision-suite evidence unless stronger methodology is present.

Tier 2 can add native prompt suites, format adherence, and non-code instruction-following checks where dependencies are packageable.

Tier 3 remains sandboxed for HumanEval, EvalPlus, MBPP, generated-code execution, and reference/gold lanes that need isolation.

## llama.cpp Runtime Plan

Do not bundle every runtime in the installer. The pragmatic plan is:

- Include a minimal app-managed runtime manifest in the app.
- On first launch, detect hardware and recommend one runtime lane.
- Apple Silicon: recommend signed/notarized Metal runtime.
- NVIDIA: offer CUDA runtime where platform packaging is feasible.
- AMD: offer Vulkan or ROCm/HIP only where the OS/runtime combination is supportable.
- CPU-only: offer CPU or Vulkan fallback when available.
- Download GPU-specific runtimes on demand with explicit user action.
- Verify downloaded runtime archive signature, SHA-256 checksum, manifest version, and expected binary names before selection.
- Keep the previous selected runtime manifest for rollback.
- Never silently upgrade a major runtime. Show provenance, version, compatibility notes, and recovery action.

Bundling all llama.cpp variants would bloat installers, complicate signing/notarization, and make platform support harder to explain. A small manifest plus verified runtime downloads gives cleaner provenance and rollback.

## Container Runtime Plan

Docker and Podman are capability enhancers, not onboarding gates.

Readiness should report:

- Native benchmark suite: ready or blocked by native runtime/model path.
- llama.cpp runtime: selected, available, missing, or incompatible.
- Docker: found or not found.
- Podman: found or not found.
- First run: ready only when native runtime and model selection are ready.

When Docker or Podman is missing, the app should say advanced sandboxed benchmarks are disabled, while native benchmarks remain available.

## PR-Sized Implementation Phases

1. Add Rust desktop readiness probe and native-first UI copy.
2. Add Rust supervisor skeleton with typed status events, keeping Python execution unchanged.
3. Move pair/redeem/token/reset into Rust commands and remove shell invocation for pairing.
4. Move worker poll/claim/heartbeat loop into Rust while delegating execution to Python runner-core.
5. Add native first-run benchmark request type and bundle schema coverage.
6. Add managed runtime manifest download/verify/select/rollback.
7. Add native first-run execution for llama.cpp.
8. Add optional Docker/Podman sandbox detection to Hub readiness and advanced benchmark gating.
9. Add clean-machine smoke scripts for macOS, Windows, and Linux installers.

## Risks And Mitigations

- Rust rewrite drift: keep Python execution until Rust replacement tests exist.
- Trust overclaiming: label native first-run evidence separately from reference/gold evidence.
- Runtime supply-chain risk: require signatures, checksums, immutable manifests, and rollback.
- Cross-platform runtime complexity: start with Apple Silicon Metal, then expand one platform lane at a time.
- Sandbox confusion: keep Docker/Podman behind advanced benchmark language.
- Secret leakage: keep tokens in OS credential storage and process env, never command args or logs.
- Hub/Runner boundary drift: keep model selection and recommendations in Hub; Desktop validates local readiness and executes.

## Manual QA Checklist

macOS Apple Silicon:

- Fresh install with no Docker, no Python, no Rust, no global `infergrade`.
- App launches and shows hosted Hub URL.
- Pair code flow succeeds.
- Reset Pairing recovers from stale token/code state.
- Readiness says native benchmark suite is available and Docker is optional.
- Metal runtime recommendation is visible.
- First native benchmark runs and uploads evidence.
- Docker missing does not block first run.
- Signed/notarized artifact passes Gatekeeper.

Windows:

- Fresh install with no Python/Rust/global `infergrade`.
- App launches from Start menu.
- Pair/reset/token recovery work.
- NVIDIA detection recommends CUDA only when supported.
- Docker/Podman absence disables only advanced sandboxed benchmarks.
- Installer and uninstaller leave no orphaned runner process.

Linux:

- AppImage or `.deb` launches on a clean desktop.
- CPU/Vulkan fallback is presented if no GPU runtime is supported.
- Podman detection is advisory.
- Docker absence does not block native first-run readiness.
- Logs and support export are readable without terminal access.

