# Runtime Selector Design

Status: v0.3.0 design input. This document defines the Runner-owned runtime selector shape that Hub should consume when v0.3.0 cuts over schemas.

## Purpose

InferGrade needs one contract for the runtime path that produced, or is expected to produce, evidence. The contract must represent the current Apple Silicon managed `llama.cpp` path, explicit local binaries, container execution, CPU-only fallbacks, and the planned Windows/NVIDIA CUDA technical beta without schema-specific exceptions in Hub.

The selector is not a marketing support claim. It is a structured compatibility and provenance record with an explicit support tier, probe result, fallback boundary, and claim boundary.

The selector is also not execution authority. It describes requirements and
compatibility. For a real native run, Runner resolves it together with local
operator preferences into one exact `runtime_build_id` and a private
per-attempt lock. Result records then carry a compact `runtime_receipt`; Hub
must not choose a local path or replace that receipt with a runtime label.

## Inputs

The field plan follows the active roadmap v0.3.0 runtime-selector scope and the CUDA feasibility decision in `infergrade-hub/docs/cuda_feasibility_report.md`:

- Mac/Metal remains the reference path.
- Windows/NVIDIA/CUDA may proceed as a technical beta only after one real full loop is proven.
- CPU, Linux CUDA, Vulkan, ROCm, and user-selected binaries must remain representable without implying support parity.
- Silent fallback from CUDA to CPU is not allowed.

## Contract Shape

The v0.3 runtime selector should be a Runner-owned object attached to run configs, readiness responses, result bundles, and support exports where applicable.

```json
{
  "runtime_selector_version": "0.3",
  "runtime_family": "llama.cpp",
  "platform": {
    "system": "macos",
    "arch": "aarch64",
    "version": "14.6"
  },
  "accelerator": {
    "vendor": "apple",
    "api": "metal",
    "model": "Apple M4 Max",
    "vram_bytes": null,
    "compute_capability": null
  },
  "delivery": {
    "mode": "managed_download",
    "binary_set": "llama_cpp_macos_metal_aarch64",
    "source": "infergrade_runtime_manifest",
    "selected_by": "managed_recommendation"
  },
  "binary": {
    "path": "/Users/example/Library/Caches/infergrade/runtimes/llama.cpp/llama-cli",
    "version_output": "llama.cpp build ...",
    "checksum_verified": true,
    "signature_verified": false
  },
  "compatibility": {
    "status": "ready",
    "reason_codes": [],
    "probes": [
      {
        "id": "binary_version_smoke",
        "status": "passed",
        "observed": "llama.cpp build ..."
      }
    ]
  },
  "support": {
    "tier": "reference",
    "claim_boundary": "Apple Silicon Metal managed runtime path validated for private beta local GGUF runs."
  },
  "fallback": {
    "allowed": false,
    "mode": null,
    "reason": "Do not silently change accelerator API for an evidence-producing run."
  }
}
```

## Field Semantics

### Platform

- `platform.system`: `macos`, `windows`, or `linux`.
- `platform.arch`: `aarch64`, `x86_64`, or another normalized architecture only after Runner can detect it.
- `platform.version`: OS version when available. For Windows/NVIDIA support exports, include Windows edition/build when the probe can capture it.

### Accelerator

- `accelerator.vendor`: `apple`, `nvidia`, `amd`, `intel`, `cpu`, or `unknown`.
- `accelerator.api`: `metal`, `cuda`, `rocm`, `vulkan`, `cpu`, or `unknown`.
- `accelerator.model`: device name from the local machine, not inferred from a selected runtime.
- `accelerator.vram_bytes`: physical or reported accelerator memory when available. Apple unified memory may remain null unless the probe can report a meaningful comparable value.
- `accelerator.compute_capability`: CUDA compute capability for NVIDIA paths when a runtime or driver probe can capture it.

### Delivery

- `delivery.mode`: `managed_download`, `user_selected`, `system_path`, `container`, or `bundled`.
- `delivery.binary_set`: a stable Runner-owned identifier for the expected binary family, such as `llama_cpp_macos_metal_aarch64` or `llama_cpp_windows_cuda_x86_64`.
- `delivery.source`: where the runtime came from, such as `infergrade_runtime_manifest`, `explicit_path`, `path_lookup`, `container_image`, or `desktop_bundle`.
- `delivery.selected_by`: `managed_recommendation`, `user_choice`, `run_config`, `environment`, or `container_runtime`.
- `delivery.runtime_delivery_gate`: optional status object for preview lanes that
  are not yet available as a managed runtime. Windows/NVIDIA CUDA uses this to
  state that the current lane is user-selected only until the pinned candidate
  artifact passes Windows hardware validation, Hub upload, Result review, and
  support export.

### Binary

- `binary.path`: the selected executable path for native paths. Redact or omit in public views when it would expose local usernames or private directories.
- `binary.version_output`: bounded version smoke output. Do not store raw command output beyond the version probe.
- `binary.checksum_verified`: true only when a managed download checksum has been verified against the Runner manifest.
- `binary.signature_verified`: true only when an independent signature verification lane exists and passed. A checksum alone is not a signature.

### Driver

- `driver.version`: accelerator driver version when the local probe can capture it.
- `driver.minimum_required`: minimum known driver version for the requested accelerator/runtime family.
- `driver.cuda_major`: CUDA major used for NVIDIA driver-floor checks.
- CUDA version reported by `nvidia-smi` should be recorded as a bounded compatibility probe when available. Older drivers may omit this signal; absence is not a preflight failure by itself.

### Compatibility

