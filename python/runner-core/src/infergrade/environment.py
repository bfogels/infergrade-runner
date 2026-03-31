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
            "--query-gpu=name,memory.total",
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
    for line in lines:
        parts = [part.strip() for part in line.split(",", 1)]
        if len(parts) != 2:
            continue
        models.append(parts[0])
        try:
            vrams.append(float(parts[1]))
        except ValueError:
            continue
    if not models:
        return None
    return {
        "accelerator_type": "gpu",
        "accelerator_vendor": "nvidia",
        "accelerator_model": models[0],
        "accelerator_vram_gb": round(max(vrams) / 1024.0, 2) if vrams else None,
        "accelerator_count": len(models),
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
        "machine_model": hardware.get("machine_model"),
        "gpu_cores": gpu.get("sppci_cores"),
    }


def _default_accelerator_payload() -> Dict[str, Any]:
    """Return the fallback accelerator payload when no accelerator is detected."""
    return {
        "accelerator_type": "unknown",
        "accelerator_vendor": None,
        "accelerator_model": None,
        "accelerator_vram_gb": None,
        "accelerator_count": 0,
    }


def _detect_cpu_model() -> str:
    """Detect the most helpful CPU label for the current platform."""
    brand = _run_command(["sysctl", "-n", "machdep.cpu.brand_string"])
    if brand:
        return brand
    return platform.processor() or platform.machine()


def capture_environment(execution_mode: str) -> Dict[str, Any]:
    """Capture hardware and OS facts for a InferGrade run."""
    gpu = _detect_nvidia_gpu() or _detect_apple_silicon_gpu() or _default_accelerator_payload()
    environment_class = {
        "local_container": "local_workstation",
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
        "cpu_model": _detect_cpu_model(),
        "cpu_core_count": os.cpu_count(),
        "memory_gb": _detect_memory_gb(),
        "os": "%s-%s" % (platform.system().lower(), platform.release()),
        "kernel_version": platform.version(),
        "driver_versions": {},
        "container_runtime": "docker" if os.path.exists("/.dockerenv") else None,
    }
    if gpu.get("machine_model"):
        payload["machine_model"] = gpu["machine_model"]
    if gpu.get("gpu_cores"):
        payload["gpu_cores"] = gpu["gpu_cores"]
    payload["hardware_id"] = "hw_%s" % stable_hash(payload)
    return payload
