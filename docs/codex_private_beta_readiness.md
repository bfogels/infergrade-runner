# Codex Private Beta Readiness

Status: working audit refreshed after Runner Batch A promotion on 2026-05-28.

## Plausible 5-20 User Beta Path

The Mac path is close enough to invite a small technical beta only after one clean current full-loop proof is refreshed and documented:

1. User signs in to Hub.
2. User creates a runner pairing.
3. User installs/opens Desktop Runner.
4. User pairs through stdin/paste-code flow.
5. User installs the managed Apple Silicon Metal runtime explicitly.
6. User selects a known-good GGUF.
7. User runs the first local benchmark.
8. Runner uploads the normalized result.
9. Hub Result explains what the run proves, what it does not prove, and what to run next.
10. Support export is designed to omit tokens and is safe to send to support after review.

## Current Strengths

- Pair-code hygiene and runner token revocation are implemented.
- Desktop has setup, runtime, first-run, listener, logs, and recovery surfaces.
- Managed Mac runtime is explicit and checksum verified.
- Upload retry and artifact path recovery exist.
- Support export redacts secrets and carries enough runtime/hardware context for triage.
- CUDA preview gates are explicit enough that support can inspect readiness without public support claims.

## Known Limits

- Public installers, signing, notarization, and clean-machine package proof remain release-gated.
- Managed runtime is checksum-verified, not independently signed.
- Windows/NVIDIA is preview/proof-gated only.
- Linux is CLI/best-effort, not a Desktop-supported v1 path.
- Cloud remains deferred.
- Founder friction-capture is still distinct from agent dogfood.

## Highest-Priority Fixes

- Refresh current Mac beta runbook from the latest `0.3.6` Desktop/Runner flow.
- Add a short first-user recovery table for the top failures: pairing expired, token revoked, runtime missing, model path missing, upload rejected, and support export needed.
- Confirm Hub handoff commands use the current pinned Runner release and explain contract drift if present.
- Keep Windows/CUDA language as preview until real hardware proof exists.

## Batch Progress From This Pass

- Branch hygiene is clean: Runner `origin/main` and `origin/develop` are aligned at `44679f0`.
- The current audit docs are on both branches, but no new Mac proof run or CUDA hardware proof was performed in this pass.
- The next Runner PR should be implementation/proof work, not another metadata-only pass: either refresh the Mac full-loop beta proof or make an explicit contract export/defer decision.
