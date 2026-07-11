import os
import platform
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

from infergrade import __version__
from infergrade.adapters.llama_cpp import LlamaCppAdapter
from infergrade.artifacts import (
    artifact_cache_status,
    artifact_to_download_url,
    default_artifact_cache_dir,
    min_artifact_cache_free_bytes,
)
from infergrade.capabilities import capability_images_for_request
from infergrade.contracts import load_contract_manifest
from infergrade.cuda import windows_cuda_preflight
from infergrade.environment import capture_environment
from infergrade.images import docker_image_exists, local_build_command
from infergrade.models import RunRequest
from infergrade.runtimes import managed_llama_cpp_binary_path, selected_llama_cpp_runtime


DEFAULT_BACKEND_IMAGES = {
    "llama.cpp": "ghcr.io/bfogels/infergrade-llama-cpp:%s" % __version__,
    "vllm": "ghcr.io/bfogels/infergrade-vllm:%s" % __version__,
}
DEFAULT_LOCAL_CAPABILITY_IMAGES = (
    {"benchmark_id": "ifeval", "display_name": "IFEval", "image": "ghcr.io/bfogels/infergrade-ifeval:%s" % __version__},
    {"benchmark_id": "evalplus", "display_name": "EvalPlus", "image": "ghcr.io/bfogels/infergrade-evalplus:%s" % __version__},
    {"benchmark_id": "mmlu_pro_reference_v1", "display_name": "MMLU-Pro reference", "image": "ghcr.io/bfogels/infergrade-mmlu-pro:%s" % __version__},
)
DEFAULT_MIN_OUTPUT_FREE_GB = 1.0


def run_doctor(request: Optional[RunRequest] = None, api_url: Optional[str] = None) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    checks.append(_python_version_check())
    if api_url:
        checks.append(_api_health_check(api_url))
    if request is None:
        checks.extend(_generic_environment_checks())
    else:
        checks.extend(_request_checks(request))

    error_count = len([item for item in checks if item["status"] == "error"])
    warning_count = len([item for item in checks if item["status"] == "warning"])
    return {
        "ok": error_count == 0,
        "error_count": error_count,
        "warning_count": warning_count,
        "request_context": _request_context(request, api_url),
        "checks": checks,
    }


def collect_runner_diagnostics(execution_modes: List[str]) -> Dict[str, Any]:
    """Collect runner-level readiness diagnostics for long-lived paired workers."""
    modes = [str(mode).strip() for mode in (execution_modes or []) if str(mode).strip()]
    environment_mode = "local_native" if "local_native" in modes else (modes[0] if modes else "local_container")
    environment = capture_environment(environment_mode)
    checks: List[Dict[str, Any]] = []

    try:
        contract = load_contract_manifest()
        checks.append(
            _check(
                "runner_contract",
                "ok",
                "Runner contract manifest is available.",
                {
                    "publisher": contract.get("publisher"),
                    "contract_version": contract.get("contract_version"),
                },
            )
        )
    except Exception as exc:
        contract = {"publisher": "infergrade-runner", "contract_version": None}
        checks.append(
            _check(
                "runner_contract",
                "error",
                "Runner contract manifest could not be loaded.",
                {"error": str(exc)},
            )
        )

    if any(mode in {"local_container", "cloud_container"} for mode in modes):
        docker_cli = _binary_check("docker", "docker_cli", "Docker CLI is available.")
        checks.append(docker_cli)
        if docker_cli["status"] == "ok":
            checks.append(_docker_daemon_check())
            checks.extend(_runner_image_checks())

    if "local_native" in modes:
        checks.extend(_native_runner_checks(environment))

    if "local_container" in modes and environment.get("hardware_class") == "apple_silicon":
        checks.append(
            _check(
                "apple_silicon_local_container_warning",
                "warning",
                "This machine is Apple Silicon. Prefer local_native for realistic Metal-backed llama.cpp benchmarking.",
                {
                    "hardware_class": environment.get("hardware_class"),
                    "suggested_execution_mode": "local_native",
                },
            )
        )

    blocking_checks = [item for item in checks if item.get("status") == "error"]
    warning_checks = [item for item in checks if item.get("status") == "warning"]
    summary_message = "Runner is ready for paired execution."
    summary_status = "ready"
    if blocking_checks:
        summary_status = "blocked"
        summary_message = blocking_checks[0]["message"]
    elif warning_checks:
        summary_status = "warning"
        summary_message = warning_checks[0]["message"]

    return {
        "execution_modes": modes,
        "environment": environment,
        "contract": {
            "publisher": contract.get("publisher"),
            "contract_version": contract.get("contract_version"),
        },
        "diagnostics": {
            "status": summary_status,
            "message": summary_message,
            "blocking_count": len(blocking_checks),
            "warning_count": len(warning_checks),
            "blocking_checks": blocking_checks,
            "warning_checks": warning_checks,
            "checks": checks,
            "preferred_local_execution_mode": _preferred_local_execution_mode(environment),
        },
    }


