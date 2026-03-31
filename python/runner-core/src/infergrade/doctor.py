import os
import platform
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

from infergrade.artifacts import artifact_to_download_url, default_artifact_cache_dir
from infergrade.capabilities import capability_images_for_request
from infergrade.environment import capture_environment
from infergrade.images import local_build_command
from infergrade.models import RunRequest


DEFAULT_BACKEND_IMAGES = {
    "llama.cpp": "infergrade-llama-cpp:local",
    "vllm": "infergrade-vllm:local",
}


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
    cli_path = shutil.which(os.environ.get("INFERGRADE_LLAMA_CPP_CLI", "llama-cli"))
    server_path = shutil.which(os.environ.get("INFERGRADE_LLAMA_CPP_SERVER", "llama-server"))
    checks.append(
        _check(
            "llama_cli_native",
            "ok" if cli_path else "error",
            "Native llama-cli is available." if cli_path else "Native llama-cli is required for local_native llama.cpp runs.",
            {
                "path": cli_path,
                "suggested_install": "brew install llama.cpp" if platform.system().lower() == "darwin" else None,
            },
        )
    )
    checks.append(
        _check(
            "llama_server_native",
            "ok" if server_path else "error",
            "Native llama-server is available." if server_path else "Native llama-server is required for local_native llama.cpp runs.",
            {
                "path": server_path,
                "suggested_install": "brew install llama.cpp" if platform.system().lower() == "darwin" else None,
            },
        )
    )
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


def _cache_dir_check(request: RunRequest) -> Dict[str, Any]:
    path = os.path.expanduser(request.quant_artifact_cache_dir or default_artifact_cache_dir())
    return _writable_directory_check("artifact_cache_dir", path, "Artifact cache directory is writable.")


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
    return _writable_directory_check("output_dir", parent, "Output directory parent is writable.", {"output_dir": output_dir})


def _writable_directory_check(check_id: str, path: str, success_message: str, extra_details: Dict[str, Any] = None) -> Dict[str, Any]:
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
    details["free_gb"] = round(free_bytes / float(1024 ** 3), 2)
    return _check(check_id, "ok", success_message, details)


def _uses_remote_artifact(request: RunRequest) -> bool:
    artifact = request.quant_artifact or ""
    return artifact.startswith("hf://") or artifact.startswith("http://") or artifact.startswith("https://")


def _check(check_id: str, status: str, message: str, details: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": check_id,
        "status": status,
        "ok": status not in ("error",),
        "message": message,
        "details": details,
    }
