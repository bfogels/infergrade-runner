"""Environment and hardware detection for InferGrade runner executions."""

import json
import os
import platform
import re
import subprocess
from typing import Any, Dict, Optional

from infergrade.utils import stable_hash


_PHYSICAL_MEMORY_RE = re.compile(r"([0-9.]+)\s*GB", re.IGNORECASE)


def _run_command(command) -> Optional[str]:
    """Run a shell command and return stripped stdout when it succeeds."""
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    output = (completed.stdout or "").strip()
    return output or None


def _parse_gb(raw_value: str) -> Optional[float]:
    """Parse a memory string like `16 GB` into a float."""
    if not raw_value:
        return None
    match = _PHYSICAL_MEMORY_RE.search(str(raw_value))
    if not match:
        return None
    return round(float(match.group(1)), 2)


def _numeric_memory_gb(raw_value: Any) -> Optional[float]:
    """Coerce a raw memory quantity in bytes or MiB-like units into GiB."""
    if raw_value in (None, ""):
        return None
    try:
        numeric = float(str(raw_value).replace(",", "").strip())
    except ValueError:
        return None
    if numeric <= 0:
        return None
    if numeric > 1024 ** 3:
        return round(numeric / float(1024 ** 3), 2)
    if numeric > 1024:
        return round(numeric / 1024.0, 2)
    return round(numeric, 2)


