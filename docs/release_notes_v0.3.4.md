# InferGrade Runner v0.3.4 Release Notes

## Summary

Runner v0.3.4 adds hardware-independent Windows/NVIDIA CUDA beta preparation while keeping CUDA evidence blocked until a real Windows/NVIDIA full loop is proven.

## Contract Changes

- Runtime selector examples now include bounded NVIDIA driver metadata for CUDA preflight.
- The Runner contract bundle includes Windows/NVIDIA CUDA beta support-boundary docs.
- The Windows CUDA preview selector remains `support.tier: preview` and `compatibility.status: blocked` while `full_loop_not_proven` is present.

## Runner Changes

- Added CUDA preflight helpers for Windows version, `nvidia-smi` CSV parsing, GPU VRAM, compute capability, driver floor checks, selected `llama.cpp` binary smoke, and explicit fallback refusal.
- Added a Windows CUDA CLI preview runtime manifest entry without managed download or checksum claims.
- Added doctor output for CUDA-selected local-native requests so unsupported hardware/runtime states fail visibly before execution.

## Validation And Limits

- Synthetic fixture tests cover detected NVIDIA GPUs, old drivers, selected runtime smoke, runtime-binary-missing, and doctor preflight wiring.
- Windows/NVIDIA remains hardware-blocked for evidence-producing support until one full install or selection, Hub pairing, GGUF run, upload, Result review, and support export is completed on real hardware.
