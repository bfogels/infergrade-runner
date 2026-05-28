# InferGrade Runner v0.3.2 Release Notes

Status: GA source and contract release for confidence and repeatability reporting.

## What Changed

- Runner package, Desktop, CLI, and Rust workspace versions advance to `0.3.2`.
- The published Runner contract advances to `0.3.2`.
- Capability confidence labels now emit the v0.3.2 roadmap terms `repeated_local_sample` and `sampled_reference`.
- Existing `repeated_local_run` and `reference_sample` artifacts remain accepted as legacy aliases so older v0.2.x and v0.3.0 bundles can still be read.
- Capability summaries now include per-artifact and per-surface repeatability metadata: repetition count, median/p95 latency, TTFT variance, tokens/sec variance, pass-rate variance, failure rate, and instability reasons.

## Claim Boundary

- Repeated local samples report repeatability and instability metrics for the same local setup; they do not become leaderboard evidence.
- Sampled reference evidence remains scoped to the benchmark protocol and sample policy.
- Windows/NVIDIA CUDA remains preflight-only until v0.3.4 proves a full loop on hardware.

## Deferred

- Production `agent_dogfood` uploads remain deferred until an explicitly labeled `agent-dogfood-*` runner is paired.
