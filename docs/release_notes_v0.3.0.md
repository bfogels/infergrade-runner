# InferGrade Runner v0.3.0 Release Notes

Status: GA source and contract release for the v0.3 runtime-selector contract cutover.

## What Changed

- Runner package, Desktop, CLI, and Rust workspace versions advance to `0.3.0`.
- The published Runner contract advances to `0.3.0`.
- The contract bundle now includes `runtime_selector.schema.json`.
- Contract fixtures cover the Apple Silicon managed Metal reference path and the Windows/NVIDIA CUDA preflight-only preview path.
- Release bundle and container image defaults now use the stable `0.3.0` tag; preview tags remain available only when explicitly requested.

## Compatibility Boundary

- Apple Silicon/Metal remains the reference local path.
- Windows/NVIDIA CUDA is representable in the contract, but remains preflight-only until v0.3.4 proves one full loop.
- Runtime selectors are compatibility and provenance records, not marketing support claims.
- Silent fallback from a requested accelerator path to CPU remains outside the claim boundary.

## Validation Boundary

This release publishes the schema and release snapshot needed for Hub-side import and refusal checks. It does not publish notarized Desktop artifacts or claim Windows/NVIDIA full-loop support.
