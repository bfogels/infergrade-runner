# Windows/NVIDIA CUDA Beta Prep

Status: hardware-independent preview prep. This is not a public support promise.

InferGrade may proceed toward a Windows/NVIDIA technical beta only after one real Windows host completes install or selection, Hub pairing, a known-good GGUF run, upload, Result review, and support export. Until that happens, Runner reports CUDA as `preview` and keeps compatibility `blocked` with `full_loop_not_proven`.

## Runtime Path

- Target runtime family: `llama.cpp`.
- Target binary set: `llama_cpp_windows_cuda_x86_64`.
- Current delivery mode: explicit user selection of an existing CUDA-capable `llama.cpp` binary.
- A selected Windows CUDA preview runtime must record `binary_set`,
  `support_tier: preview`, checksum status, bounded binary fingerprints, and
  the preview claim boundary in `selected_runtime.json`.
- The preview selector requires the complete sibling binary set
  (`llama-cli.exe`, `llama-server.exe`, and `llama-perplexity.exe`) so a partial
  CUDA install cannot be recorded as a viable runtime.
- Managed download is not enabled until a pinned, checksummed upstream artifact is selected and validated.
- The selector reports `delivery.runtime_delivery_gate` so Hub and support tools can
  distinguish "user-selected preview only" from a managed runtime lane that is
  pinned and checksum-verifiable.
- CUDA requests must not silently fall back to CPU. If a user chooses CPU as a recovery path, the resulting run gets a separate CPU runtime selector.

## Preflight Data

Runner CUDA preflight captures bounded, support-safe fields:

- Windows system, architecture, and version.
- Common Windows aliases such as `Windows`, `Windows_NT`, and `win32` are normalized before compatibility checks so support exports and external probes do not create false `windows_host_required` blockers.
- `nvidia-smi` availability.
- GPU name, VRAM, compute capability, driver version, and CUDA version when `nvidia-smi` reports it.
- CUDA major version selected for driver-floor checks.
- Selected `llama.cpp` binary path and bounded `--version` smoke output.
- Runtime selector compatibility status, reason codes, probe summaries, support tier, and fallback boundary.

## Failure Modes

`no_nvidia_gpu`: No NVIDIA GPU rows were reported. Use the CPU path explicitly or run on a Windows host with an NVIDIA GPU.

`nvidia_smi_missing`: `nvidia-smi` is not available on `PATH`. Install or repair the NVIDIA driver package before attempting CUDA evidence.

`nvidia_smi_failed`: `nvidia-smi` was found but failed to return GPU rows. Repair the NVIDIA driver/runtime installation before attempting CUDA evidence.

`nvidia_smi_timeout`: `nvidia-smi` was found but did not return within the bounded preflight timeout. Repair or restart the NVIDIA driver/runtime stack before attempting CUDA evidence.

`driver_too_old`: The NVIDIA driver is below the selected CUDA major floor. Upgrade the driver or select a runtime that targets an older CUDA major.

`runtime_binary_missing`: No pinned managed CUDA artifact or explicit binary was selected. Provide an existing CUDA-capable `llama.cpp` binary path for preflight.

`runtime_binary_not_found`: The selected CUDA binary path does not exist. Re-select the binary path before attempting CUDA evidence.

`runtime_binary_not_executable`: The selected CUDA binary path exists but cannot be executed. Repair file permissions or re-select the binary before attempting CUDA evidence.

`runtime_smoke_timeout`: The selected CUDA binary did not return `--version` within the bounded smoke timeout. Re-select the binary, repair the runtime install, or keep CUDA evidence blocked.

`runtime_smoke_failed`: The selected CUDA binary did not pass `--version`. Re-select the binary, repair the runtime install, or keep CUDA evidence blocked.

`runtime_binary_mismatch`: The selected binary does not match the expected Windows CUDA binary set. Do not upload it as CUDA evidence.

`insufficient_vram`: The detected GPU has less memory than the selected model or quant needs. Choose a smaller quant/model or a GPU with more VRAM.

`model_too_large`: The chosen GGUF is too large for the detected VRAM or expected runtime overhead.

`artifact_download_failed`: The GGUF artifact could not be downloaded or verified. Retry the download or use a local artifact path.

`managed_runtime_not_pinned`: InferGrade has not pinned a Windows CUDA managed runtime artifact. Keep the path user-selected preview only.

`checksum_manifest_missing`: No checksum manifest exists for a managed Windows CUDA runtime artifact. Do not enable managed download or checksum-verified claims.

`fallback_not_allowed`: A requested CUDA run must not silently execute as CPU evidence. Choose CPU explicitly if that is the intended recovery path.

`full_loop_not_proven`: Hardware-independent preflight passed far enough to classify the host, but the Windows/NVIDIA beta gate remains closed until a full Hub loop is proven on hardware.

## Support Boundary

Support exports include a `cuda` block. If the captured environment has no
CUDA signal, the block says `included: false` with `reason:
no_cuda_signal`. If the host reports NVIDIA/CUDA,
`INFERGRADE_LLAMA_CPP_CUDA_CLI` is set, or the selected llama.cpp runtime record
names the Windows CUDA preview binary set, the block includes the same bounded
preflight selector used by doctor, including driver floor, selected binary,
selected GPU position/count on multi-GPU hosts, fallback, and claim-boundary fields. The block also includes a compact
`summary` with compatibility status, reason codes, GPU count, platform, driver
floor, selected GPU, selected runtime source, binary smoke result, binary
fingerprint status, runtime delivery gate, and next action so support triage
does not need to parse the full runtime selector first.

The preflight payload also includes a machine-readable `proof_gate` while
`full_loop_not_proven` is active. The required proof steps are:

1. Select a CUDA-capable `llama.cpp` runtime and record the Windows CUDA binary
   set plus preview claim boundary.
2. Pair a Windows/NVIDIA runner with Hub using a label and token state that can
   be inspected without secrets.
3. Run one known-good GGUF locally and keep manifest, summary, environment, and
   benchmark artifacts.
4. Upload the result bundle to Hub and preserve the CUDA runtime selector.
5. Review the owner-visible Hub Result and keep Windows/NVIDIA caveats visible.
6. Capture a secret-free support export that includes CUDA preflight and selected
   runtime context.

Public copy must say "Windows/NVIDIA CUDA preview" until the full loop is proven. After proof, the support tier can advance to `technical_beta` for the validated path only. Linux CUDA, ROCm, Vulkan, and Windows AMD remain separate paths and must not inherit NVIDIA support claims.
