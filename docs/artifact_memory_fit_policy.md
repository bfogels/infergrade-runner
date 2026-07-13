# GGUF Artifact Memory Fit Policy

`gguf_artifact_memory_fit_v1` lets consumers produce decision-supporting memory allocation estimates before running a GGUF. Runner owns the policy, its output schema, and the exported assumptions.

The estimator always accepts an exact GGUF artifact size and emits ranges for 2K, 8K, and 32K context buckets. When complete GGUF or repository-config architecture metadata is available, it combines the artifact size as a resident-tensor proxy, a dense-transformer KV-cache formula, and an explicitly uncalibrated runtime-overhead range. Without architecture metadata it uses deliberately wide, versioned fallback ranges from the same policy. The fallback needs no additional repository request beyond the artifact-size resolver.

These are artifact estimates, not measurements. They do not prove that a setup fits, do not represent device VRAM, do not model offload, and are not guaranteed bounds. Sliding-window, recurrent, hybrid, MLA, non-F16-KV, and incomplete-attention architectures are outside version 1. A real run should replace or calibrate these estimates with context-matched runtime evidence.

The machine-readable policy is `schemas/policies/artifact_memory_fit_policy.v1.json`; output artifacts conform to `schemas/json/artifact_memory_fit.schema.json`. Both are part of the Runner contract export. The policy also owns deployment-profile context-bucket mappings and the `fits`/`tight`/`over` capacity-ratio thresholds so consumers do not redefine those values.

Python consumers can call `build_gguf_artifact_memory_fit` for an in-memory payload or `export_gguf_artifact_memory_fit` for deterministic JSON output. The caller must identify whether artifact size came from a local file stat or repository metadata; guessed sizes are rejected.
