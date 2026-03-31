"""Worker loop for claiming and executing InferGrade run jobs."""

import socket
import time
from typing import Any, Callable, Dict, Optional

from infergrade.run_configs import request_from_run_config_document
from infergrade.runner import run_infergrade
from infergrade.transport import (
    claim_run_job,
    complete_run_job,
    fail_run_job,
    fetch_run_config,
    heartbeat_run_job,
    upload_bundle,
)


def execute_run_job(
    api_url: str,
    run_job: Dict[str, Any],
    worker_id: str,
    api_token: str = None,
    simulate: bool = False,
    emit_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Execute one claimed run job and report lifecycle state back to the API."""
    run_id = run_job["run_id"]
    try:
        heartbeat_run_job(api_url, run_id, worker_id, stage="fetch_run_config", message="Fetching run config.", api_token=api_token)
        payload = fetch_run_config(api_url, run_job["run_config_id"], api_token=api_token)
        request = request_from_run_config_document(payload, simulate=simulate)
        request.output_dir = run_job.get("output_dir")
        request.resume = True
        if run_job.get("execution_mode"):
            request.execution_mode = run_job["execution_mode"]
        cloud = run_job.get("cloud") or {}
        if cloud.get("provider_id"):
            request.cloud_provider = cloud.get("provider_id")
        if cloud.get("instance_type_id"):
            request.cloud_instance_type = cloud.get("instance_type_id")

        def _emit(message: str) -> None:
            if emit_progress:
                emit_progress(message)
            heartbeat_run_job(api_url, run_id, worker_id, message=message, api_token=api_token)

        result = run_infergrade(request, emit_progress=_emit)
        heartbeat_run_job(api_url, run_id, worker_id, stage="upload", message="Uploading completed bundle.", progress_percent=95.0, api_token=api_token)
        upload = upload_bundle(result["output_dir"], api_url, api_token=api_token)
        completed = complete_run_job(
            api_url,
            run_id,
            worker_id,
            bundle_id=result["bundle_id"],
            upload=upload,
            api_token=api_token,
        )
        return {
            "claimed": True,
            "completed": True,
            "run": completed.get("run"),
            "bundle": result,
            "upload": upload,
        }
    except Exception as exc:
        try:
            fail_run_job(api_url, run_id, worker_id, message=str(exc), error_code="worker_execution_failed", api_token=api_token)
        except Exception:
            pass
        if emit_progress:
            emit_progress("Run %s failed: %s" % (run_id, exc))
        return {
            "claimed": True,
            "completed": False,
            "run_id": run_id,
            "error": str(exc),
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
    simulate: bool = False,
    emit_progress: Optional[Callable[[str], None]] = None,
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
        simulate=simulate,
        emit_progress=emit_progress,
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
    simulate: bool = False,
    poll_interval_seconds: float = 10.0,
    max_jobs: Optional[int] = None,
    emit_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Continuously poll for run jobs and execute them."""
    resolved_worker_id = worker_id or _default_worker_id()
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
            simulate=simulate,
            emit_progress=emit_progress,
        )
        if not result.get("claimed"):
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
