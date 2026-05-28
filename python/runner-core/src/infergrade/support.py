"""Support export helpers for local operator debugging."""

import os
from typing import Any, Dict, Optional

from infergrade import __version__
from infergrade.cuda import WINDOWS_CUDA_BINARY_SET, WINDOWS_CUDA_CLAIM_BOUNDARY, windows_cuda_preflight
from infergrade.environment import capture_environment
from infergrade.pairing import load_runner_profile, runner_profile_path
from infergrade.progress import load_progress
from infergrade.runtimes import selected_llama_cpp_runtime
from infergrade.utils import read_json, utcnow_iso, write_json


def build_support_export(run_dir: Optional[str] = None, execution_mode: Optional[str] = None) -> Dict[str, Any]:
    """Return a compact, secret-free support payload for a local runner session."""
    resolved_run_dir = os.path.abspath(os.path.expanduser(run_dir)) if run_dir else None
    progress = _redact_support_payload(load_progress(resolved_run_dir)) if resolved_run_dir else None
    detected_mode = (
        execution_mode
        or (progress or {}).get("request_context", {}).get("execution_mode")
        or "local_container"
    )
    environment = _redact_support_payload(capture_environment(detected_mode))
    payload = {
        "export_kind": "infergrade_runner_support_v1",
        "generated_at": utcnow_iso(),
        "runner_version": __version__,
        "secrets_excluded": True,
        "runner_profile_path": runner_profile_path(),
        "runner_profile": _sanitized_runner_profile(load_runner_profile()),
        "environment": environment,
        "cuda": _redact_support_payload(_cuda_support_payload(detected_mode, environment)),
        "run_dir": resolved_run_dir,
        "progress": progress,
        "manifest": _read_json_if_present(resolved_run_dir, "manifest.json"),
        "summary": _read_json_if_present(resolved_run_dir, "summary.json"),
        "validation": _read_json_if_present(resolved_run_dir, "validation.json"),
        "captured_environment": _read_json_if_present(resolved_run_dir, "artifacts", "environment.json"),
        "artifact_receipt": _read_json_if_present(resolved_run_dir, "artifacts", "receipts", "quant_artifact_resolution.json"),
        "files_present": _support_file_presence(resolved_run_dir),
    }
    return payload


def write_support_export(output_path: str, run_dir: Optional[str] = None, execution_mode: Optional[str] = None) -> str:
    """Write a support export to disk and return the normalized path."""
    resolved_output = os.path.abspath(os.path.expanduser(output_path))
    write_json(resolved_output, build_support_export(run_dir=run_dir, execution_mode=execution_mode))
    return resolved_output


def _cuda_support_payload(execution_mode: str, environment: Dict[str, Any]) -> Dict[str, Any]:
    """Return CUDA preflight context when a support export has CUDA signals."""
    cuda_signal_reason = _cuda_signal_reason(environment)
    if not cuda_signal_reason:
        return {
            "included": False,
            "reason": "no_cuda_signal",
            "claim_boundary": WINDOWS_CUDA_CLAIM_BOUNDARY,
        }
    runtime_path = _cuda_runtime_binary_path()
    preflight = windows_cuda_preflight(
        runtime_binary_path=runtime_path,
        cuda_major=_cuda_major_from_environment(environment),
        platform_snapshot=_platform_snapshot_from_environment(environment),
    )
    return {
        "included": True,
        "reason": cuda_signal_reason,
        "execution_mode": execution_mode,
        "claim_boundary": WINDOWS_CUDA_CLAIM_BOUNDARY,
        "summary": _cuda_support_summary(preflight),
        "preflight": preflight,
    }


def _cuda_support_summary(preflight: Dict[str, Any]) -> Dict[str, Any]:
    selector = preflight.get("selector") or {}
    compatibility = selector.get("compatibility") or {}
    platform = selector.get("platform") or {}
    accelerator = selector.get("accelerator") or {}
    driver = selector.get("driver") or {}
    delivery = selector.get("delivery") or {}
    binary = selector.get("binary") or {}
    fingerprint = binary.get("fingerprint") or {}
    selected_gpu = preflight.get("selected_gpu") or {}
    return {
        "status": compatibility.get("status") or "unknown",
        "reason_codes": list(compatibility.get("reason_codes") or []),
        "gpu_count": preflight.get("gpu_count"),
        "platform": {
            "system": platform.get("system"),
            "arch": platform.get("arch"),
            "version": platform.get("version"),
        },
        "gpu": {
            "model": accelerator.get("model"),
            "vram_bytes": accelerator.get("vram_bytes"),
            "compute_capability": accelerator.get("compute_capability"),
            "selected_position": selected_gpu.get("position"),
            "candidate_count": selected_gpu.get("count"),
        },
        "driver": {
            "version": driver.get("version"),
            "minimum_required": driver.get("minimum_required"),
            "cuda_major": driver.get("cuda_major"),
        },
        "runtime": {
            "source": delivery.get("source"),
            "binary_set": delivery.get("binary_set"),
            "binary_path_present": bool(binary.get("path")),
            "version_output": binary.get("version_output"),
            "fingerprint_status": fingerprint.get("status"),
            "sha256": fingerprint.get("sha256"),
            "size_bytes": fingerprint.get("size_bytes"),
        },
        "next_action": preflight.get("next_action"),
        "proof_gate": _cuda_support_proof_gate(preflight.get("proof_gate")),
    }


