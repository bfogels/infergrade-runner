"""Immutable physical CUDA selections with per-child visibility, never global env writes."""

import copy
import csv
import io
import math
import os
import re
import subprocess
from dataclasses import dataclass

from infergrade.utils import stable_hash
from infergrade.environment import _hardware_label

UUID_PATTERN = r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
PLACEMENT_OPTIONS = ("--device", "-dev", "--split-mode", "-sm", "--tensor-split", "-ts", "--main-gpu", "-mg")
QUERY = ["nvidia-smi", "--query-gpu=uuid,index,pci.bus_id,name,memory.total", "--format=csv,noheader,nounits"]


@dataclass(frozen=True)
class Device:
    uuid: str
    index: int
    pci_bus: str
    model: str
    memory_mib: int


@dataclass(frozen=True)
class Selection:
    uuids: tuple
    devices: tuple
    fingerprint: str


def requested_uuids(request):
    values = getattr(request, "cuda_device_uuids", [])
    if not isinstance(values, list):
        raise ValueError("Physical CUDA selection must be a device UUID list.")
    if not values:
        return ()
    if (not 1 <= len(values) <= 16
            or not all(isinstance(value, str) and re.fullmatch(UUID_PATTERN, value) for value in values)):
        raise ValueError("Select one to sixteen distinct physical CUDA GPU UUIDs.")
    normalized = tuple("GPU-" + value[4:].lower() for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError("Physical CUDA device selections must be distinct.")
    if request.backend != "llama.cpp" or request.execution_mode != "local_native":
        raise ValueError("Physical CUDA device selection requires native llama.cpp.")
    api = ((request.runtime_selector or {}).get("accelerator") or {}).get("api")
    if api not in (None, "unknown", "cuda"):
        raise ValueError("Physical CUDA devices conflict with the selected accelerator API.")
    return normalized


def inventory():
    try:
        completed = subprocess.run(QUERY, check=True, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise RuntimeError("Could not inspect physical NVIDIA devices. No device fallback is allowed.") from exc
    text = completed.stdout
    if not isinstance(text, str) or len(text) > 65536:
        raise RuntimeError("NVIDIA device inventory exceeded its bound.")
    try:
        rows = list(csv.reader(io.StringIO(text), strict=True))
    except csv.Error as exc:
        raise RuntimeError("NVIDIA device inventory returned invalid model metadata.") from exc
    if not 1 <= len(rows) <= 16:
        raise RuntimeError("NVIDIA device inventory is unavailable or exceeds sixteen devices.")
    devices = []
    try:
        for row in rows:
            if len(row) != 5:
                raise ValueError()
            uuid, index, pci, model, memory = [value.strip() for value in row]
            if (not re.fullmatch(UUID_PATTERN, uuid) or not re.fullmatch(r"[0-9]{1,3}", index)
                    or not re.fullmatch(r"[0-9a-fA-F]{4,8}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]", pci)
                    or _hardware_label(model) is None or model.casefold() in {"[n/a]", "n/a"}):
                raise ValueError()
            amount = float(memory)
            if not math.isfinite(amount) or not amount.is_integer() or not 0 < amount <= 4194304:
                raise ValueError()
            devices.append(Device("GPU-" + uuid[4:].lower(), int(index), pci.lower(), model, int(amount)))
        if len({device.uuid for device in devices}) != len(devices) or len({device.index for device in devices}) != len(devices) or len({device.pci_bus for device in devices}) != len(devices):
            raise ValueError()
    except (ValueError, OverflowError) as exc:
        raise RuntimeError("NVIDIA device inventory returned invalid model metadata.") from exc
    return tuple(sorted(devices, key=lambda device: device.index))


def _reject_placement_overrides(flags):
    if not isinstance(flags, list) or not all(isinstance(flag, str) for flag in flags):
        raise ValueError("Backend flags must be a list of arguments.")
    if any(flag == name or flag.startswith(name + "=") for flag in flags for name in PLACEMENT_OPTIONS):
        raise ValueError("Physical CUDA selection owns device/split flags; remove conflicting backend placement overrides.")


def prepare(request, *, device_inventory=None):
    values = requested_uuids(request)
    previous = getattr(request, "_native_cuda_selection", None)
    if not values and previous is None:
        return None
    if request.simulate:
        raise ValueError("Physical CUDA selection requires real execution; simulation cannot verify devices.")
    if previous is not None:
        if previous.uuids != values:
            raise RuntimeError("Physical CUDA selection changed after it was frozen.")
        return previous
    _reject_placement_overrides(getattr(request, "backend_flags", []))
    devices = {device.uuid: device for device in (inventory() if device_inventory is None else device_inventory)}
    if any(value not in devices for value in values):
        raise RuntimeError("A selected physical CUDA GPU is unavailable. No device fallback is allowed.")
    selection = Selection(values, tuple(devices[value] for value in values),
                          stable_hash({"policy": "native_cuda_uuid_mask_v1", "uuids": list(values)}, length=64))
    request._native_cuda_selection = selection
    return selection


def frozen(request):
    values = requested_uuids(request)
    selection = getattr(request, "_native_cuda_selection", None)
    if not values and selection is None:
        return None
    if selection is None or selection.uuids != values:
        raise RuntimeError("Physical CUDA selection is not frozen for this execution.")
    return selection


def namespace_devices(request):
    selection = frozen(request)
    return tuple("CUDA%d" % index for index in range(len(selection.devices))) if selection else None


def environment_kwargs(request):
    selection = frozen(request)
    if not selection:
        return {}
    environment = dict(os.environ)
    environment.update(CUDA_VISIBLE_DEVICES=",".join(selection.uuids), CUDA_DEVICE_ORDER="PCI_BUS_ID")
    return {"env": environment}


def placement_flags(request, flags):
    selection = frozen(request)
    if not selection:
        return flags
    _reject_placement_overrides(flags)
    devices = namespace_devices(request)
    result = [*flags, "--device", ",".join(devices), "--split-mode", "layer" if len(devices) > 1 else "none"]
    if len(devices) > 1:
        result += ["--main-gpu", "0", "--tensor-split", ",".join(str(device.memory_mib) for device in selection.devices)]
    return result


def selected_environment(request, environment):
    selection = frozen(request)
    if not selection:
        return environment
    result = copy.deepcopy(environment)
    hardware = result
    capacities = [device.memory_mib / 1024.0 for device in selection.devices]
    hardware.update(accelerator_type="gpu", accelerator_vendor="nvidia", accelerator_api="cuda",
                    hardware_class="nvidia_gpu", memory_architecture="discrete_vram",
                    accelerator_model=selection.devices[0].model, accelerator_count=len(selection.devices),
                    accelerator_vram_gb=round(max(capacities), 2), accelerator_vram_total_gb=round(sum(capacities), 2),
                    accelerator_devices=[{"model": device.model, "vram_gb": round(device.memory_mib / 1024.0, 2)}
                                         for device in selection.devices])
    identity = {key: value for key, value in result.items()
                if key not in {"hardware_id", "process_architecture", "process_translation"}}
    result["hardware_id"] = "hw_%s" % stable_hash(identity)
    return result


def logical_layout(request):
    """Shareable execution layout; physical UUIDs remain in the private request."""
    selection = frozen(request)
    if not selection:
        return None
    return {"policy": "native_cuda_uuid_mask_v1", "device_count": len(selection.devices),
            "split_mode": "layer" if len(selection.devices) > 1 else "none",
            "tensor_split_weights_mib": ([device.memory_mib for device in selection.devices]
                                         if len(selection.devices) > 1 else [])}


def sample_selected_memory_used_mb(request):
    """Selected-device aggregate, still an estimate that includes other processes."""
    selection = frozen(request)
    if not selection:
        return None
    command = ["nvidia-smi", "--query-gpu=uuid,memory.used", "--format=csv,noheader,nounits"]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True, timeout=5)
        text = completed.stdout
        if not isinstance(text, str) or len(text) > 65536:
            return None
        rows = list(csv.reader(io.StringIO(text), strict=True))
        if not 1 <= len(rows) <= 16:
            return None
        readings = {}
        for row in rows:
            if len(row) != 2:
                return None
            uuid, amount = [value.strip() for value in row]
            if not re.fullmatch(UUID_PATTERN, uuid):
                return None
            uuid = "GPU-" + uuid[4:].lower()
            if uuid in readings:
                return None
            # Other cards can be busy or unavailable without becoming this run's memory.
            readings[uuid] = amount
        selected = [float(readings[uuid]) for uuid in selection.uuids]
        if not all(math.isfinite(value) and 0 <= value <= device.memory_mib
                   for value, device in zip(selected, selection.devices)):
            return None
        return round(sum(selected), 2)
    except (OSError, subprocess.SubprocessError, UnicodeError, csv.Error, ValueError, KeyError, OverflowError):
        return None
