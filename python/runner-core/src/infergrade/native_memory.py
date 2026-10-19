"""Bounded native llama.cpp memory recovery; requested settings stay immutable."""

import json
import os
import re

from infergrade.utils import write_json

POLICY_ID = "native_llama_memory_recovery_v1"
# A generic compute error, timeout, or process exit is NOT proof of an OOM.
_OOM = re.compile(
    r"kIOGPUCommandBufferCallbackErrorOutOfMemory|"
    r"(?:CUDA|HIP|Vulkan|Metal)[^\n]{0,160}(?:out of memory|insufficient memory)|"
    r"error:\s*Insufficient Memory|cudaMalloc[^\n]{0,120}(?:failed|out of memory)|"
    r"(?:failed to allocate|cannot allocate|not enough memory)[^\n]{0,160}(?:buffer|memory|bytes)|"
    r"(?:std::bad_alloc|VK_ERROR_OUT_OF_DEVICE_MEMORY|VK_ERROR_OUT_OF_HOST_MEMORY)", re.IGNORECASE,
)
_PLACEMENT_OPTIONS = frozenset((
    "--n-gpu-layers", "--gpu-layers", "-ngl", "--device", "-dev",
    "--split-mode", "-sm", "--tensor-split", "-ts", "--main-gpu", "-mg",
    "--cpu-moe", "-cmoe", "--n-cpu-moe", "-ncmoe", "--override-tensor", "-ot",
    "--fit-target", "-fitt", "--fit-ctx", "-fitc", "--mmap", "--mlock",
))


class NativeMemoryExhausted(RuntimeError):
    """Terminal infrastructure failure, never a model's capability score."""


def is_memory_failure(logs):
    return bool(_OOM.search(str(logs or "")))


def _option(flags, name):
    value = None
    for i, flag in enumerate(flags):
        if flag == name and i + 1 < len(flags):
            value = str(flags[i + 1])
        elif flag.startswith(name + "="):
            value = flag.split("=", 1)[1]
    return value


def _replace(flags, name, value=None):
    result, skip = [], False
    for flag in flags:
        if skip:
            skip = False
            continue
        if flag == name:
            skip = value is not None
            continue
        if flag.startswith(name + "="):
            continue
        result.append(flag)
    result.append(name)
    if value is not None:
        result.append(str(value))
    return result


def recovery_flags(request, flags, step, supported):
    """Let upstream fit weights; never reduce context, alter devices, or undo overrides."""
    if request.simulate or request.execution_mode != "local_native":
        return None
    explicit = list(request.backend_flags or [])
    if any(flag.split("=", 1)[0] in _PLACEMENT_OPTIONS for flag in explicit):
        return None
    if _option(flags, "--fit") != "on" or _option(explicit, "--fit") == "off":
        return None
    api = ((request.runtime_selector or {}).get("accelerator") or {}).get("api")
    if api == "cpu":
        return None
    # Three total configurations at most: default, no mmap, increased fit margin.
    if step == 0 and "--no-mmap" not in flags and "--no-mmap" in supported:
        return list(flags) + ["--no-mmap"]
    if step <= 1 and "--fit-target" in supported and _option(flags, "--fit-target") != "4096":
        result = list(flags)
        if "--no-mmap" not in result:
            if "--no-mmap" not in supported:
                return None
            result.append("--no-mmap")
        return _replace(result, "--fit-target", "4096")
    return None


def effective_configuration(request):
    """Only effective memory controls affect identity, never invocation history."""
    if not getattr(request, "_native_memory_step", 0):
        return None
    flags = getattr(request, "_native_memory_flags", [])
    controls = []
    for name in ("--fit", "--fit-target"):
        value = _option(flags, name)
        if value is not None:
            controls.extend([name, value])
    if "--no-mmap" in flags:
        controls.append("--no-mmap")
    return {"policy_id": POLICY_ID, "fallback_applied": True, "effective_memory_flags": controls}


def policy_summary(request):
    """Path-free effective settings; stable across equivalent repeated runs."""
    entries = getattr(request, "_native_memory_observations", [])
    if not entries:
        return None
    unique = {json.dumps(entry, sort_keys=True): entry for entry in entries}
    return {"policy_id": POLICY_ID, "configurations": [unique[key] for key in sorted(unique)][:32]}


def record_attempt(request, command, placement, role, step, status, oom=False):
    """Separate local recovery receipt; no raw logs, model paths, or prompts."""
    flags = []
    for name in ("--fit", "--fit-target"):
        value = _option(command, name)
        if value is not None:
            flags.extend([name, value])
    if "--no-mmap" in command:
        flags.append("--no-mmap")
    entry = {
        "role": role, "context_tokens": placement.get("requested_context_tokens"),
        "effective_memory_flags": flags, "recovery_step": step,
        "status": status, "confirmed_oom": bool(oom),
        "placement_fingerprint": placement.get("placement_fingerprint"),
    }
    if status == "ready":
        observations = getattr(request, "_native_memory_observations", [])
        if entry not in observations and len(observations) < 32:
            observations.append(entry)
        request._native_memory_observations = observations
    receipt = {"policy_id": POLICY_ID, **entry, "placement_invocation_id": placement.get("invocation_id")}
    if request.output_dir:
        path = os.path.join(request.output_dir, "artifacts", "runtime-memory", placement["invocation_id"] + ".json")
        write_json(path, receipt)
    return receipt


def memory_label(summary):
    if (summary or {}).get("fallback_applied"):
        return "Memory fallback"
    entries = (summary or {}).get("configurations") or []
    return "Memory fallback" if any(item.get("recovery_step", 0) > 0 for item in entries) else None
