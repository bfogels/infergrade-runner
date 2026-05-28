# Codex v1 Readiness Audit

Status: private-beta audit refreshed after Runner Batch A promotion on 2026-05-28.

## Current State

- Branches: `origin/develop` was reclaimed by PR #246 and promoted by PR #248. `origin/main` and `origin/develop` now both point at `44679f0`.
- Runner source version: `0.3.6`.
- Runner contract version: `0.3.5`.
- Current `origin/main`: `44679f0`, the Runner Batch A readiness-doc promotion.
- Current `origin/develop`: `44679f0`, aligned with `main`.
- Immediately after PR #248 landed, Runner branch hygiene was clean and no Runner feature work had been promoted beyond the readiness-doc batch in this pass.

## Latest Runner Capabilities

- Mac Apple Silicon is the reference path: Desktop can pair, show readiness, install/select the managed Metal `llama.cpp` runtime, run a native GGUF first-run, upload via saved pairing, and expose recovery/support actions.
- Managed Mac runtime install is explicit, SHA-256 verified, expected-binary checked, version-smoked, and recorded as the selected runtime. It is not silently installed or independently signed.
- Runner pairing supports safer pair-code handling through stdin/env paths, runner labels, runner kind, saved profile state, and revoked-token recovery.
- Run/listener paths can claim Hub jobs, execute locally, upload normalized bundles, and preserve progress/support artifacts.
- Support exports are secret-free and include runtime, hardware, selected CUDA metadata where applicable, and recovery context.
- Windows/NVIDIA CUDA is represented as a proof-gated preview: preflight diagnostics, selected GPU metadata, user-selected runtime provenance, review-only candidate artifact metadata, and machine-readable proof gates.

## User-Visible Versus Internal

User-visible today:

- Desktop setup and readiness.
- Pair/reset/unpair.
- Managed Mac runtime install/select/remove.
- Native first-run and upload handoff.
- CLI worker/listener fallback.
- Support export.

Internal or private-beta only:

- Agent/founder dogfood identity and evidence-source tagging.
- CUDA managed-runtime candidate review metadata.
- Windows/NVIDIA support exports and proof gates.
- Release/public readiness scripts and unsigned/smoke package artifacts.

## v1 Blockers

- Mac needs a clean protected full-loop proof on current bits: install/open Desktop, pair, install managed runtime, run known-good GGUF, upload, view Hub Result, and capture support export.
- Public runtime supply-chain posture is incomplete: checksum verification exists, but independent signing/notarization of the runtime artifact is not solved.
- The source is `0.3.6` while the exported contract remains `0.3.5`; decide whether the current runtime-selector/CUDA contract state needs a new export before v1.
- Evidence calibration still needs observed repeat ladders for key Apple Silicon setups so Hub recommendations can stop relying on estimated duration/token/failure metadata.
- Windows/NVIDIA cannot move beyond preview until a real machine proves runtime selection/install, Hub pairing, known-good GGUF execution, upload, Result review, and secret-free support export.

## Public Beta Blockers

- No v1.0.0, public release, or open-source-public launch decision has been made.
- macOS signing/notarization, protected release workflow, published artifact verification, and clean-machine smoke need founder-approved release gates.
- Windows/Linux desktop packages remain smoke artifacts, not public installers.
- Third-party license and benchmark dataset checks need final public-release confirmation.
- CUDA managed download must remain disabled until every candidate review check is `passed`, not merely recorded or pending.

## Highest-Leverage PR Sequence

1. Re-export or explicitly defer a Runner contract update so Hub and Runner version boundaries are clear.
2. Add Mac full-loop beta proof artifacts/docs from a clean current build without committing secrets or raw outputs.
3. Improve managed runtime provenance with independent signature verification or clear v1 copy that the lane is checksum-only.
4. Inspect the Windows CUDA candidate archive and update review checks without enabling managed download.
5. Run one real Windows/NVIDIA proof loop when hardware is available, keeping all CUDA copy preview-gated until then.
6. Run Apple Silicon repeat ladders for the top recommendation questions and feed aggregate evidence back into Hub.

## Landed In This Pass

- PR #246 reclaimed `develop` without dropping the historical develop-only commit from ancestry.
- PR #247 added this v1 readiness audit and the private beta readiness audit.
- PR #248 promoted the readiness-doc batch to `main` and `develop` was fast-forwarded back to `main`.
- No Runner version bump, v1.0.0 promotion, public launch, or CUDA support expansion happened in this pass.