def _request_context(request: Optional[RunRequest], api_url: Optional[str]) -> Dict[str, Any]:
    if request is None:
        return {
            "api_url": api_url,
            "mode": "generic_environment",
        }
    return {
        "api_url": api_url,
        "mode": "run_request",
        "run_config_id": request.run_config_id,
        "model": request.model,
        "backend": request.backend,
        "tier": request.tier,
        "execution_mode": request.execution_mode,
        "backend_image": None
        if request.execution_mode == "local_native"
        else (request.backend_image or DEFAULT_BACKEND_IMAGES.get(request.backend)),
        "capability_images": capability_images_for_request(request),
        "quant_artifact": request.quant_artifact,
        "artifact_cache_dir": os.path.expanduser(request.quant_artifact_cache_dir or default_artifact_cache_dir()),
        "output_dir": os.path.abspath(request.output_dir or os.path.join("runs", request.run_config_id or "infergrade_run")),
    }


def _generic_environment_checks() -> List[Dict[str, Any]]:
    environment = capture_environment("local_container")
    return [
        _check(
            "hardware_snapshot",
            "info",
            "Captured local hardware snapshot.",
            environment,
        )
    ]


def _request_checks(request: RunRequest) -> List[Dict[str, Any]]:
    environment = capture_environment(request.execution_mode)
    checks = [
        _check("backend", "ok", "Backend is supported.", {"backend": request.backend}),
        _check(
            "hardware_snapshot",
            "info",
            "Captured local hardware snapshot.",
            environment,
        ),
    ]
    checks.extend(_execution_mode_guidance_checks(request, environment))
    checks.extend(_backend_compatibility_checks(request))
    if request.execution_mode in ("local_container", "cloud_container"):
        checks.append(_binary_check("docker", "docker_cli", "Docker CLI is available."))
        if checks[-1]["status"] == "ok":
            checks.append(_docker_daemon_check())
            checks.append(_backend_image_check(request))
            checks.extend(_capability_image_checks(request))
    if request.execution_mode == "local_native":
        checks.extend(_native_runtime_checks(request, environment))
    if _uses_remote_artifact(request):
        checks.append(_binary_check("curl", "curl", "curl is available for resilient artifact downloads.", severity_if_missing="warning"))
        checks.append(_cache_dir_check(request))
        checks.append(_artifact_reference_check(request))
    elif request.quant_artifact:
        checks.append(_local_artifact_check(request))
    else:
        checks.append(
            _check(
                "quant_artifact",
                "warning",
                "No quant artifact is specified; a real run will need one.",
                {},
            )
        )
    checks.append(_output_dir_check(request))
    return checks


def _execution_mode_guidance_checks(request: RunRequest, environment: Dict[str, Any]) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    if request.backend != "llama.cpp":
        return checks
    if (
        request.execution_mode == "local_container"
        and not request.simulate
        and environment.get("hardware_class") == "apple_silicon"
    ):
        checks.append(
            _check(
                "apple_silicon_local_container",
                "error",
                "Apple Silicon local_container runs benchmark llama.cpp inside Docker's Linux VM and do not exercise Metal acceleration. Use execution_mode=local_native for realistic local benchmarking.",
                {
                    "hardware_class": environment.get("hardware_class"),
                    "accelerator_api": environment.get("accelerator_api"),
                    "suggested_execution_mode": "local_native",
                },
            )
        )
    return checks