- `compatibility.status`: `ready`, `warning`, `blocked`, `unsupported`, or `unknown`.
- `compatibility.reason_codes`: stable machine-readable codes. Initial codes should include `no_accelerator_detected`, `nvidia_smi_missing`, `nvidia_smi_failed`, `driver_too_old`, `runtime_binary_missing`, `runtime_smoke_failed`, `checksum_failed`, `candidate_runtime_not_validated`, `candidate_review_not_complete`, `managed_download_not_enabled`, `model_too_large`, `unsupported_model_architecture`, `container_runtime_missing`, and `fallback_not_allowed`.
- `compatibility.probes`: ordered probe records. Each probe should have `id`, `status`, and bounded `observed` or `detail` fields after redaction.

### Support Tier

`support.tier` must separate product support from technical possibility:

- `reference`: Apple Silicon/Metal private-beta path with managed runtime proof.
- `technical_beta`: Windows/NVIDIA CUDA only after a hardware host proves one full loop.
- `best_effort`: Linux CUDA and explicit user-selected native binaries where Runner can run but support is limited.
- `preview`: CPU, Vulkan, ROCm, and other paths useful for detection or development but not a launch promise.
- `unsupported`: detected combination should not be offered for evidence-producing runs.

### Claim Boundary

`support.claim_boundary` is required when a selector is surfaced to Hub. It should explain what the selector proves in one sentence, for example:

- `Apple Silicon Metal managed runtime path validated for local GGUF runs.`
- `Windows/NVIDIA CUDA technical beta path detected; full-loop support requires explicit beta validation.`
- `User-selected llama.cpp binary; InferGrade records provenance but does not endorse the build.`
- `Container runtime path; host accelerator behavior is bounded by the container image and runtime configuration.`

## Fallback Behavior

Fallbacks must be explicit and non-silent:

- A run requested for CUDA must not silently run on CPU and upload as CUDA evidence.
- A managed runtime checksum failure must block managed execution instead of falling back to a system binary.
- A user-selected binary may be used only when the selector records `delivery.mode: "user_selected"` and preserves the claim boundary.
- Container fallback from native is allowed only when the user or run config explicitly chose container execution.
- Hub may show an alternate path as a recovery action, but the resulting run gets a new selector.
- Runtime fallback may occur only before evidence measurement begins and must
  create a new attempt lock. Resume always reuses the saved lock. After
  measurement starts, another runtime requires a new attempt rather than an
  in-place selector update.

## Exact Runtime Receipt

`execution.runtime_receipt` is the evidence binding produced after a successful
native run. It records:

- an immutable `runtime_build_id` derived from the platform, runtime interface,
  content scope, and normalized execution-tree file manifest;
- the per-attempt `runtime_lock_id`;
- runtime origin, maturity, and provenance strength as separate dimensions;
- the exact CLI/server/perplexity role digests without absolute local paths;
- the full execution-tree file count and manifest digest; and
- successful pre-launch and post-run verification with silent substitution
  explicitly disabled.

The complete file manifest is emitted once as a receipt artifact. Result rows
use the compact projection so multi-profile bundles do not duplicate every
library entry. Different build ids remain distinct evidence setup facts; any
future cross-build comparison policy must be dimension-specific rather than a
generic runtime-equivalence cohort.

## Initial Selector Matrix

| Path | Platform | Accelerator API | Delivery mode | Support tier | Compatibility bar |
| --- | --- | --- | --- | --- | --- |
| Apple Silicon managed `llama.cpp` | macOS aarch64 | Metal | managed_download | reference | manifest checksum, expected binaries, version smoke |
| Apple Silicon selected local binary | macOS aarch64 | Metal or unknown | user_selected/system_path | best_effort | executable exists, version smoke, model architecture check |
| Container `llama.cpp` | macOS/Linux | CPU or runtime-defined | container | best_effort | container runtime available, image present/pinned |
| Windows/NVIDIA CUDA | Windows x86_64 | CUDA | managed_download or user_selected | technical_beta after proof | NVIDIA GPU, driver version, compute capability, VRAM, CUDA runtime, binary smoke |
| Linux CUDA CLI | Linux x86_64 | CUDA | user_selected/system_path/container | best_effort | same CUDA probes where available |
| CPU-only | any | CPU | user_selected/system_path/container | preview | explicit CPU selection, no accelerator overclaim |
| ROCm/Vulkan | Linux/Windows | ROCm/Vulkan | user_selected/system_path | preview | detection/preflight only until proven |

## Schema Cutover Plan

1. Add the runtime selector object to Runner schemas and examples.
2. Emit it from native readiness, run config normalization, result bundle metadata, and support export paths.
3. Keep legacy runtime fields during a transition window, but derive them from the selector when possible.
4. Export the Runner contract bundle with selector fixtures for Metal, CUDA, CPU, container, managed runtime, and selected binary.
5. Update Hub pinned contracts and reject unsupported or mismatched selector versions.
6. Add Hub tests proving unsupported runtime/contract combinations fail visibly rather than degrading into old assumptions.

## Privacy And Redaction

Runtime selectors may contain local paths, host details, driver versions, and version-smoke text. Support export redaction must remove secrets and signed URLs as today, and public Hub surfaces must avoid exposing local usernames, private directories, runner labels, or machine details unless the owner explicitly publishes them as part of a public result summary.

## Open v0.3 Decisions

- Whether `platform.version` is required for all selectors or only support exports.
- Whether Apple unified memory should map into `accelerator.vram_bytes` or a separate memory field.
- Whether `binary_set` should be generated from the runtime manifest id or kept as a shorter compatibility lane id.
- The exact Hub policy for accepting older result bundles during the transition window.
