"""Bounded Hub-directed benchmark-agent execution."""

from typing import Any, Callable, Dict, Optional

from infergrade.transport import fetch_agent_work_plan, materialize_agent_work_candidate
from infergrade.worker import run_worker_once


def run_agent_work_loop(
    *,
    api_url: str,
    worker_id: str,
    api_token: str,
    hostname: Optional[str] = None,
    max_jobs: Optional[int] = None,
    simulate: bool = False,
    emit_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Materialize and execute only work authorized by the paired grant."""
    progress = emit_progress or (lambda _message: None)
    processed = 0
    completed = 0
    failed = 0
    selected = []
    final_plan = None

    while max_jobs is None or processed < max_jobs:
        plan = fetch_agent_work_plan(api_url, api_token=api_token)
        candidates = list(plan.get("candidates") or [])
        if not candidates:
            final_plan = plan
            break
        candidate = candidates[0]
        progress(_selection_message(candidate))
        materialized = materialize_agent_work_candidate(
            api_url,
            candidate_id=candidate["candidate_id"],
            grant_id=(plan.get("grant") or {}).get("grant_id"),
            api_token=api_token,
        )
        run = materialized.get("run") or {}
        run_id = run.get("run_id")
        if not run_id:
            raise RuntimeError("Hub materialized agent work without returning a run_id")
        result = run_worker_once(
            api_url=api_url,
            execution_mode="local_native",
            worker_id=worker_id,
            run_id=run_id,
            hostname=hostname,
            api_token=api_token,
            run_token=None,
            simulate=simulate,
            emit_progress=emit_progress,
        )
        if result.get("claimed") is not True:
            raise RuntimeError("Materialized agent run %s was not claimable by this paired runner" % run_id)
        processed += 1
        completed += int(bool(result.get("completed")))
        failed += int(bool(result.get("failed")))
        selected.append({
            "candidate_id": candidate.get("candidate_id"),
            "run_id": run_id,
            "model_id": candidate.get("model_id"),
            "quantization_scheme": candidate.get("quantization_scheme"),
            "use_case": candidate.get("use_case"),
            "selection_basis": candidate.get("selection_basis"),
            "completed": bool(result.get("completed")),
            "failed": bool(result.get("failed")),
        })

    if final_plan is None:
        final_plan = fetch_agent_work_plan(api_url, api_token=api_token)
    return {
        "worker_id": worker_id,
        "mode": "bounded_agent_work",
        "processed_jobs": processed,
        "completed_jobs": completed,
        "failed_jobs": failed,
        "selected": selected,
        "grant": final_plan.get("grant") or {},
        "stopped_reason": (
            "local_max_jobs_reached"
            if max_jobs is not None and processed >= max_jobs and list(final_plan.get("candidates") or [])
            else "grant_has_no_remaining_candidates"
        ),
    }


def _selection_message(candidate: Dict[str, Any]) -> str:
    """Describe the immutable Hub choice without exposing credentials."""
    model = candidate.get("model_id") or "unknown model"
    quant = candidate.get("quantization_scheme") or "unknown quant"
    use_case = candidate.get("use_case") or "unknown task"
    size_gib = float(candidate.get("download_size_bytes") or 0) / float(1024 ** 3)
    return "Hub selected %s · %s · %s (%.2f GiB download)." % (model, quant, use_case, size_gib)
