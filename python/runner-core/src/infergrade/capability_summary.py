"""Local capability summary artifact helpers."""

import json
import os
from typing import Any, Dict, List, Optional

from infergrade import __version__
from infergrade.benchmark_catalog import selection_metadata_for_request
from infergrade.capability_contract import CAPABILITY_SURFACES, validate_capability_summary_artifact
from infergrade.models import CapabilityExecution, RunRequest
from infergrade.utils import stable_hash, utcnow_iso, write_json

SUMMARY_SURFACES = (
    "local_assistant_capability",
    "local_coding_capability",
    "local_reasoning_capability",
    "quant_fidelity",
    "deployment_fitness",
)

NEXT_ACTION_BY_SURFACE = {
    "local_assistant_capability": ("run_assistant_decision_lane", "multiturn_chat_memory_v1"),
    "local_coding_capability": ("run_coding_decision_lane", "coding_static_repair_v1"),
    "local_reasoning_capability": ("run_reasoning_decision_lane", "reasoning_exact_answer_v1"),
}

MISSING_SURFACE_CLAIMS = {
    "local_assistant_capability": "No local assistant capability evidence has been collected in this bundle.",
    "local_coding_capability": "No local coding capability evidence has been collected in this bundle.",
    "local_reasoning_capability": "No local reasoning capability evidence has been collected in this bundle.",
    "quant_fidelity": "No quant-fidelity evidence is represented in this capability summary.",
    "deployment_fitness": "Deployment fitness remains separate from capability scoring in this summary.",
}

BASE_UNSUPPORTED_CLAIMS = [
    "This summary is not a global intelligence score.",
    "This summary is not leaderboard-grade evidence.",
    "Thin local samples are useful for setup guidance, not broad model ranking claims.",
]

CONFIDENCE_ORDER = {
    None: -1,
    "single_smoke": 0,
    "thin_local_sample": 1,
    "repeated_local_run": 2,
    "stronger_local_sample": 3,
    "reference_sample": 4,
    "gold": 5,
}

STATE_ORDER = {
    "failed": 0,
    "partial": 1,
    "scored": 2,
    "skipped": 3,
    "not_yet_benchmarked": 4,
    "not_comparable": 5,
}


def write_capability_summary_artifact(
    request: RunRequest,
    execution: CapabilityExecution,
    output_dir: str,
    created_at: Optional[str] = None,
) -> str:
    """Write and return the local capability summary artifact path."""
    path = os.path.join(output_dir, "artifacts", "capability", "capability_summary.json")
    artifact = build_capability_summary_artifact(request, execution, output_dir, created_at=created_at)
    errors = validate_capability_summary_artifact(artifact)
    if errors:
        raise ValueError("Invalid capability_summary artifact: %s" % "; ".join(errors))
    write_json(path, artifact)
    return path