def _backend_compatibility_checks(request: RunRequest) -> List[Dict[str, Any]]:
    if request.backend != "llama.cpp":
        return []
    adapter = LlamaCppAdapter()
    try:
        adapter._ensure_backend_model_compatibility(request)
    except Exception as exc:
        return [
            _check(
                "llama_cpp_model_compatibility",
                "error",
                str(exc),
                {
                    "backend": request.backend,
                    "model": request.model,
                    "quant_artifact": request.quant_artifact,
                    "action": "Use a newer explicit llama.cpp runtime, choose a supported artifact, or switch backend lane.",
                },
            )
        ]
    return [
        _check(
            "llama_cpp_model_compatibility",
            "ok",
            "No known llama.cpp/model architecture incompatibility was detected before execution.",
            {
                "backend": request.backend,
                "model": request.model,
            },
        )
    ]


def _llama_native_binary_check(check_id: str, explicit_path: Optional[str], env_name: str, default_binary: str, label: str) -> Dict[str, Any]:
    managed_selection = selected_llama_cpp_runtime()
    binary_kind = "cli" if "cli" in check_id else "server"
    managed_path = managed_llama_cpp_binary_path(binary_kind) if not explicit_path and not os.environ.get(env_name) else None
    requested = explicit_path or os.environ.get(env_name) or managed_path or default_binary
    path = shutil.which(requested)
    install_hint = "brew install llama.cpp" if platform.system().lower() == "darwin" else None
    source = "custom_path" if explicit_path else ("environment_path" if os.environ.get(env_name) else ("managed_runtime" if managed_path else "system_path"))
    if not path:
        return _check(
            check_id,
            "error",
            "%s is required for local_native llama.cpp runs." % label,
            {
                "requested": requested,
                "path": None,
                "source": source,
                "managed_runtime": managed_selection,
                "env_var": env_name,
                "suggested_install": install_hint,
                "managed_install_suggestion": "Run `infergrade install-runtime --runtime llama.cpp` to inspect the pinned managed runtime plan.",
            },
        )
    version = _binary_version(path)
    return _check(
        check_id,
        "ok",
        "%s is available." % label,
        {
            "requested": requested,
            "path": path,
            "version": version,
            "version_status": "detected" if version else "unknown",
            "source": source,
            "managed_runtime": managed_selection,
            "env_var": env_name,
            "suggested_install": install_hint,
        },
    )


