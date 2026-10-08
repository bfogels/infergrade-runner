"""Durable machine-local CUDA choice, with immutable job consent binding."""
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from infergrade.environment import _hardware_label
from infergrade.native_cuda_devices import UUID_PATTERN, inventory, prepare
from infergrade.pairing import runner_config_dir
from infergrade.process_locks import file_lock
from infergrade.utils import stable_hash

SCHEMA = "infergrade.cuda_device_policy.v1"


def _validate(value):
    if (not isinstance(value, dict) or set(value) != {"schema_version", "devices"}
            or value["schema_version"] != SCHEMA or not isinstance(value["devices"], list)
            or len(value["devices"]) > 16):
        raise ValueError("Invalid GPU preference. Reset or select the devices again.")
    seen = set()
    for device in value["devices"]:
        if (not isinstance(device, dict) or set(device) != {"uuid", "model", "memory_mib"}
                or not isinstance(device["uuid"], str) or not re.fullmatch(UUID_PATTERN, device["uuid"])
                or device["uuid"] != "GPU-" + device["uuid"][4:].lower()
                or device["uuid"] in seen or not isinstance(device["model"], str)
                or _hardware_label(device["model"]) != device["model"]
                or type(device["memory_mib"]) is not int or not 0 < device["memory_mib"] <= 4194304):
            raise ValueError("Invalid GPU preference. Reset or select the devices again.")
        seen.add(device["uuid"])
    return value


def _check_directory(directory):
    if directory.is_symlink():
        raise RuntimeError("GPU preferences refuse linked configuration directories.")
    if directory.exists():
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise RuntimeError("GPU preferences require a configuration directory.")
        if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o022):
            raise RuntimeError("GPU preference directory must belong to you and refuse writes from other users.")


def load_policy():
    directory = Path(runner_config_dir())
    _check_directory(directory)
    path = directory / "cuda-device-policy.json"
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if path.is_symlink() or not stat.S_ISREG(info.st_mode):
            raise ValueError("GPU preferences require a regular file.")
        if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise ValueError("GPU preferences must be readable only by their owner.")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(16385)
        if len(data) > 16384:
            raise ValueError("GPU preference exceeded its size bound.")
        value = _validate(json.loads(data))
        return value if value["devices"] else None
    finally:
        os.close(fd)


def descriptor(policy):
    if policy is None:
        return None
    _validate(policy)
    if not policy["devices"]:
        return None
    return {
        "schema_version": SCHEMA,
        "revision": stable_hash(policy, length=64),
        "selection_fingerprint": stable_hash({"policy": "native_cuda_uuid_mask_v1",
                                              "uuids": [d["uuid"] for d in policy["devices"]]}, length=64),
        "device_count": len(policy["devices"]),
        "devices": [{"model": d["model"], "vram_gb": round(d["memory_mib"] / 1024.0, 2)}
                    for d in policy["devices"]],
    }


def set_policy(uuids):
    if not isinstance(uuids, list) or len(uuids) > 16:
        raise ValueError("Select up to sixteen distinct full GPU UUIDs.")
    normalized = []
    for value in uuids:
        if not isinstance(value, str) or not re.fullmatch(UUID_PATTERN, value):
            raise ValueError("Select full GPU UUIDs from this machine's inventory.")
        normalized.append("GPU-" + value[4:].lower())
    if len(set(normalized)) != len(normalized):
        raise ValueError("Selected GPUs must be distinct.")
    available = {device.uuid: device for device in inventory()} if normalized else {}
    if any(value not in available for value in normalized):
        raise ValueError("A selected GPU is unavailable. No device fallback is allowed.")
    policy = _validate({"schema_version": SCHEMA, "devices": [
        {"uuid": value, "model": available[value].model, "memory_mib": available[value].memory_mib}
        for value in normalized]})
    directory = Path(runner_config_dir())
    _check_directory(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    _check_directory(directory)
    with file_lock(directory / "cuda-device-policy.lock"):
        path = directory / "cuda-device-policy.json"
        if path.is_symlink() or (path.exists() and not stat.S_ISREG(path.lstat().st_mode)):
            raise RuntimeError("GPU preferences refuse linked or special state files.")
        if path.exists() and os.name != "nt" and path.lstat().st_uid != os.getuid():
            raise RuntimeError("GPU preferences refuse state owned by another user.")
        fd, temporary = tempfile.mkstemp(prefix=".cuda-policy-", dir=str(directory))
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(policy, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            if os.name != "nt":
                directory_fd = os.open(str(directory), os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return descriptor(policy) if normalized else None


def apply_policy(request, expected_revision=None, hub_job=False):
    api = ((request.runtime_selector or {}).get("accelerator") or {}).get("api")
    if (request.backend != "llama.cpp" or request.execution_mode != "local_native"
            or api not in (None, "unknown", "cuda")):
        if expected_revision is not None:
            raise RuntimeError("GPU consent requires native CUDA llama.cpp execution.")
        return None
    policy = load_policy()
    current = descriptor(policy)
    revision = current["revision"] if current else None
    if hub_job and expected_revision != revision:
        raise RuntimeError("GPU choice changed or this job has no matching GPU consent. Review the machine and queue it again.")
    if policy is None:
        return None
    values = [d["uuid"] for d in policy["devices"]]
    if request.cuda_device_uuids and request.cuda_device_uuids != values:
        raise ValueError("The job's GPU devices conflict with this machine's selected devices.")
    request.cuda_device_uuids = list(values)
    selection = prepare(request)
    observed = [{"uuid": d.uuid, "model": d.model, "memory_mib": d.memory_mib} for d in selection.devices]
    if observed != policy["devices"]:
        raise RuntimeError("Selected GPU hardware changed. Select its devices again before benchmarking.")
    return current


def policy_heartbeat_metadata(metadata=None):
    result = dict(metadata or {})
    try:
        result["native_device_policy"] = descriptor(load_policy())
        result.pop("native_device_policy_warning", None)
    except (OSError, ValueError, RuntimeError, RecursionError):
        result["native_device_policy"] = None
        result["native_device_policy_warning"] = "GPU preference is unavailable; new work requires repair."
    return result


def policy_status():
    policy = load_policy()
    try:
        devices = inventory()
    except RuntimeError:
        return {"schema_version": SCHEMA, "policy": descriptor(policy), "available": False, "devices": [],
                "message": "Physical NVIDIA device inventory is unavailable."}
    return {"schema_version": SCHEMA, "policy": descriptor(policy), "available": True,
            "devices": [{"uuid": d.uuid, "index": d.index, "model": d.model,
                         "vram_gb": round(d.memory_mib / 1024.0, 2),
                         "selected": bool(policy and d.uuid in {v["uuid"] for v in policy["devices"]})}
                        for d in devices]}