def _detect_memory_gb() -> Optional[float]:
    """Detect total system memory across common Linux and macOS environments."""
    sysctl_mem = _run_command(["sysctl", "-n", "hw.memsize"])
    if sysctl_mem:
        try:
            return round(int(sysctl_mem) / float(1024 ** 3), 2)
        except ValueError:
            pass
    if os.path.exists("/proc/meminfo"):
        try:
            with open("/proc/meminfo", "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("MemTotal:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            return round(int(parts[1]) / float(1024 ** 2), 2)
        except Exception:
            pass
    if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names and "SC_PHYS_PAGES" in os.sysconf_names:
        page_size = os.sysconf("SC_PAGE_SIZE")
        phys_pages = os.sysconf("SC_PHYS_PAGES")
        return round((page_size * phys_pages) / float(1024 ** 3), 2)
    return None


def _detect_nvidia_gpu() -> Optional[Dict[str, Any]]:
    """Detect NVIDIA accelerators through `nvidia-smi` when available."""
    output = _run_command(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    if not output:
        return None
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return None
    models = []
    vrams = []
    driver_versions = []
    for line in lines:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        models.append(parts[0])
        try:
            vrams.append(float(parts[1]))
        except ValueError:
            continue
        if len(parts) >= 3 and parts[2]:
            driver_versions.append(parts[2])
    cuda_output = _run_command(["nvidia-smi"])
    cuda_version = None
    if cuda_output:
        match = re.search(r"CUDA Version:\s*([0-9.]+)", cuda_output)
        if match:
            cuda_version = match.group(1)
    if not models:
        return None
    return {
        "accelerator_type": "gpu",
        "accelerator_vendor": "nvidia",
        "accelerator_model": models[0],
        "accelerator_vram_gb": round(max(vrams) / 1024.0, 2) if vrams else None,
        "accelerator_count": len(models),
        "hardware_class": "nvidia_gpu",
        "memory_architecture": "discrete_vram",
        "accelerator_api": "cuda",
        "driver_versions": {
            "nvidia": driver_versions[0] if driver_versions else None,
            "cuda": cuda_version,
        },
    }


def _find_first_matching_value(payload: Dict[str, Any], candidates) -> Optional[Any]:
    """Find the first value whose key loosely matches one of the candidate substrings."""
    for key, value in payload.items():
        lowered = str(key).lower()
        if any(candidate in lowered for candidate in candidates) and value not in (None, ""):
            return value
    return None


def _detect_amd_gpu() -> Optional[Dict[str, Any]]:
    """Detect AMD/ROCm accelerators through `rocm-smi` when available."""
    output = _run_command(["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--json"])
    if not output:
        return None
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    cards = [value for value in payload.values() if isinstance(value, dict)]
    if not cards:
        return None
    models = []
    vrams = []
    for card in cards:
        model = _find_first_matching_value(card, ["card sku", "card model", "product name", "device name", "series"])
        if model:
            models.append(str(model))
        vram_value = _find_first_matching_value(card, ["vram total memory", "total memory"])
        vram_gb = _numeric_memory_gb(vram_value)
        if vram_gb is not None:
            vrams.append(vram_gb)
    if not models:
        return None
    return {
        "accelerator_type": "gpu",
        "accelerator_vendor": "amd",
        "accelerator_model": models[0],
        "accelerator_vram_gb": max(vrams) if vrams else None,
        "accelerator_count": len(models),
        "hardware_class": "amd_gpu",
        "memory_architecture": "discrete_vram",
        "accelerator_api": "rocm",
    }


def _detect_apple_silicon_gpu() -> Optional[Dict[str, Any]]:
    """Detect Apple Silicon GPU characteristics through `system_profiler`."""
    if platform.system().lower() != "darwin":
        return None
    output = _run_command(["system_profiler", "SPDisplaysDataType", "SPHardwareDataType", "-json"])
    if not output:
        return None
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None
    displays = payload.get("SPDisplaysDataType") or []
    hardware = (payload.get("SPHardwareDataType") or [{}])[0]
    if not displays:
        return None
    gpu = displays[0]
    model = gpu.get("sppci_model") or gpu.get("_name") or hardware.get("chip_type")
    vendor = gpu.get("spdisplays_vendor") or "apple"
    memory_gb = _parse_gb(str(hardware.get("physical_memory") or "")) or _detect_memory_gb()
    accelerator_type = "unified_memory_gpu"
    device_type = str(gpu.get("sppci_device_type") or "").lower()
    if "gpu" in device_type:
        accelerator_type = "gpu"
    return {
        "accelerator_type": accelerator_type,
        "accelerator_vendor": "apple" if "apple" in str(vendor).lower() else vendor,
        "accelerator_model": model,
        "accelerator_vram_gb": memory_gb,
        "accelerator_count": 1,
        "hardware_class": "apple_silicon",
        "memory_architecture": "unified_memory",
        "accelerator_api": "metal",
        "machine_model": hardware.get("machine_model"),
        "chip_type": hardware.get("chip_type"),
        "gpu_cores": gpu.get("sppci_cores"),
    }


def _default_accelerator_payload() -> Dict[str, Any]:
    """Return the fallback accelerator payload when no accelerator is detected."""
    return {
        "accelerator_type": "cpu",
        "accelerator_vendor": None,
        "accelerator_model": None,
        "accelerator_vram_gb": None,
        "accelerator_count": 0,
        "hardware_class": "cpu_only",
        "memory_architecture": "system_memory",
        "accelerator_api": None,
    }


def _normalize_accelerator_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Backfill normalized hardware fields so older detector payloads still compare well."""
    normalized = dict(payload or {})
    accelerator_type = normalized.get("accelerator_type")
    vendor = str(normalized.get("accelerator_vendor") or "").lower()
    memory_architecture = normalized.get("memory_architecture")
    hardware_class = normalized.get("hardware_class")
    accelerator_api = normalized.get("accelerator_api")

    if not hardware_class:
        if vendor == "nvidia":
            hardware_class = "nvidia_gpu"
        elif vendor == "amd":
            hardware_class = "amd_gpu"
        elif vendor == "apple":
            hardware_class = "apple_silicon"
        elif accelerator_type == "cpu":
            hardware_class = "cpu_only"
    if not memory_architecture:
        if hardware_class == "apple_silicon":
            memory_architecture = "unified_memory"
        elif hardware_class in ("nvidia_gpu", "amd_gpu"):
            memory_architecture = "discrete_vram"
        elif accelerator_type == "cpu":
            memory_architecture = "system_memory"
    if not accelerator_api:
        if hardware_class == "nvidia_gpu":
            accelerator_api = "cuda"
        elif hardware_class == "amd_gpu":
            accelerator_api = "rocm"
        elif hardware_class == "apple_silicon":
            accelerator_api = "metal"

    normalized["hardware_class"] = hardware_class
    normalized["memory_architecture"] = memory_architecture
    normalized["accelerator_api"] = accelerator_api
    return normalized


def _load_host_environment_override() -> Optional[Dict[str, Any]]:
    """Load an optional host-side environment snapshot passed into a containerized runner."""
    snapshot_path = os.environ.get("INFERGRADE_HOST_ENVIRONMENT_PATH")
    if not snapshot_path or not os.path.isfile(snapshot_path):
        return None
    try:
        with open(snapshot_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _detect_cpu_model() -> str:
    """Detect the most helpful CPU label for the current platform."""
    brand = _run_command(["sysctl", "-n", "machdep.cpu.brand_string"])
    if brand:
        return brand
    return platform.processor() or platform.machine()


def _detect_machine_model() -> Optional[str]:
    """Detect the most useful machine-model identifier when the platform exposes one."""
    hw_model = _run_command(["sysctl", "-n", "hw.model"])
    if hw_model:
        return hw_model
    return None


def capture_environment(execution_mode: str) -> Dict[str, Any]:
    """Capture hardware and OS facts for a InferGrade run."""
    gpu = _normalize_accelerator_payload(
        _detect_nvidia_gpu() or _detect_amd_gpu() or _detect_apple_silicon_gpu() or _default_accelerator_payload()
    )
    environment_class = {
        "local_container": "local_workstation",
        "local_native": "local_workstation",
        "cloud_container": "cloud_vm",
        "manual_external": "external_environment",
    }.get(execution_mode, "unknown")
    payload = {
        "environment_class": environment_class,
        "accelerator_type": gpu["accelerator_type"],
        "accelerator_vendor": gpu["accelerator_vendor"],
        "accelerator_model": gpu["accelerator_model"],
        "accelerator_vram_gb": gpu["accelerator_vram_gb"],
        "accelerator_count": gpu["accelerator_count"],
        "hardware_class": gpu.get("hardware_class"),
        "memory_architecture": gpu.get("memory_architecture"),
        "accelerator_api": gpu.get("accelerator_api"),
        "cpu_model": _detect_cpu_model(),
        "cpu_architecture": platform.machine(),
        "cpu_core_count": os.cpu_count(),
        "memory_gb": _detect_memory_gb(),
        "os": "%s-%s" % (platform.system().lower(), platform.release()),
        "kernel_version": platform.version(),
        "machine_model": _detect_machine_model(),
        "driver_versions": {},
        "container_runtime": "docker" if os.path.exists("/.dockerenv") else None,
    }
    if gpu.get("driver_versions"):
        payload["driver_versions"] = gpu["driver_versions"]
    if gpu.get("machine_model"):
        payload["machine_model"] = gpu["machine_model"]
    if gpu.get("chip_type"):
        payload["chip_type"] = gpu["chip_type"]
    if gpu.get("gpu_cores"):
        payload["gpu_cores"] = gpu["gpu_cores"]
    docker_version = _run_command(["docker", "--version"])
    if docker_version:
        payload["docker_version"] = docker_version
    host_override = _load_host_environment_override()
    if host_override:
        payload.update(host_override)
        payload["environment_class"] = environment_class
    payload["hardware_id"] = "hw_%s" % stable_hash(payload)
    return payload
