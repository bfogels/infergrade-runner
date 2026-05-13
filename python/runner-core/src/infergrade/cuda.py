"""Windows/NVIDIA CUDA preflight helpers.

This module is intentionally probe-first. It does not claim Windows/NVIDIA is
supported; it builds the runtime-selector evidence needed for a technical beta
once hardware is available.
"""

import os
import platform
import re
import shutil
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple


CUDA_DRIVER_FLOORS = {
    "13": "580.0",
    "12": "525.0",
    "11": "450.0",
}

WINDOWS_CUDA_BINARY_SET = "llama_cpp_windows_cuda_x86_64"
WINDOWS_CUDA_CLAIM_BOUNDARY = (
    "Windows/NVIDIA CUDA path is preflight-only until one full install, run, upload, and publish loop is proven on hardware."
)


def parse_version(value: Optional[str]) -> Tuple[int, ...]:
    parts = re.findall(r"\d+", str(value or ""))
    return tuple(int(part) for part in parts)


def version_at_least(observed: Optional[str], minimum: Optional[str]) -> bool:
    observed_parts = parse_version(observed)
    minimum_parts = parse_version(minimum)
    if not observed_parts or not minimum_parts:
        return False
    width = max(len(observed_parts), len(minimum_parts))
    return observed_parts + (0,) * (width - len(observed_parts)) >= minimum_parts + (0,) * (width - len(minimum_parts))


def minimum_driver_for_cuda(cuda_major: Optional[str]) -> Optional[str]:
    if not cuda_major:
        return CUDA_DRIVER_FLOORS["12"]
    return CUDA_DRIVER_FLOORS.get(str(cuda_major).split(".")[0])


def parse_nvidia_smi_csv(output: str) -> List[Dict[str, Any]]:
    """Parse bounded `nvidia-smi --query-gpu` CSV output."""
    rows: List[Dict[str, Any]] = []
    for line in str(output or "").splitlines():
        line = line.strip()
        if not line or line.lower().startswith("name,"):
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            continue
        name, driver_version, memory_mib = parts[:3]
        compute_capability = parts[3] if len(parts) > 3 and parts[3] else None
        cuda_version = parts[4] if len(parts) > 4 and parts[4] else None
        try:
            vram_bytes = int(float(memory_mib)) * 1024 * 1024
        except (TypeError, ValueError):
            vram_bytes = None
        rows.append(
            {
                "name": name,
                "driver_version": driver_version,
                "vram_bytes": vram_bytes,
                "compute_capability": compute_capability,
                "cuda_version": cuda_version,
            }
        )
    return rows


def detect_windows_version() -> Dict[str, Optional[str]]:
    return {
        "system": "windows" if platform.system().lower().startswith("win") else platform.system().lower() or "unknown",
        "arch": platform.machine().lower() or "unknown",
        "version": platform.version() or platform.release() or None,
    }