def _cuda_support_proof_gate(proof_gate: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    proof_gate = dict(proof_gate or {})
    return {
        "status": proof_gate.get("status") or "blocked",
        "reason_code": proof_gate.get("reason_code") or "full_loop_not_proven",
        "required_step_ids": [
            item.get("id")
            for item in list(proof_gate.get("required_steps") or [])
            if isinstance(item, dict) and item.get("id")
        ],
    }


def _environment_suggests_cuda(environment: Dict[str, Any]) -> bool:
    return bool(_cuda_signal_reason(environment))


def _cuda_signal_reason(environment: Dict[str, Any]) -> Optional[str]:
    if (
        environment.get("hardware_class") == "nvidia_gpu"
        or environment.get("accelerator_vendor") == "nvidia"
        or environment.get("accelerator_api") == "cuda"
    ):
        return "nvidia_cuda_environment"
    if os.environ.get("INFERGRADE_LLAMA_CPP_CUDA_CLI"):
        return "cuda_runtime_env_var"
    if _selected_cuda_runtime_cli_path():
        return "selected_cuda_runtime"
    return None


def _cuda_runtime_binary_path() -> Optional[str]:
    return os.environ.get("INFERGRADE_LLAMA_CPP_CUDA_CLI") or _selected_cuda_runtime_cli_path()


def _selected_cuda_runtime_cli_path() -> Optional[str]:
    selection = selected_llama_cpp_runtime() or {}
    if selection.get("binary_set") != WINDOWS_CUDA_BINARY_SET:
        return None
    binaries = selection.get("binaries") or {}
    path = binaries.get("cli")
    return str(path) if path else None


def _cuda_major_from_environment(environment: Dict[str, Any]) -> str:
    cuda_version = ((environment.get("driver_versions") or {}).get("cuda") or "").strip()
    return cuda_version.split(".", 1)[0] if cuda_version else "12"


def _platform_snapshot_from_environment(environment: Dict[str, Any]) -> Dict[str, str]:
    os_label = str(environment.get("os") or "").lower()
    system = os_label.split("-", 1)[0] if os_label else None
    if system == "win32":
        system = "windows"
    return {
        "system": system or "unknown",
        "arch": str(environment.get("cpu_architecture") or "unknown").lower(),
        "version": str(environment.get("os") or "") or None,
    }


def _sanitized_runner_profile(profile: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not profile:
        return None
    sanitized = dict(profile)
    if sanitized.get("access_token"):
        sanitized["access_token_present"] = True
        sanitized.pop("access_token", None)
    return _redact_support_payload(sanitized)


def _read_json_if_present(base_path: Optional[str], *parts: str) -> Optional[Dict[str, Any]]:
    if not base_path:
        return None
    path = os.path.join(base_path, *parts)
    if not os.path.exists(path):
        return None
    try:
        return _redact_support_payload(read_json(path))
    except Exception as exc:
        return {"error": str(exc), "path": path}


def _support_file_presence(run_dir: Optional[str]) -> Dict[str, bool]:
    if not run_dir:
        return {}
    expected = {
        "progress_json": ("progress.json",),
        "manifest_json": ("manifest.json",),
        "summary_json": ("summary.json",),
        "validation_json": ("validation.json",),
        "captured_environment": ("artifacts", "environment.json"),
        "artifact_receipt": ("artifacts", "receipts", "quant_artifact_resolution.json"),
    }
    return {
        key: os.path.exists(os.path.join(run_dir, *relative_parts))
        for key, relative_parts in expected.items()
    }


_SENSITIVE_KEY_MARKERS = (
    "access_token",
    "api_token",
    "authorization",
    "bearer",
    "completion_text",
    "credential",
    "hf_token",
    "huggingface_token",
    "model_output",
    "output_text",
    "pair_code",
    "pairing_code",
    "password",
    "prompt",
    "raw_output",
    "raw_outputs",
    "secret",
    "signed_url",
    "token",
)

_SENSITIVE_URL_MARKERS = (
    "x-amz-signature=",
    "x-amz-credential=",
    "x-goog-signature=",
    "signature=",
    "signed=",
    "token=",
)


def _redact_support_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            if _support_key_is_sensitive(str(key)):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = _redact_support_payload(item)
        return redacted
    if isinstance(value, list):
        return [_redact_support_payload(item) for item in value]
    if isinstance(value, str) and _support_value_is_sensitive(value):
        return "[redacted]"
    return value


def _support_key_is_sensitive(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized.endswith("_present"):
        return False
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


def _support_value_is_sensitive(value: str) -> bool:
    normalized = value.lower()
    if not (normalized.startswith("http://") or normalized.startswith("https://")):
        return False
    return any(marker in normalized for marker in _SENSITIVE_URL_MARKERS)
