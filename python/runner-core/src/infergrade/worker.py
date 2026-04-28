"""Worker loop for claiming and executing InferGrade run jobs."""

import os
import socket
import time
from typing import Any, Callable, Dict, Optional, Tuple

from infergrade import __version__
from infergrade.doctor import collect_runner_diagnostics, run_doctor
from infergrade.progress import load_progress
from infergrade.run_configs import request_from_run_config_document
from infergrade.runner import run_infergrade
from infergrade.transport import (
    claim_run_job,
    complete_run_job,
    fail_run_job,
    fetch_run_config,
    heartbeat_runner,
    heartbeat_run_job,
    register_runner,
    upload_run_bundle,
)


def execute_run_job(
    api_url: str,
    run_job: Dict[str, Any],
    worker_id: str,
    api_token: str = None,
    run_token: str = None,
    simulate: bool = False,
    hostname: str = None,
    provider_id: str = None,
    instance_type_id: str = None,
    emit_progress: Optional[Callable[[str], None]] = None,
    runner_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute one claimed run job and report lifecycle state back to the API."""
    run_id = run_job["run_id"]

    def _runner_heartbeat(status: str, current_run_id: str = None, message: str = None) -> None:
        if not api_token:
            return
        heartbeat_runner(
            api_url,
            runner_id=worker_id,
            api_token=api_token,
            status=status,
            current_run_id=current_run_id,
            hostname=hostname or socket.gethostname(),
            provider_id=provider_id,
            instance_type_id=instance_type_id,
            metadata={"message": message} if message else None,
            environment=(runner_snapshot or {}).get("environment"),
            contract=(runner_snapshot or {}).get("contract"),
            diagnostics=(runner_snapshot or {}).get("diagnostics"),
        )

    doctor_report = None
    try:
        _runner_heartbeat("busy", current_run_id=run_id, message="Fetching run config.")
        heartbeat_run_job(api_url, run_id, worker_id, stage="fetch_run_config", message="Fetching run config.", api_token=api_token, run_token=run_token)
        payload = fetch_run_config(api_url, run_job["run_config_id"], api_token=api_token)
        request = request_from_run_config_document(payload, simulate=simulate)
        request.output_dir = run_job.get("output_dir")
        request.resume = True
        if run_job.get("execution_mode"):
            request.execution_mode = run_job["execution_mode"]
        if request.execution_mode == "local_container":
            host_artifact_cache_dir = os.environ.get("INFERGRADE_HOST_ARTIFACT_CACHE_DIR")
            if host_artifact_cache_dir:
                request.quant_artifact_cache_dir = host_artifact_cache_dir
        cloud = run_job.get("cloud") or {}
        if cloud.get("provider_id"):
            request.cloud_provider = cloud.get("provider_id")
        if cloud.get("instance_type_id"):
            request.cloud_instance_type = cloud.get("instance_type_id")
        heartbeat_run_job(
            api_url,
            run_id,
            worker_id,
            stage="preflight",
            message="Running local preflight checks.",
            progress_percent=5.0,
            api_token=api_token,
            run_token=run_token,
        )
        doctor_report = run_doctor(request=request, api_url=api_url)
        if not doctor_report.get("ok"):
            raise RuntimeError(_doctor_failure_message(doctor_report))

        def _emit(message: str) -> None:
            if emit_progress:
                emit_progress(message)
            _runner_heartbeat("busy", current_run_id=run_id, message=message)
            stage, detail, progress_percent = _runtime_progress_update(request.output_dir)
            heartbeat_run_job(
                api_url,
                run_id,
                worker_id,
                stage=stage,
                detail=detail,
                message=message,
                progress_percent=progress_percent,
                api_token=api_token,
                run_token=run_token,
            )

        result = run_infergrade(request, emit_progress=_emit)
        heartbeat_run_job(api_url, run_id, worker_id, stage="upload", message="Uploading completed bundle.", progress_percent=95.0, api_token=api_token, run_token=run_token)
        upload = upload_run_bundle(result["output_dir"], api_url, run_id=run_id, run_token=run_token, api_token=api_token)
        completed = complete_run_job(
            api_url,
            run_id,
            worker_id,
            bundle_id=result["bundle_id"],
            upload=upload,
            api_token=api_token,
            run_token=run_token,
        )
        _runner_heartbeat("listening", current_run_id=None, message="Runner is listening for the next run.")
        return {
            "claimed": True,
            "completed": True,
            "run": completed.get("run"),
            "bundle": result,
            "upload": upload,
        }
    except Exception as exc:
        failure = _classify_worker_failure(exc, doctor_report=doctor_report)
        try:
            fail_run_job(
                api_url,
                run_id,
                worker_id,
                message=failure["message"],
                error_code=failure["error_code"],
                recovery=failure.get("recovery"),
                details=failure.get("details"),
                api_token=api_token,
                run_token=run_token,
            )
        except Exception:
            pass
        try:
            _runner_heartbeat("listening", current_run_id=None, message="Runner recovered and is listening for more work.")
        except Exception:
            pass
        if emit_progress:
            emit_progress("Run %s failed: %s" % (run_id, exc))
        return {
            "claimed": True,
            "completed": False,
            "run_id": run_id,
            "error": failure["message"],
            "failure": failure,
        }


def run_worker_once(
    api_url: str,
    execution_mode: str,
    worker_id: str = None,
    run_id: str = None,
    run_config_id: str = None,
    provider_id: str = None,
    instance_type_id: str = None,
    hostname: str = None,
    api_token: str = None,
    run_token: str = None,
    simulate: bool = False,
    emit_progress: Optional[Callable[[str], None]] = None,
    runner_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Claim and execute at most one run job."""
    resolved_worker_id = worker_id or _default_worker_id()
    claimed = claim_run_job(
        api_url,
        worker_id=resolved_worker_id,
        execution_mode=execution_mode,
        run_id=run_id,
        run_config_id=run_config_id,
        provider_id=provider_id,
        instance_type_id=instance_type_id,
        hostname=hostname or socket.gethostname(),
        api_token=api_token,
        run_token=run_token,
    )
    if claimed.get("error"):
        raise RuntimeError(claimed["error"].get("message") or "Failed to claim run job.")
    run_job = claimed.get("run")
    if not run_job:
        if emit_progress:
            emit_progress("No matching run jobs are awaiting execution.")
        return {"claimed": False, "worker_id": resolved_worker_id}
    if emit_progress:
        emit_progress("Claimed run %s." % run_job["run_id"])
    result = execute_run_job(
        api_url=api_url,
        run_job=run_job,
        worker_id=resolved_worker_id,
        api_token=api_token,
        run_token=run_token,
        simulate=simulate,
        hostname=hostname,
        provider_id=provider_id,
        instance_type_id=instance_type_id,
        emit_progress=emit_progress,
        runner_snapshot=runner_snapshot,
    )
    result["worker_id"] = resolved_worker_id
    return result


def run_worker_loop(
    api_url: str,
    execution_mode: str,
    worker_id: str = None,
    run_id: str = None,
    run_config_id: str = None,
    provider_id: str = None,
    instance_type_id: str = None,
    hostname: str = None,
    api_token: str = None,
    run_token: str = None,
    simulate: bool = False,
    poll_interval_seconds: float = 10.0,
    max_jobs: Optional[int] = None,
    emit_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Continuously poll for run jobs and execute them."""
    resolved_worker_id = worker_id or _default_worker_id()
    runner_snapshot = collect_runner_diagnostics([execution_mode])
    register_runner(
        api_url=api_url,
        runner_id=resolved_worker_id,
        execution_modes=[execution_mode],
        api_token=api_token,
        status="starting",
        label=resolved_worker_id,
        runner_kind="cloud_worker" if execution_mode == "cloud_container" else "local_listener",
        hostname=hostname or socket.gethostname(),
        provider_id=provider_id,
        instance_type_id=instance_type_id,
        capabilities={"run_token_supported": True, "auto_upload": True},
        version=__version__,
        environment=runner_snapshot.get("environment"),
        contract=runner_snapshot.get("contract"),
        diagnostics=runner_snapshot.get("diagnostics"),
    )
    heartbeat_runner(
        api_url=api_url,
        runner_id=resolved_worker_id,
        api_token=api_token,
        status="listening",
        hostname=hostname or socket.gethostname(),
        provider_id=provider_id,
        instance_type_id=instance_type_id,
        metadata={"message": "Runner registered and is listening for jobs."},
        environment=runner_snapshot.get("environment"),
        contract=runner_snapshot.get("contract"),
        diagnostics=runner_snapshot.get("diagnostics"),
    )
    processed = 0
    completed = 0
    failed = 0
    while True:
        if max_jobs is not None and processed >= max_jobs:
            break
        result = run_worker_once(
            api_url=api_url,
            execution_mode=execution_mode,
            worker_id=resolved_worker_id,
            run_id=run_id,
            run_config_id=run_config_id,
            provider_id=provider_id,
            instance_type_id=instance_type_id,
            hostname=hostname,
            api_token=api_token,
            run_token=run_token,
            simulate=simulate,
            emit_progress=emit_progress,
            runner_snapshot=runner_snapshot,
        )
        if not result.get("claimed"):
            heartbeat_runner(
                api_url=api_url,
                runner_id=resolved_worker_id,
                api_token=api_token,
                status="listening",
                hostname=hostname or socket.gethostname(),
                provider_id=provider_id,
                instance_type_id=instance_type_id,
                metadata={"message": "Runner is listening for more work."},
                environment=runner_snapshot.get("environment"),
                contract=runner_snapshot.get("contract"),
                diagnostics=runner_snapshot.get("diagnostics"),
            )
            time.sleep(max(poll_interval_seconds, 0.1))
            continue
        processed += 1
        if result.get("completed"):
            completed += 1
        else:
            failed += 1
    return {
        "worker_id": resolved_worker_id,
        "processed_jobs": processed,
        "completed_jobs": completed,
        "failed_jobs": failed,
    }


def _default_worker_id() -> str:
    """Build a host-scoped default worker identifier."""
    return "worker-%s" % socket.gethostname()


def _doctor_failure_message(report: Dict[str, Any]) -> str:
    """Condense a doctor report into a short worker-facing failure reason."""
    failing_checks = [item for item in report.get("checks", []) if item.get("status") == "error"]
    if not failing_checks:
        return "Preflight failed."
    labels = ["%s (%s)" % (item.get("id"), item.get("message")) for item in failing_checks[:3]]
    if len(failing_checks) > 3:
        labels.append("and %d more" % (len(failing_checks) - 3))
    return "Preflight failed: %s." % "; ".join(labels)


def _classify_worker_failure(exc: Exception, doctor_report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Normalize common first-user-path failures into actionable error codes."""
    if doctor_report and not doctor_report.get("ok"):
        return _classify_doctor_failure(doctor_report)
    message = str(exc)
    lowered = message.lower()
    if "curl failed while downloading" in lowered or "quant artifact does not exist" in lowered or "sha256 mismatch" in lowered:
        return {
            "error_code": "artifact_download_failed",
            "message": "Artifact download failed: verify the artifact reference and reconnect Hugging Face if access is required.",
            "recovery": [
                {"label": "Check the artifact reference", "detail": "Confirm the Hugging Face path and quant filename are still valid."},
                {"label": "Reconnect Hugging Face if needed", "detail": "Private or gated artifacts need valid access before retrying."},
            ],
            "details": {"raw_error": message},
        }
    if "pull access denied" in lowered or "unable to find image" in lowered or "docker: error response from daemon" in lowered:
        return {
            "error_code": "missing_runtime_image",
            "message": "A required runtime image is missing locally. Build or pull it, then retry the run.",
            "recovery": [
                {"label": "Install the runtime image", "detail": "Use infergrade install-images for the missing image before retrying."},
                {"label": "Restart the listener", "detail": "A rebuilt listener image ensures the next claim sees the new runtime image."},
            ],
            "details": {"raw_error": message},
        }
    if "missing or invalid api token" in lowered or "run token is not valid" in lowered:
        return {
            "error_code": "auth_mismatch",
            "message": "Runner authentication failed. Refresh the paired runner profile or mint a fresh run token before retrying.",
            "recovery": [
                {"label": "Re-pair the runner or refresh the run token", "detail": "Stale tokens are a common first-user-path failure and are safe to rotate."},
            ],
            "details": {"raw_error": message},
        }
    if "no space left on device" in lowered or "path is not writable" in lowered or "insufficient free disk space" in lowered:
        return {
            "error_code": "insufficient_disk",
            "message": "The runner could not write to the output or cache path. Free space or change the path, then retry.",
            "recovery": [
                {"label": "Free space or choose a different path", "detail": "Artifact cache and bundle output both need writable disk."},
            ],
            "details": {"raw_error": message},
        }
    if "output directory already contains infergrade state" in lowered or "cannot resume" in lowered:
        return {
            "error_code": "output_path_conflict",
            "message": "The output path already contains conflicting InferGrade state. Resume the existing run or choose a fresh output path.",
            "recovery": [
                {"label": "Resume the interrupted run", "detail": "If you intend to continue the same run, retry with resume."},
                {"label": "Use a clean output path", "detail": "New runs should avoid reusing partially-populated bundle directories."},
            ],
            "details": {"raw_error": message},
        }
    if "contract version does not match" in lowered:
        return {
            "error_code": "contract_mismatch",
            "message": "Runner contract version does not match the Hub. Update to the pinned release lane before retrying.",
            "recovery": [
                {"label": "Update the runner", "detail": "Install or pull the Hub's pinned runner release before retrying."},
            ],
            "details": {"raw_error": message},
        }
    return {
        "error_code": "worker_execution_failed",
        "message": message,
        "recovery": [
            {"label": "Inspect the local progress and event timeline", "detail": "If the cause is not obvious, export support details and share them with the maintainer."},
        ],
        "details": {"raw_error": message},
    }


def _classify_doctor_failure(report: Dict[str, Any]) -> Dict[str, Any]:
    """Turn a failed doctor report into one operator-facing recovery summary."""
    failing_checks = [item for item in report.get("checks", []) if item.get("status") == "error"]
    primary = failing_checks[0] if failing_checks else {}
    check_id = str(primary.get("id") or "")
    details = dict(primary.get("details") or {})
    message = primary.get("message") or _doctor_failure_message(report)
    if check_id in {"docker_cli", "docker_daemon", "backend_image"} or check_id.startswith("capability_image_"):
        suggested = details.get("suggested_command") or "infergrade install-images"
        return {
            "error_code": "missing_runtime_image",
            "message": "Preflight failed because the local runtime image or container runtime is not ready.",
            "recovery": [
                {"label": "Prepare the runtime image", "detail": "Run %s, then restart the listener before retrying." % suggested},
            ],
            "details": {"failed_check": primary},
        }
    if check_id == "api_health":
        return {
            "error_code": "auth_mismatch",
            "message": "Preflight could not reach the Hub API. Confirm the API URL and token, then retry.",
            "recovery": [
                {"label": "Verify Hub reachability", "detail": "Make sure the paired runner can still reach the configured API URL."},
            ],
            "details": {"failed_check": primary},
        }
    if check_id == "artifact_cache_dir":
        return {
            "error_code": "insufficient_disk",
            "message": "Preflight found an unwritable or full artifact cache path.",
            "recovery": [
                {"label": "Free space or choose a different cache path", "detail": "Artifact downloads need a writable cache with enough free disk before retrying."},
            ],
            "details": {"failed_check": primary},
        }
    if check_id == "quant_artifact":
        return {
            "error_code": "artifact_download_failed",
            "message": "Preflight could not prepare the requested artifact.",
            "recovery": [
                {"label": "Fix the artifact reference", "detail": "Check the artifact URI, local file path, and Hugging Face access before retrying."},
            ],
            "details": {"failed_check": primary},
        }
    if check_id in {"output_dir"}:
        return {
            "error_code": "insufficient_disk",
            "message": "Preflight found an unwritable or full output path.",
            "recovery": [
                {"label": "Choose a writable output path", "detail": "Free space or point the run at a different writable directory."},
            ],
            "details": {"failed_check": primary},
        }
    if check_id in {"apple_silicon_local_container", "llama_cli_native", "llama_server_native", "native_backend_support"}:
        return {
            "error_code": "worker_execution_failed",
            "message": message,
            "recovery": [
                {"label": "Use the recommended local execution path", "detail": "Apple Silicon local llama.cpp runs should use local_native with the required native binaries installed."},
            ],
            "details": {"failed_check": primary},
        }
    return {
        "error_code": "worker_execution_failed",
        "message": _doctor_failure_message(report),
        "recovery": [
            {"label": "Review the failed preflight checks", "detail": "The doctor output names the first blocking dependency and should be fixed before retrying."},
        ],
        "details": {"failed_checks": failing_checks[:5]},
    }


def _runtime_progress_update(output_dir: Optional[str]) -> Tuple[Optional[str], Optional[str], Optional[float]]:
    """Project the local runner progress file into Hub-facing stage and percent updates."""
    if not output_dir:
        return None, None, None
    payload = load_progress(output_dir)
    if not payload:
        return None, None, None
    return payload.get("current_stage"), payload.get("current_detail"), _progress_percent(payload)


def _progress_percent(payload: Dict[str, Any]) -> Optional[float]:
    """Estimate a user-facing percent complete from the structured progress payload."""
    stage = payload.get("current_stage")
    if stage == "completed":
        return 100.0
    if stage == "finalization":
        return 96.0
    stage_defaults = {
        "environment_capture": 12.0,
        "artifact_resolution": 24.0,
        "backend_resolution": 36.0,
        "ontology_build": 44.0,
    }
    if stage == "capability":
        capability_benchmarks = payload.get("capability_benchmarks") or {}
        if not capability_benchmarks:
            return 52.0
        total_benchmarks = max(len(capability_benchmarks), 1)
        span = 12.0
        progress = 48.0
        completed_benchmarks = len(
            [item for item in capability_benchmarks.values() if item.get("status") == "completed"]
        )
        progress += (span * completed_benchmarks) / float(total_benchmarks)
        running_benchmarks = [item for item in capability_benchmarks.values() if item.get("status") == "running"]
        if running_benchmarks:
            running = running_benchmarks[0]
            total_cases = running.get("total_cases") or 0
            completed_cases = running.get("completed_cases") or 0
            if total_cases:
                progress += (span / float(total_benchmarks)) * min(completed_cases / float(total_cases), 0.98)
            else:
                progress += min(span / float(total_benchmarks) * 0.15, 2.0)
        return round(min(progress, 60.0), 1)
    if stage in stage_defaults:
        return stage_defaults[stage]
    if stage != "deployment":
        return None
    request_context = payload.get("request_context") or {}
    configured_profiles = list(request_context.get("deployment_profiles") or [])
    deployment_profiles = payload.get("deployment_profiles") or {}
    total_profiles = max(len(configured_profiles), len(deployment_profiles))
    if total_profiles <= 0:
        return 72.0
    completed_profiles = len([item for item in deployment_profiles.values() if item.get("status") == "completed"])
    running_profiles = [item for item in deployment_profiles.values() if item.get("status") == "running"]
    step = 34.0 / float(total_profiles)
    progress = 60.0 + (completed_profiles * step)
    if running_profiles:
        running = running_profiles[0]
        total_iterations = running.get("total_iterations") or 0
        completed_iterations = running.get("completed_iterations") or 0
        if total_iterations:
            progress += step * min(completed_iterations / float(total_iterations), 0.98)
        else:
            progress += min(step * 0.2, 6.0)
    return round(min(progress, 94.0), 1)