def _run_nvidia_smi(nvidia_smi_path: str) -> Tuple[List[Dict[str, Any]], str]:
    completed = subprocess.run(
        [
            nvidia_smi_path,
            "--query-gpu=name,driver_version,memory.total,compute_cap",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=8,
    )
    raw = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode != 0:
        return [], raw
    return parse_nvidia_smi_csv(raw), raw


def _binary_version(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        completed = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    output = (completed.stdout or completed.stderr or "").strip()
    return output.splitlines()[0] if output else None


def windows_cuda_preflight(
    runtime_binary_path: Optional[str] = None,
    cuda_major: str = "12",
    nvidia_smi_path: Optional[str] = None,
    nvidia_smi_output: Optional[str] = None,
    platform_snapshot: Optional[Dict[str, str]] = None,
    selected_binary_set: str = WINDOWS_CUDA_BINARY_SET,
    required_vram_bytes: Optional[int] = None,
    artifact_download_error: Optional[str] = None,
    which: Callable[[str], Optional[str]] = shutil.which,
) -> Dict[str, Any]:
    """Return a runtime selector plus actionable CUDA readiness details."""
    platform_info = dict(platform_snapshot or detect_windows_version())
    if platform_info.get("system") == "win32":
        platform_info["system"] = "windows"
    nvidia_smi = nvidia_smi_path or which("nvidia-smi")
    probes: List[Dict[str, Any]] = []
    reason_codes: List[str] = []
    gpu_rows: List[Dict[str, Any]] = []

    if not nvidia_smi and nvidia_smi_output is None:
        probes.append({"id": "nvidia_smi", "status": "failed", "detail": "nvidia-smi is not available on PATH."})
        reason_codes.append("nvidia_smi_missing")
    else:
        try:
            gpu_rows = parse_nvidia_smi_csv(nvidia_smi_output) if nvidia_smi_output is not None else _run_nvidia_smi(nvidia_smi)[0]
        except Exception as exc:
            gpu_rows = []
            probes.append({"id": "nvidia_smi", "status": "failed", "detail": str(exc)})
            reason_codes.append("nvidia_smi_failed")
        if gpu_rows:
            probes.append({"id": "nvidia_smi", "status": "passed", "observed": "detected %d NVIDIA GPU(s)" % len(gpu_rows)})
        elif "nvidia_smi_failed" not in reason_codes and "nvidia_smi_missing" not in reason_codes:
            probes.append({"id": "nvidia_smi", "status": "failed", "detail": "No NVIDIA GPU rows were reported."})
            reason_codes.append("no_nvidia_gpu")

    selected_gpu = gpu_rows[0] if gpu_rows else {}
    minimum_driver = minimum_driver_for_cuda(cuda_major)
    driver_version = selected_gpu.get("driver_version")
    if driver_version and minimum_driver:
        if version_at_least(driver_version, minimum_driver):
            probes.append({"id": "cuda_driver_floor", "status": "passed", "observed": "driver %s >= %s" % (driver_version, minimum_driver)})
        else:
            probes.append({"id": "cuda_driver_floor", "status": "failed", "observed": "driver %s < %s" % (driver_version, minimum_driver)})
            reason_codes.append("driver_too_old")
    elif gpu_rows:
        probes.append({"id": "cuda_driver_floor", "status": "unknown", "detail": "Driver version or CUDA floor was not available."})
        reason_codes.append("driver_version_unknown")

    if gpu_rows and required_vram_bytes is not None:
        observed_vram = selected_gpu.get("vram_bytes")
        if observed_vram is not None and observed_vram >= required_vram_bytes:
            probes.append({"id": "vram_capacity", "status": "passed", "observed": observed_vram})
        else:
            probes.append(
                {
                    "id": "vram_capacity",
                    "status": "failed",
                    "observed": observed_vram,
                    "detail": "Detected VRAM is below the selected model or quant requirement.",
                }
            )
            reason_codes.extend(["insufficient_vram", "model_too_large"])

    if artifact_download_error:
        probes.append({"id": "artifact_download", "status": "failed", "detail": str(artifact_download_error)})
        reason_codes.append("artifact_download_failed")

    runtime_path = runtime_binary_path or os.environ.get("INFERGRADE_LLAMA_CPP_CUDA_CLI")
    runtime_version = _binary_version(runtime_path)
    if selected_binary_set != WINDOWS_CUDA_BINARY_SET:
        probes.append(
            {
                "id": "runtime_binary_set",
                "status": "failed",
                "observed": selected_binary_set,
                "detail": "Selected binary set does not match the Windows CUDA preview lane.",
            }
        )
        reason_codes.append("runtime_binary_mismatch")
    if runtime_path and runtime_version:
        probes.append({"id": "cuda_runtime_binary", "status": "passed", "observed": runtime_version})
    elif runtime_path:
        probes.append({"id": "cuda_runtime_binary", "status": "failed", "detail": "Selected CUDA llama.cpp binary did not pass version smoke."})
        reason_codes.append("runtime_smoke_failed")
    else:
        probes.append({"id": "cuda_runtime_binary", "status": "failed", "detail": "No pinned/checksummed CUDA llama.cpp binary is selected."})
        reason_codes.append("runtime_binary_missing")

    if platform_info.get("system") != "windows":
        reason_codes.append("windows_host_required")
        probes.append({"id": "windows_platform", "status": "failed", "observed": platform_info.get("system")})
    else:
        probes.append({"id": "windows_platform", "status": "passed", "observed": platform_info.get("version")})

    if reason_codes:
        reason_codes.append("fallback_not_allowed")
    reason_codes.append("full_loop_not_proven")
    status = "blocked" if reason_codes else "ready"
    selector = {
        "runtime_selector_version": "0.3",
        "runtime_family": "llama.cpp",
        "platform": {
            "system": platform_info.get("system") or "unknown",
            "arch": platform_info.get("arch") or "x86_64",
            "version": platform_info.get("version"),
        },
        "accelerator": {
            "vendor": "nvidia" if gpu_rows else "unknown",
            "api": "cuda",
            "model": selected_gpu.get("name"),
            "vram_bytes": selected_gpu.get("vram_bytes"),
            "compute_capability": selected_gpu.get("compute_capability"),
        },
        "driver": {
            "version": driver_version,
            "minimum_required": minimum_driver,
            "cuda_major": str(cuda_major),
        },
        "delivery": {
            "mode": "user_selected",
            "binary_set": selected_binary_set,
            "source": "explicit_path" if runtime_path else "run_config",
            "selected_by": "user_choice" if runtime_path else "run_config",
        },
        "binary": {
            "path": runtime_path,
            "version_output": runtime_version,
            "checksum_verified": False,
            "signature_verified": False,
        },
        "compatibility": {
            "status": status,
            "reason_codes": sorted(set(reason_codes)),
            "probes": probes,
        },
        "support": {
            "tier": "preview",
            "claim_boundary": WINDOWS_CUDA_CLAIM_BOUNDARY,
        },
        "fallback": {
            "allowed": False,
            "mode": None,
            "reason": "CUDA requests must not silently upload CPU evidence.",
        },
    }
    return {
        "selector": selector,
        "gpu_count": len(gpu_rows),
        "hardware_blocked": True,
        "next_action": "Validate on a Windows/NVIDIA machine before enabling evidence-producing technical beta.",
    }
