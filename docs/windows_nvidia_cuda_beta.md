# Windows/NVIDIA CUDA Beta Prep

Status: v0.3.4 hardware-independent prep. This is not a public support promise.

InferGrade may proceed toward a Windows/NVIDIA technical beta only after one real Windows host completes install or selection, Hub pairing, a known-good GGUF run, upload, Result review, and support export. Until that happens, Runner reports CUDA as `preview` and keeps compatibility `blocked` with `full_loop_not_proven`.

## Runtime Path

- Target runtime family: `llama.cpp`.
- Target binary set: `llama_cpp_windows_cuda_x86_64`.
- Current delivery mode: explicit user selection of an existing CUDA-capable `llama.cpp` binary.
- Managed download is not enabled until a pinned, checksummed upstream artifact is selected and validated.
- CUDA requests must not silently fall back to CPU. If a user chooses CPU as a recovery path, the resulting run gets a separate CPU runtime selector.

## Preflight Data

Runner CUDA preflight captures bounded, support-safe fields:

- Windows system, architecture, and version.
- `nvidia-smi` availability.
- GPU name, VRAM, compute capability, and driver version.
- CUDA major version selected for driver-floor checks.
- Selected `llama.cpp` binary path and bounded `--version` smoke output.
- Runtime selector compatibility status, reason codes, probe summaries, support tier, and fallback boundary.

## Failure Modes

`no_nvidia_gpu`: No NVIDIA GPU rows were reported. Use the CPU path explicitly or run on a Windows host with an NVIDIA GPU.

`nvidia_smi_missing`: `nvidia-smi` is not available on `PATH`. Install or repair the NVIDIA driver package before attempting CUDA evidence.

`driver_too_old`: The NVIDIA driver is below the selected CUDA major floor. Upgrade the driver or select a runtime that targets an older CUDA major.

`runtime_binary_missing`: No pinned managed CUDA artifact or explicit binary was selected. Provide an existing CUDA-capable `llama.cpp` binary path for preflight.

`runtime_smoke_failed`: The selected CUDA binary did not pass `--version`. Re-select the binary, repair the runtime install, or keep CUDA evidence blocked.

`runtime_binary_mismatch`: The selected binary does not match the expected Windows CUDA binary set. Do not upload it as CUDA evidence.

`insufficient_vram`: The detected GPU has less memory than the selected model or quant needs. Choose a smaller quant/model or a GPU with more VRAM.

`model_too_large`: The chosen GGUF is too large for the detected VRAM or expected runtime overhead.

`artifact_download_failed`: The GGUF artifact could not be downloaded or verified. Retry the download or use a local artifact path.

`fallback_not_allowed`: A requested CUDA run must not silently execute as CPU evidence. Choose CPU explicitly if that is the intended recovery path.

`full_loop_not_proven`: Hardware-independent preflight passed far enough to classify the host, but the Windows/NVIDIA beta gate remains closed until a full Hub loop is proven on hardware.

## Support Boundary

Public copy must say "Windows/NVIDIA CUDA preview" until the full loop is proven. After proof, the support tier can advance to `technical_beta` for the validated path only. Linux CUDA, ROCm, Vulkan, and Windows AMD remain separate paths and must not inherit NVIDIA support claims.
