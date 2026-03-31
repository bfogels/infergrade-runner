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
        "capability_benchmarks": {},
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


def update_stage_progress(
    output_dir: str,
    progress: Dict[str, Any],
    stage: str,
    detail: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    now = utcnow_iso()
    stage_payload = progress["stages"].get(stage, {})
    stage_payload["status"] = "running"
    stage_payload["detail"] = detail
    if "started_at" not in stage_payload:
        stage_payload["started_at"] = now
    if metadata:
        merged_metadata = dict(stage_payload.get("metadata") or {})
        merged_metadata.update(metadata)
        stage_payload["metadata"] = merged_metadata
    progress["status"] = "running"
    progress["current_stage"] = stage
    progress["current_detail"] = detail
    progress["stages"][stage] = stage_payload
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
        "total_iterations": None,
        "completed_iterations": 0,
        "warmup_runs": None,
        "measured_runs": None,
        "current_iteration": None,
        "current_phase": None,
        "progress_detail": None,
    }
    save_progress(output_dir, progress)


def update_profile_progress(
    output_dir: str,
    progress: Dict[str, Any],
    profile_id: str,
    total_iterations: Optional[int] = None,
    completed_iterations: Optional[int] = None,
    warmup_runs: Optional[int] = None,
    measured_runs: Optional[int] = None,
    current_iteration: Optional[int] = None,
    current_phase: Optional[str] = None,
    progress_detail: Optional[str] = None,
) -> None:
    now = utcnow_iso()
    profile_payload = dict(progress["deployment_profiles"].get(profile_id, {}))
    profile_payload["status"] = "running"
    profile_payload["started_at"] = profile_payload.get("started_at", now)
    profile_payload["completed_at"] = None
    profile_payload["result_path"] = profile_payload.get("result_path")
    profile_payload["result_id"] = profile_payload.get("result_id")
    if total_iterations is not None:
        profile_payload["total_iterations"] = total_iterations
    if completed_iterations is not None:
        profile_payload["completed_iterations"] = completed_iterations
    if warmup_runs is not None:
        profile_payload["warmup_runs"] = warmup_runs
    if measured_runs is not None:
        profile_payload["measured_runs"] = measured_runs
    if current_iteration is not None:
        profile_payload["current_iteration"] = current_iteration
    if current_phase is not None:
        profile_payload["current_phase"] = current_phase
    if progress_detail is not None:
        profile_payload["progress_detail"] = progress_detail
    progress["status"] = "running"
    progress["current_stage"] = "deployment"
    progress["current_detail"] = profile_id
    progress["deployment_profiles"][profile_id] = profile_payload
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
        "total_iterations": progress["deployment_profiles"].get(profile_id, {}).get("total_iterations"),
        "completed_iterations": progress["deployment_profiles"].get(profile_id, {}).get("total_iterations"),
        "warmup_runs": progress["deployment_profiles"].get(profile_id, {}).get("warmup_runs"),
        "measured_runs": progress["deployment_profiles"].get(profile_id, {}).get("measured_runs"),
        "current_iteration": progress["deployment_profiles"].get(profile_id, {}).get("total_iterations"),
        "current_phase": "completed",
        "progress_detail": "completed",
    }
    progress["current_stage"] = "deployment"
    progress["current_detail"] = profile_id
    save_progress(output_dir, progress)


def mark_capability_benchmark_started(
    output_dir: str,
    progress: Dict[str, Any],
    benchmark_id: str,
    display_name: str,
    total_cases: Optional[int] = None,
) -> None:
    now = utcnow_iso()
    progress["status"] = "running"
    progress["current_stage"] = "capability"
    progress["current_detail"] = benchmark_id
    progress["capability_benchmarks"][benchmark_id] = {
        "status": "running",
        "display_name": display_name,
        "started_at": now,
        "completed_at": None,
        "total_cases": total_cases,
        "completed_cases": 0,
        "current_case": None,
        "progress_detail": None,
    }
    save_progress(output_dir, progress)


def update_capability_benchmark_progress(
    output_dir: str,
    progress: Dict[str, Any],
    benchmark_id: str,
    completed_cases: Optional[int] = None,
    total_cases: Optional[int] = None,
    current_case: Optional[str] = None,
    progress_detail: Optional[str] = None,
) -> None:
    now = utcnow_iso()
    benchmark_payload = dict(progress["capability_benchmarks"].get(benchmark_id, {}))
    benchmark_payload["status"] = "running"
    benchmark_payload["started_at"] = benchmark_payload.get("started_at", now)
    benchmark_payload["completed_at"] = None
    if total_cases is not None:
        benchmark_payload["total_cases"] = total_cases
    if completed_cases is not None:
        benchmark_payload["completed_cases"] = completed_cases
    if current_case is not None:
        benchmark_payload["current_case"] = current_case
    if progress_detail is not None:
        benchmark_payload["progress_detail"] = progress_detail
    progress["status"] = "running"
    progress["current_stage"] = "capability"
    progress["current_detail"] = benchmark_id
    progress["capability_benchmarks"][benchmark_id] = benchmark_payload
    save_progress(output_dir, progress)


def mark_capability_benchmark_completed(
    output_dir: str,
    progress: Dict[str, Any],
    benchmark_id: str,
    status: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    now = utcnow_iso()
    benchmark_payload = dict(progress["capability_benchmarks"].get(benchmark_id, {}))
    benchmark_payload["status"] = status
    benchmark_payload["completed_at"] = now
    if benchmark_payload.get("total_cases") is not None and benchmark_payload.get("completed_cases") is None:
        benchmark_payload["completed_cases"] = benchmark_payload["total_cases"]
    if metadata:
        merged_metadata = dict(benchmark_payload.get("metadata") or {})
        merged_metadata.update(metadata)
        benchmark_payload["metadata"] = merged_metadata
    progress["current_stage"] = "capability"
    progress["current_detail"] = benchmark_id
    progress["capability_benchmarks"][benchmark_id] = benchmark_payload
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
