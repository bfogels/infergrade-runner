from typing import Any, Dict, Optional

from infergrade.request import request_to_dict
from infergrade.utils import read_json, stable_hash, utcnow_iso, write_json


def progress_path(output_dir: str) -> str:
    return "%s/progress.json" % output_dir


def request_fingerprint(request) -> str:
    payload = request_to_dict(request)
    payload["output_dir"] = None
    payload["upload"] = False
    payload["resume"] = False
    return stable_hash(payload, length=16)


def initialize_progress(bundle_id: str, request, started_at: str) -> Dict[str, Any]:
    return {
        "spec_version": "0.1-draft",
        "bundle_id": bundle_id,
        "request_fingerprint": request_fingerprint(request),
        "request_context": {
            "model": request.model,
            "backend": request.backend,
            "tier": request.tier,
            "use_case": request.use_case,
            "deployment_profiles": list(request.deployment_profiles),
            "simulate": request.simulate,
            "run_config_id": request.run_config_id,
        },
        "status": "running",
        "started_at": started_at,
        "updated_at": started_at,
        "completed_at": None,
        "current_stage": "initializing",
        "current_detail": None,
        "stages": {
            "initializing": {
                "status": "completed",
                "started_at": started_at,
                "completed_at": started_at,
            }
        },
        "deployment_profiles": {},
        "errors": [],
    }


def load_progress(output_dir: str) -> Optional[Dict[str, Any]]:
    try:
        return read_json(progress_path(output_dir))
    except FileNotFoundError:
        return None


def save_progress(output_dir: str, progress: Dict[str, Any]) -> None:
    progress["updated_at"] = utcnow_iso()
    write_json(progress_path(output_dir), progress)


def mark_stage_started(output_dir: str, progress: Dict[str, Any], stage: str, detail: Optional[str] = None) -> None:
    now = utcnow_iso()
    progress["status"] = "running"
    progress["current_stage"] = stage
    progress["current_detail"] = detail
    progress["stages"][stage] = {
        "status": "running",
        "detail": detail,
        "started_at": now,
        "completed_at": None,
    }
    save_progress(output_dir, progress)


def mark_stage_completed(
    output_dir: str,
    progress: Dict[str, Any],
    stage: str,
    detail: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    now = utcnow_iso()
    stage_payload = progress["stages"].get(stage, {})
    stage_payload["status"] = "completed"
    stage_payload["detail"] = detail
    stage_payload["completed_at"] = now
    if "started_at" not in stage_payload:
        stage_payload["started_at"] = now
    if metadata:
        stage_payload["metadata"] = dict(metadata)
    progress["stages"][stage] = stage_payload
    progress["current_stage"] = stage
    progress["current_detail"] = detail
    save_progress(output_dir, progress)


def mark_profile_started(output_dir: str, progress: Dict[str, Any], profile_id: str) -> None:
    now = utcnow_iso()
    progress["status"] = "running"
    progress["current_stage"] = "deployment"
    progress["current_detail"] = profile_id
    progress["deployment_profiles"][profile_id] = {
        "status": "running",
        "started_at": now,
        "completed_at": None,
        "result_path": None,
        "result_id": None,
    }
    save_progress(output_dir, progress)


def mark_profile_completed(
    output_dir: str,
    progress: Dict[str, Any],
    profile_id: str,
    result_path: str,
    result_id: str,
) -> None:
    now = utcnow_iso()
    progress["deployment_profiles"][profile_id] = {
        "status": "completed",
        "started_at": progress["deployment_profiles"].get(profile_id, {}).get("started_at", now),
        "completed_at": now,
        "result_path": result_path,
        "result_id": result_id,
    }
    progress["current_stage"] = "deployment"
    progress["current_detail"] = profile_id
    save_progress(output_dir, progress)


def mark_failed(
    output_dir: str,
    progress: Dict[str, Any],
    stage: Optional[str],
    detail: Optional[str],
    message: str,
) -> None:
    progress["status"] = "failed"
    progress["current_stage"] = stage
    progress["current_detail"] = detail
    progress["completed_at"] = None
    progress["errors"].append(
        {
            "stage": stage,
            "detail": detail,
            "message": message,
            "timestamp": utcnow_iso(),
        }
    )
    save_progress(output_dir, progress)


def mark_completed(output_dir: str, progress: Dict[str, Any], result_count: int) -> None:
    now = utcnow_iso()
    progress["status"] = "completed"
    progress["current_stage"] = "completed"
    progress["current_detail"] = None
    progress["completed_at"] = now
    progress["stages"]["finalization"] = {
        "status": "completed",
        "started_at": progress["stages"].get("finalization", {}).get("started_at", now),
        "completed_at": now,
        "metadata": {"result_count": result_count},
    }
    save_progress(output_dir, progress)
