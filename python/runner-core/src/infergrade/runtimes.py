"""Managed runtime metadata and selection helpers."""

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


RUNTIME_MANIFEST_VERSION = "2026-04-22"
LLAMA_CPP_RUNTIME_ID = "llama-cpp-homebrew-stable-2026-04"
_CACHE_ENV = "INFERGRADE_RUNTIME_CACHE_DIR"


def runtime_cache_root() -> Path:
    return Path(os.environ.get(_CACHE_ENV) or Path.home() / ".cache" / "infergrade" / "runtimes").expanduser()


def llama_cpp_runtime_dir() -> Path:
    return runtime_cache_root() / "llama.cpp"


def selected_llama_cpp_runtime_path() -> Path:
    return llama_cpp_runtime_dir() / "selected_runtime.json"


def known_llama_cpp_runtimes() -> List[Dict[str, Any]]:
    return [
        {
            "runtime_id": LLAMA_CPP_RUNTIME_ID,
            "backend": "llama.cpp",
            "version_label": "homebrew stable",
            "source": "homebrew",
            "provenance": "Homebrew formula `llama.cpp`; inspect with `brew info llama.cpp` before executing.",
            "platforms": [{"system": "Darwin", "machine": "arm64"}],
            "install_command": ["brew", "install", "llama.cpp"],
            "binary_names": {
                "cli": "llama-cli",
                "server": "llama-server",
                "perplexity": "llama-perplexity",
            },
            "checksum": None,
            "notes": [
                "Recommended managed path for Apple Silicon native benchmarking.",
                "No command is run unless the operator passes --execute.",
            ],
        },
        {
            "runtime_id": "llama-cpp-windows-cuda-cli-preview-2026-05",
            "backend": "llama.cpp",
            "version_label": "Windows CUDA CLI preview",
            "source": "user_selected",
            "provenance": "Windows/NVIDIA CUDA remains CLI-only until a pinned, checksummed upstream llama.cpp CUDA artifact is selected and validated.",
            "platforms": [{"system": "Windows", "machine": "AMD64"}, {"system": "Windows", "machine": "x86_64"}],
            "install_command": [],
            "binary_names": {
                "cli": "llama-cli.exe",
                "server": "llama-server.exe",
                "perplexity": "llama-perplexity.exe",
            },
            "binary_set": "llama_cpp_windows_cuda_x86_64",
            "checksum": None,
            "support_tier": "preview",
            "notes": [
                "Technical-beta prep only; not a supported public path.",
                "No CUDA binary is downloaded by InferGrade until a pinned checksum exists.",
                "Users must explicitly select an existing CUDA-capable llama.cpp binary for preflight.",
                "CUDA requests must not silently fall back to CPU evidence.",
            ],
        },
    ]


def runtime_manifest() -> Dict[str, Any]:
    return {
        "manifest_version": RUNTIME_MANIFEST_VERSION,
        "runtime_family": "llama.cpp",
        "runtimes": known_llama_cpp_runtimes(),
    }


def find_known_runtime(runtime_id: Optional[str] = None) -> Dict[str, Any]:
    wanted = runtime_id or LLAMA_CPP_RUNTIME_ID
    for item in known_llama_cpp_runtimes():
        if item["runtime_id"] == wanted:
            return item
    raise ValueError("Unknown managed llama.cpp runtime id: %s" % wanted)


def platform_supported(runtime: Dict[str, Any]) -> bool:
    system = platform.system()
    machine = platform.machine()
    return any(item.get("system") == system and item.get("machine") in (machine, "*") for item in runtime.get("platforms") or [])


def selected_llama_cpp_runtime() -> Optional[Dict[str, Any]]:
    path = selected_llama_cpp_runtime_path()
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def managed_llama_cpp_binary_path(kind: str) -> Optional[str]:
    selection = selected_llama_cpp_runtime() or {}
    binaries = selection.get("binaries") or {}
    path = binaries.get(kind)
    return path if path and shutil.which(path) else None


def select_llama_cpp_runtime(
    runtime_id: Optional[str] = None,
    cli_path: Optional[str] = None,
    server_path: Optional[str] = None,
    perplexity_path: Optional[str] = None,
) -> Dict[str, Any]:
    runtime = find_known_runtime(runtime_id)
    names = runtime.get("binary_names") or {}
    resolved = {
        "cli": shutil.which(cli_path or names.get("cli") or "llama-cli"),
        "server": shutil.which(server_path or names.get("server") or "llama-server"),
        "perplexity": shutil.which(perplexity_path or names.get("perplexity") or "llama-perplexity"),
    }
    missing = [name for name in ("cli", "server") if not resolved.get(name)]
    if missing:
        raise RuntimeError(
            "Cannot select managed llama.cpp runtime %s; missing required binary kind(s): %s"
            % (runtime["runtime_id"], ", ".join(missing))
        )
    payload = {
        "runtime_id": runtime["runtime_id"],
        "backend": "llama.cpp",
        "version_label": runtime.get("version_label"),
        "source": runtime.get("source"),
        "provenance": runtime.get("provenance"),
        "manifest_version": RUNTIME_MANIFEST_VERSION,
        "binaries": resolved,
        "selected_at_platform": {"system": platform.system(), "machine": platform.machine()},
    }
    llama_cpp_runtime_dir().mkdir(parents=True, exist_ok=True)
    with open(selected_llama_cpp_runtime_path(), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return payload


def install_llama_cpp_runtime(runtime_id: Optional[str] = None, execute: bool = False) -> Dict[str, Any]:
    runtime = find_known_runtime(runtime_id)
    payload = {
        "runtime": runtime,
        "cache_dir": str(llama_cpp_runtime_dir()),
        "supported_on_this_platform": platform_supported(runtime),
        "execute": execute,
        "selected": None,
        "action": "plan",
    }
    if not execute:
        payload["message"] = "No install command was run. Re-run with --execute after inspecting the plan."
        return payload
    if not payload["supported_on_this_platform"]:
        raise RuntimeError("Managed runtime %s is not supported on this platform." % runtime["runtime_id"])
    command = list(runtime.get("install_command") or [])
    if not command:
        raise RuntimeError("Managed runtime %s does not define an install command." % runtime["runtime_id"])
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "Managed runtime install failed.").strip())
    payload["action"] = "installed"
    payload["install_stdout"] = completed.stdout
    payload["install_stderr"] = completed.stderr
    payload["selected"] = select_llama_cpp_runtime(runtime["runtime_id"])
    return payload