def build_capability_summary_artifact(
    request: RunRequest,
    execution: CapabilityExecution,
    output_dir: str,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a conservative capability summary from produced capability artifacts."""
    created_at = created_at or utcnow_iso()
    artifact_pointers = _discover_capability_run_artifacts(execution, output_dir)
    surfaces = [_surface_summary(surface, artifact_pointers) for surface in SUMMARY_SURFACES]
    unsupported_claims = _unsupported_claim_summary(surfaces)
    artifact = {
        "artifact_spec_version": "0.1.0",
        "artifact_kind": "capability_summary",
        "summary_id": "capsum_%s" % stable_hash(
            {
                "model": request.model,
                "benchmark_check_ids": request.benchmark_check_ids,
                "artifacts": [item.get("path") for item in artifact_pointers],
            },
            length=12,
        ),
        "created_at": created_at,
        "runner": {
            "name": "infergrade-runner",
            "version": __version__,
            "contract_version": "0.1.0",
        },
        "subject": _subject_from_artifacts_or_request(request, artifact_pointers),
        "surfaces": surfaces,
        "capability_artifacts": artifact_pointers,
        "unsupported_claim_summary": unsupported_claims,
        "next_recommended_benchmark_action": _next_action(surfaces),
    }
    return artifact


def _discover_capability_run_artifacts(execution: CapabilityExecution, output_dir: str) -> List[Dict[str, Any]]:
    pointers = []
    artifact_benchmark_ids = set()
    for benchmark_id, paths in sorted(dict(execution.artifacts or {}).items()):
        if not isinstance(paths, dict):
            continue
        capability_run_path = paths.get("capability_run_path")
        if not capability_run_path:
            continue
        try:
            artifact = _read_json(capability_run_path)
        except (OSError, ValueError):
            metadata = _check_metadata_from_execution(execution, benchmark_id)
            surface = metadata.get("surface_id")
            if surface not in SUMMARY_SURFACES:
                continue
            pointers.append(
                {
                    "artifact_kind": "unreadable_capability_run",
                    "benchmark_id": benchmark_id,
                    "surface": surface,
                    "state": "failed",
                    "lane": metadata.get("evidence_lane_id") or "decision",
                    "confidence_label": _confidence_for_lane(metadata.get("evidence_lane_id") or "decision"),
                    "path": _relative_path(capability_run_path, output_dir),
                    "score": None,
                    "task_count": 0,
                    "failure_count": 1,
                    "error_class": "artifact_unreadable",
                }
            )
            continue
        evidence = dict(artifact.get("evidence") or {})
        summary = dict(artifact.get("summary") or {})
        protocol = dict(artifact.get("protocol") or {})
        tasks = list(artifact.get("tasks") or [])
        state = str(summary.get("state") or "not_comparable")
        artifact_benchmark_ids.add(benchmark_id)
        pointers.append(
            {
                "artifact_kind": "capability_run",
                "benchmark_id": benchmark_id,
                "surface": evidence.get("surface") or "local_assistant_capability",
                "state": state,
                "lane": evidence.get("lane") or "decision",
                "confidence_label": evidence.get("confidence_label") or "thin_local_sample",
                "path": _relative_path(capability_run_path, output_dir),
                "score": summary.get("score") if state in ("scored", "partial") else None,
                "task_count": len(tasks),
                "failure_count": len([task for task in tasks if task.get("state") == "failed"]),
                "partial_count": summary.get("partial_count") or 0,
                "repetition_count": protocol.get("repetitions") or 1,
                "experimental": evidence.get("experimental"),
                "unsupported_claims": list((artifact.get("claim_boundary") or {}).get("unsupported_claims") or []),
                "subject": dict(artifact.get("subject") or {}),
            }
        )
    pointers.extend(_fallback_benchmark_summary_pointers(execution, output_dir, artifact_benchmark_ids))
    return pointers


def _fallback_benchmark_summary_pointers(
    execution: CapabilityExecution,
    output_dir: str,
    artifact_benchmark_ids: set,
) -> List[Dict[str, Any]]:
    pointers = []
    for benchmark_id, result in sorted(dict(execution.benchmark_results or {}).items()):
        if benchmark_id in artifact_benchmark_ids or not isinstance(result, dict):
            continue
        metadata = _check_metadata_from_execution(execution, benchmark_id)
        surface = metadata.get("surface_id")
        if surface not in SUMMARY_SURFACES:
            continue
        state = _state_from_benchmark_summary(result)
        paths = dict((execution.artifacts or {}).get(benchmark_id) or {})
        summary_path = paths.get("summary_path")
        if not summary_path:
            continue
        pointers.append(
            {
                "artifact_kind": "benchmark_summary",
                "benchmark_id": benchmark_id,
                "surface": surface,
                "state": state,
                "lane": metadata.get("evidence_lane_id") or "decision",
                "confidence_label": _confidence_for_lane(metadata.get("evidence_lane_id") or "decision"),
                "path": _relative_path(summary_path, output_dir),
                "score": _primary_metric_value(result) if state in ("scored", "partial") else None,
                "task_count": int(result.get("total_cases") or 0),
                "failure_count": int(result.get("generation_failure_count") or 0),
                "partial_count": 1 if state == "partial" else 0,
                "repetition_count": 1,
                "experimental": True,
                "unsupported_claims": [
                    "This benchmark summary is not a global capability score.",
                    "This benchmark summary does not replace a Runner-owned capability_run artifact.",
                ],
            }
        )
    return pointers


def _surface_summary(surface: str, artifact_pointers: List[Dict[str, Any]]) -> Dict[str, Any]:
    surface_artifacts = [item for item in artifact_pointers if item.get("surface") == surface]
    if not surface_artifacts:
        return {
            "surface": surface,
            "state": "not_yet_benchmarked",
            "score": None,
            "lane": None,
            "confidence_label": None,
            "experimental": None,
            "repetition_count": 0,
            "task_count": 0,
            "failure_count": 0,
            "partial_count": 0,
            "capability_artifacts": [],
            "unsupported_claims": [MISSING_SURFACE_CLAIMS[surface]],
        }
    states = [str(item.get("state") or "not_comparable") for item in surface_artifacts]
    state = _aggregate_state(states)
    scores = [float(item["score"]) for item in surface_artifacts if isinstance(item.get("score"), (int, float))]
    score = round(sum(scores) / float(len(scores)), 6) if scores and state in ("scored", "partial") else None
    return {
        "surface": surface,
        "state": state,
        "score": score,
        "lane": _strongest_lane([item.get("lane") for item in surface_artifacts]),
        "confidence_label": _conservative_confidence_label(surface_artifacts),
        "experimental": any(bool(item.get("experimental")) for item in surface_artifacts),
        "repetition_count": sum(int(item.get("repetition_count") or 0) for item in surface_artifacts),
        "task_count": sum(int(item.get("task_count") or 0) for item in surface_artifacts),
        "failure_count": sum(int(item.get("failure_count") or 0) for item in surface_artifacts),
        "partial_count": sum(int(item.get("partial_count") or 0) for item in surface_artifacts),
        "capability_artifacts": surface_artifacts,
        "unsupported_claims": _dedupe_claims(
            claim
            for item in surface_artifacts
            for claim in list(item.get("unsupported_claims") or [])
        ),
    }


def _aggregate_state(states: List[str]) -> str:
    states = [state if state in STATE_ORDER else "not_comparable" for state in states]
    if not states:
        return "not_yet_benchmarked"
    if any(state == "partial" for state in states):
        return "partial"
    if any(state == "failed" for state in states) and any(state == "scored" for state in states):
        return "partial"
    if all(state == "scored" for state in states):
        return "scored"
    if all(state == "failed" for state in states):
        return "failed"
    if all(state == "skipped" for state in states):
        return "skipped"
    if all(state == "not_yet_benchmarked" for state in states):
        return "not_yet_benchmarked"
    if all(state == "not_comparable" for state in states):
        return "not_comparable"
    return sorted(states, key=lambda item: STATE_ORDER.get(item, 99))[0]


def _state_from_benchmark_summary(summary: Dict[str, Any]) -> str:
    status = str(summary.get("status") or "")
    value = _primary_metric_value(summary)
    if status in ("failed", "error"):
        return "failed"
    if status in ("partial", "degraded"):
        return "partial"
    if value is not None:
        return "scored"
    if status == "skipped":
        return "skipped"
    return "not_comparable"


def _primary_metric_value(summary: Dict[str, Any]) -> Optional[float]:
    value = dict(summary.get("primary_metric") or {}).get("value")
    try:
        return None if value is None else round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _strongest_lane(lanes: List[Optional[str]]) -> Optional[str]:
    order = {"smoke": 0, "decision": 1, "reference": 2, "gold": 3}
    known = [lane for lane in lanes if lane in order]
    if not known:
        return None
    return sorted(known, key=lambda item: order[item], reverse=True)[0]


def _conservative_confidence_label(artifacts: List[Dict[str, Any]]) -> Optional[str]:
    labels = [item.get("confidence_label") for item in artifacts if item.get("confidence_label") in CONFIDENCE_ORDER]
    if not labels:
        return None
    strongest = sorted(labels, key=lambda item: CONFIDENCE_ORDER[item], reverse=True)[0]
    lane = _strongest_lane([item.get("lane") for item in artifacts])
    if lane == "decision" and CONFIDENCE_ORDER[strongest] > CONFIDENCE_ORDER["repeated_local_run"]:
        return "repeated_local_run"
    if lane == "smoke" and strongest != "single_smoke":
        return "single_smoke"
    return strongest


def _confidence_for_lane(lane: str) -> str:
    if lane == "smoke":
        return "single_smoke"
    if lane == "reference":
        return "reference_sample"
    if lane == "gold":
        return "gold"
    return "thin_local_sample"


def _check_metadata_from_execution(execution: CapabilityExecution, benchmark_id: str) -> Dict[str, Any]:
    request = RunRequest(
        model="summary-metadata",
        backend="summary",
        tier=execution.benchmark_tier or "standard",
        capability_suite_ids=list(execution.suite_ids or []),
        benchmark_group_ids=list(execution.benchmark_group_ids or []),
        benchmark_check_ids=list(execution.benchmark_check_ids or []),
        use_case=execution.use_case,
    )
    metadata = selection_metadata_for_request(request)
    for check in list(metadata.get("benchmark_checks") or []):
        if check.get("check_id") == benchmark_id:
            return dict(check)
    return {}


def _unsupported_claim_summary(surfaces: List[Dict[str, Any]]) -> List[str]:
    claims = list(BASE_UNSUPPORTED_CLAIMS)
    for surface in surfaces:
        claims.extend(list(surface.get("unsupported_claims") or []))
    return _dedupe_claims(claims)


def _next_action(surfaces: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_surface = {item.get("surface"): item for item in surfaces}
    for surface in ("local_assistant_capability", "local_coding_capability", "local_reasoning_capability"):
        item = by_surface.get(surface) or {}
        if item.get("state") in ("failed", "partial"):
            return {
                "action": "retry_or_inspect_capability_lane",
                "surface": surface,
                "benchmark_check_id": NEXT_ACTION_BY_SURFACE[surface][1],
                "reason": "This surface has failed or partial local evidence; inspect the raw artifact or retry the lane before comparing scores.",
            }
    for surface in ("local_assistant_capability", "local_coding_capability", "local_reasoning_capability"):
        item = by_surface.get(surface) or {}
        if item.get("state") in (None, "not_yet_benchmarked", "skipped", "not_comparable"):
            action, benchmark_id = NEXT_ACTION_BY_SURFACE[surface]
            return {
                "action": action,
                "surface": surface,
                "benchmark_check_id": benchmark_id,
                "reason": "This surface is missing local decision-lane evidence.",
            }
    return {
        "action": "repeat_local_capability_run",
        "surface": None,
        "benchmark_check_id": None,
        "reason": "Assistant, coding, and reasoning thin local samples are present; repeat the local capability run to improve confidence without treating it as a leaderboard score.",
    }


def _subject_from_artifacts_or_request(request: RunRequest, artifact_pointers: List[Dict[str, Any]]) -> Dict[str, Any]:
    for pointer in artifact_pointers:
        subject = pointer.get("subject")
        if isinstance(subject, dict) and subject:
            return subject
    return {
        "model": {
            "model": request.model,
            "quant_artifact": request.quant_artifact,
            "quant_artifact_sha256": request.quant_artifact_sha256,
            "quant_artifact_filename": request.quant_artifact_filename,
        },
        "runtime": {
            "backend": request.backend,
            "execution_mode": request.execution_mode,
            "llama_cpp_cli_path": request.llama_cpp_cli_path,
        },
        "hardware": {
            "source": "run_bundle_environment",
        },
    }


def _dedupe_claims(claims) -> List[str]:
    deduped = []
    seen = set()
    for claim in claims:
        if not isinstance(claim, str) or not claim.strip():
            continue
        if claim not in seen:
            deduped.append(claim)
            seen.add(claim)
    return deduped or ["No broad capability claim is supported by this summary."]


def _relative_path(path: str, output_dir: str) -> str:
    try:
        return os.path.relpath(path, output_dir)
    except ValueError:
        return path


def _read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


assert set(SUMMARY_SURFACES).issubset(set(CAPABILITY_SURFACES))
