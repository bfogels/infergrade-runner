# Runner v0.2.20 Sprint Planning: Golden Apple Silicon Path

## Current Branch State

- Runner `origin/main`: v0.2.18 dogfood planner release.
- Runner `origin/develop`: one post-release sync commit ahead of `main` at branch start.
- Branch: `codex/runner-golden-apple-silicon`.
- Open Runner PRs at branch start: none.
- Hub `main` and `develop`: parity after populated evidence proof-path release.

## Release Goal

Make the private-beta Apple Silicon path executable by a maintainer or early user without relying on chat history:

> pair Runner with Hub, run local native evidence, upload a bundle, open Hub Result, and choose the next benchmark.

This release should document the loop and recovery boundaries. It should not add new benchmark lanes.

## Scope

- Add a golden Apple Silicon private-beta runbook.
- Link the runbook from the first-user quickstart and Runner README.
- Keep pairing-code and token handling explicit and safe.
- Keep local-native Apple Silicon evidence distinct from Docker/container paths.
- Keep thin local samples, reference evidence, quant fidelity, and future gold-lane evidence separate.

## Evidence Honesty Notes

- No gold-lane claim.
- No public leaderboard claim.
- No global model-quality or intelligence score.
- Thin local samples remain setup guidance.
- Reference checks remain intentionally selected follow-ups.
- Quant fidelity remains same-family/protocol-comparable only.

## Validation Plan

- `git diff --check`
- Documentation grep for forbidden placeholder mistakes:
  - no real `igrp_` pairing code in changed docs;
  - no bearer/upload token examples in changed docs beyond forbidden-token warnings;
  - no broad winner, public leaderboard, or gold-lane claims.

## Known Limits

- This slice does not run a fresh production upload.
- It does not add a Desktop UI affordance.
- It does not solve GitHub Actions pre-step failures.
- A real production pairing code is still required out of band for live Hub upload dogfood.