def _binary_version(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    try:
        completed = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    output = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode != 0 or not output:
        return None
    return output.splitlines()[0]


def _native_runtime_checks(request: RunRequest, environment: Dict[str, Any]) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    if request.backend != "llama.cpp":
        checks.append(
            _check(
                "native_backend_support",
                "warning",
                "local_native execution currently has first-class support only for llama.cpp.",
                {"backend": request.backend},
            )
        )
        return checks
    if _request_selects_cuda(request):
        checks.append(_windows_cuda_preflight_check(request))
    checks.append(_llama_native_binary_check("llama_cli_native", request.llama_cpp_cli_path, "INFERGRADE_LLAMA_CPP_CLI", "llama-cli", "Native llama-cli"))
    checks.append(_llama_native_binary_check("llama_server_native", request.llama_cpp_server_path, "INFERGRADE_LLAMA_CPP_SERVER", "llama-server", "Native llama-server"))
    if environment.get("hardware_class") == "apple_silicon":
        checks.append(
            _check(
                "apple_silicon_native_runtime",
                "ok",
                "Apple Silicon native execution path can use Metal acceleration when the installed llama.cpp binaries were built with Metal support.",
                {
                    "hardware_class": environment.get("hardware_class"),
                    "accelerator_api": environment.get("accelerator_api"),
                },
            )
        )
    return checks


def _request_selects_cuda(request: RunRequest) -> bool:
    selector = request.runtime_selector or {}
    accelerator = selector.get("accelerator") if isinstance(selector, dict) else {}
    delivery = selector.get("delivery") if isinstance(selector, dict) else {}
    return (
        isinstance(accelerator, dict)
        and accelerator.get("api") == "cuda"
        and (accelerator.get("vendor") in (None, "nvidia", "unknown"))
    ) or (
        isinstance(delivery, dict)
        and str(delivery.get("binary_set") or "").startswith("llama_cpp_windows_cuda")
    )


def _windows_cuda_preflight_check(request: RunRequest) -> Dict[str, Any]:
    selector = request.runtime_selector or {}
    driver = selector.get("driver") if isinstance(selector, dict) else {}
    cuda_major = str((driver or {}).get("cuda_major") or "12")
    result = windows_cuda_preflight(runtime_binary_path=request.llama_cpp_cli_path, cuda_major=cuda_major)
    preflight_selector = result["selector"]
    compatibility = preflight_selector["compatibility"]
    status = compatibility.get("status")
    doctor_status = "ok" if status == "ready" else ("warning" if status == "warning" else "error")
    return _check(
        "windows_cuda_preflight",
        doctor_status,
        "Windows/NVIDIA CUDA preflight is %s." % status,
        {
            "runtime_selector": preflight_selector,
            "gpu_count": result.get("gpu_count"),
            "hardware_blocked": result.get("hardware_blocked"),
            "next_action": result.get("next_action"),
            "proof_gate": result.get("proof_gate"),
        },
    )


def _native_runner_checks(environment: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return runner-level readiness checks for native local execution."""
    checks: List[Dict[str, Any]] = []
    checks.append(_llama_native_binary_check("llama_cli_native", None, "INFERGRADE_LLAMA_CPP_CLI", "llama-cli", "Native llama-cli"))
    checks.append(_llama_native_binary_check("llama_server_native", None, "INFERGRADE_LLAMA_CPP_SERVER", "llama-server", "Native llama-server"))
    if environment.get("hardware_class") == "apple_silicon":
        checks.append(
            _check(
                "apple_silicon_native_runtime",
                "ok",
                "Apple Silicon native execution can use Metal acceleration when the installed llama.cpp binaries include Metal support.",
                {
                    "hardware_class": environment.get("hardware_class"),
                    "accelerator_api": environment.get("accelerator_api"),
                },
            )
        )
    checks.extend(_runner_capability_image_checks())
    return checks


def _python_version_check() -> Dict[str, Any]:
    version = "%s.%s.%s" % sys.version_info[:3]
    if sys.version_info < (3, 8):
        return _check(
            "python_version",
            "error",
            "Python 3.8+ is required.",
            {"detected_version": version},
        )
    return _check(
        "python_version",
        "ok",
        "Python version is supported.",
        {"detected_version": version},
    )


def _api_health_check(api_url: str) -> Dict[str, Any]:
    url = api_url.rstrip("/") + "/healthz"
    try:
        with urllib_request.urlopen(url) as response:
            payload = response.read().decode("utf-8")
    except urllib_error.URLError as exc:
        return _check(
            "api_health",
            "error",
            "InferGrade API is not reachable.",
            {"api_url": api_url, "error": str(exc)},
        )
    return _check(
        "api_health",
        "ok",
        "InferGrade API is reachable.",
        {"api_url": api_url, "response": payload},
    )


def _binary_check(binary_name: str, check_id: str, success_message: str, severity_if_missing: str = "error") -> Dict[str, Any]:
    path = shutil.which(binary_name)
    if path is None:
        return _check(
            check_id,
            severity_if_missing,
            "%s is not installed or not on PATH." % binary_name,
            {},
        )
    return _check(check_id, "ok", success_message, {"path": path})


def _docker_daemon_check() -> Dict[str, Any]:
    completed = subprocess.run(["docker", "info"], capture_output=True, text=True)
    if completed.returncode != 0:
        return _check(
            "docker_daemon",
            "error",
            "Docker daemon is not reachable.",
            {"stderr": (completed.stderr or completed.stdout or "").strip()},
        )
    return _check(
        "docker_daemon",
        "ok",
        "Docker daemon is reachable.",
        {},
    )


def _backend_image_check(request: RunRequest) -> Dict[str, Any]:
    image = request.backend_image or DEFAULT_BACKEND_IMAGES.get(request.backend)
    if not image:
        return _check(
            "backend_image",
            "warning",
            "No backend image is configured.",
            {"backend": request.backend},
        )
    completed = subprocess.run(["docker", "image", "inspect", image], capture_output=True, text=True)
    if completed.returncode != 0:
        details = {"image": image, "stderr": (completed.stderr or "").strip()}
        build_command = local_build_command(image)
        if build_command:
            details["suggested_command"] = build_command
        return _check(
            "backend_image",
            "warning",
            "Backend image is not present locally yet.",
            details,
        )
    return _check(
        "backend_image",
        "ok",
        "Backend image is available locally.",
        {"image": image},
    )


def _capability_image_checks(request: RunRequest) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    for image_info in capability_images_for_request(request):
        image = image_info["image"]
        completed = subprocess.run(["docker", "image", "inspect", image], capture_output=True, text=True)
        if completed.returncode != 0:
            details = {
                "benchmark_id": image_info["benchmark_id"],
                "display_name": image_info["display_name"],
                "image": image,
                "stderr": (completed.stderr or "").strip(),
            }
            build_command = local_build_command(image)
            if build_command:
                details["suggested_command"] = build_command
            checks.append(
                _check(
                    "capability_image_%s" % image_info["benchmark_id"],
                    "warning",
                    "Capability benchmark image is not present locally yet.",
                    details,
                )
            )
            continue
        checks.append(
            _check(
                "capability_image_%s" % image_info["benchmark_id"],
                "ok",
                "Capability benchmark image is available locally.",
                {
                    "benchmark_id": image_info["benchmark_id"],
                    "display_name": image_info["display_name"],
                    "image": image,
                },
            )
        )
    return checks


def _runner_image_checks() -> List[Dict[str, Any]]:
    """Return readiness checks for the default local runtime images."""
    images = [{"benchmark_id": "llama_cpp", "display_name": "llama.cpp runtime", "image": DEFAULT_BACKEND_IMAGES["llama.cpp"]}]
    return [_local_image_check(item, warning=True) for item in images]


def _runner_capability_image_checks() -> List[Dict[str, Any]]:
    """Return readiness checks for local capability containers."""
    return [_local_image_check(item, warning=True) for item in DEFAULT_LOCAL_CAPABILITY_IMAGES]


def _local_image_check(image_info: Dict[str, Any], warning: bool = False) -> Dict[str, Any]:
    """Return a readiness check for one known local image."""
    image = image_info["image"]
    if docker_image_exists(image):
        return _check(
            "local_image_%s" % image_info["benchmark_id"],
            "ok",
            "%s image is available locally." % image_info["display_name"],
            {
                "benchmark_id": image_info["benchmark_id"],
                "display_name": image_info["display_name"],
                "image": image,
            },
        )
    details = {
        "benchmark_id": image_info["benchmark_id"],
        "display_name": image_info["display_name"],
        "image": image,
    }
    build_command = local_build_command(image)
    if build_command:
        details["suggested_command"] = build_command
    return _check(
        "local_image_%s" % image_info["benchmark_id"],
        "warning" if warning else "error",
        "%s image is not present locally yet." % image_info["display_name"],
        details,
    )


def _cache_dir_check(request: RunRequest) -> Dict[str, Any]:
    path = os.path.expanduser(request.quant_artifact_cache_dir or default_artifact_cache_dir())
    status = artifact_cache_status(path)
    return _writable_directory_check(
        "artifact_cache_dir",
        path,
        "Artifact cache directory is writable and has enough free space.",
        status,
        min_free_bytes=min_artifact_cache_free_bytes(),
    )


def _artifact_reference_check(request: RunRequest) -> Dict[str, Any]:
    try:
        download_url = artifact_to_download_url(request.quant_artifact, revision=request.quant_artifact_revision)
    except Exception as exc:
        return _check(
            "quant_artifact",
            "error",
            "Quant artifact reference is invalid.",
            {"artifact": request.quant_artifact, "error": str(exc)},
        )
    return _check(
        "quant_artifact",
        "ok",
        "Remote quant artifact reference looks valid.",
        {"artifact": request.quant_artifact, "download_url": download_url},
    )


def _local_artifact_check(request: RunRequest) -> Dict[str, Any]:
    artifact = os.path.expanduser(request.quant_artifact)
    if not os.path.isfile(artifact):
        return _check(
            "quant_artifact",
            "error",
            "Local quant artifact does not exist.",
            {"artifact": artifact},
        )
    if request.backend == "llama.cpp" and not artifact.lower().endswith(".gguf"):
        return _check(
            "quant_artifact",
            "error",
            "llama.cpp real runs require a GGUF artifact.",
            {"artifact": artifact},
        )
    return _check(
        "quant_artifact",
        "ok",
        "Local quant artifact exists.",
        {"artifact": artifact, "size_bytes": os.path.getsize(artifact)},
    )


def _output_dir_check(request: RunRequest) -> Dict[str, Any]:
    output_dir = os.path.abspath(request.output_dir or os.path.join("runs", request.run_config_id or "infergrade_run"))
    parent = os.path.dirname(output_dir) or "."
    return _writable_directory_check(
        "output_dir",
        parent,
        "Output directory parent is writable and has enough free space.",
        {"output_dir": output_dir},
        min_free_bytes=_min_output_free_bytes(),
    )


def _writable_directory_check(
    check_id: str,
    path: str,
    success_message: str,
    extra_details: Dict[str, Any] = None,
    min_free_bytes: int = 0,
) -> Dict[str, Any]:
    details = dict(extra_details or {})
    expanded = os.path.abspath(os.path.expanduser(path))
    details["path"] = expanded
    try:
        os.makedirs(expanded, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(dir=expanded, delete=True)
        handle.write(b"infergrade")
        handle.flush()
        handle.close()
    except Exception as exc:
        details["error"] = str(exc)
        return _check(check_id, "error", "Path is not writable.", details)
    free_bytes = shutil.disk_usage(expanded).free
    details["free_bytes"] = free_bytes
    details["free_gb"] = round(free_bytes / float(1024 ** 3), 2)
    details["min_required_free_bytes"] = min_free_bytes
    details["min_required_free_gb"] = round(min_free_bytes / float(1024 ** 3), 2)
    if min_free_bytes > 0 and free_bytes < min_free_bytes:
        return _check(
            check_id,
            "error",
            "Insufficient free disk space.",
            details,
        )
    return _check(check_id, "ok", success_message, details)


def _min_output_free_bytes() -> int:
    raw_value = os.environ.get("INFERGRADE_MIN_OUTPUT_FREE_GB")
    if raw_value is None or str(raw_value).strip() == "":
        gb_value = DEFAULT_MIN_OUTPUT_FREE_GB
    else:
        try:
            gb_value = float(str(raw_value).strip())
        except ValueError:
            gb_value = DEFAULT_MIN_OUTPUT_FREE_GB
    return max(0, int(gb_value * (1024 ** 3)))


def _uses_remote_artifact(request: RunRequest) -> bool:
    artifact = request.quant_artifact or ""
    return artifact.startswith("hf://") or artifact.startswith("http://") or artifact.startswith("https://")


def _preferred_local_execution_mode(environment: Dict[str, Any]) -> str:
    """Return the best default local execution mode for the detected hardware."""
    if (environment or {}).get("hardware_class") == "apple_silicon":
        return "local_native"
    return "local_container"


def _check(check_id: str, status: str, message: str, details: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": check_id,
        "status": status,
        "ok": status not in ("error",),
        "message": message,
        "details": details,
    }
