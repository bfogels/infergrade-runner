"""Local capability summary artifact helpers."""

import json
import math
import os
from typing import Any, Dict, List, Optional

from infergrade import __version__
from infergrade.benchmark_catalog import selection_metadata_for_request
from infergrade.capability_contract import CAPABILITY_SURFACES, validate_capability_summary_artifact
from infergrade.capability_scoring import score_capability_surface
from infergrade.contracts import load_contract_manifest
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
    "repeated_local_sample": 2,
    "repeated_local_run": 2,
    "sampled_reference": 3,
    "reference_sample": 3,
    "stronger_local_sample": 4,
    "gold": 5,
}

LEGACY_CONFIDENCE_ALIASES = {
    "repeated_local_run": "repeated_local_sample",
    "reference_sample": "sampled_reference",
}

STATE_ORDER = {
    "failed": 0,
    "partial": 1,
    "scored": 2,
    "skipped": 3,
    "not_yet_benchmarked": 4,
    "not_comparable": 5,
}

_CONTRACT_VERSION = str(load_contract_manifest().get("contract_version") or "unknown")


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
            "contract_version": _CONTRACT_VERSION,
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
        lane = evidence.get("lane") or "decision"
        repetition_count = int(protocol.get("repetitions") or 1)
        artifact_benchmark_ids.add(benchmark_id)
        confidence_label = _confidence_from_artifact(
            lane=lane,
            label=evidence.get("confidence_label"),
            repetition_count=repetition_count,
            state=state,
        )
        pointers.append(
            {
                "artifact_kind": "capability_run",
                "benchmark_id": benchmark_id,
                "surface": evidence.get("surface") or "local_assistant_capability",
                "state": state,
                "lane": lane,
                "confidence_label": confidence_label,
                "confidence_explanation": _confidence_explanation(confidence_label),
                "path": _relative_path(capability_run_path, output_dir),
                "score": summary.get("score") if state in ("scored", "partial") else None,
                "task_count": len(tasks),
                "failure_count": len([task for task in tasks if task.get("state") == "failed"]),
                "partial_count": summary.get("partial_count") or 0,
                "repetition_count": repetition_count,
                "repeatability": _repeatability_summary(
                    summary=summary,
                    tasks=tasks,
                    repetition_count=repetition_count,
                    failure_count=len([task for task in tasks if task.get("state") == "failed"]),
                    partial_count=int(summary.get("partial_count") or 0),
                ),
                "task_performance": dict(summary.get("task_performance") or {}),
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
                "confidence_explanation": _confidence_explanation(
                    _confidence_for_lane(metadata.get("evidence_lane_id") or "decision")
                ),
                "path": _relative_path(summary_path, output_dir),
                "score": _primary_metric_value(result) if state in ("scored", "partial") else None,
                "task_count": int(result.get("total_cases") or 0),
                "failure_count": int(result.get("generation_failure_count") or 0),
                "partial_count": 1 if state == "partial" else 0,
                "repetition_count": 1,
                "repeatability": _repeatability_summary(
                    summary=result,
                    tasks=[],
                    repetition_count=1,
                    failure_count=int(result.get("generation_failure_count") or 0),
                    partial_count=1 if state == "partial" else 0,
                ),
                "task_performance": dict(result.get("task_performance") or {}),
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
        missing_score_details = score_capability_surface(surface, {})
        return {
            "surface": surface,
            "state": "not_yet_benchmarked",
            "score": None,
            "score_observed": missing_score_details.get("observed_weighted_score"),
            "score_label": missing_score_details.get("score_label"),
            "score_version": missing_score_details.get("score_version"),
            "score_method": missing_score_details.get("score_method"),
            "score_ready": False,
            "score_coverage": missing_score_details.get("coverage"),
            "score_components": missing_score_details.get("components", []),
            "score_claim_boundary": missing_score_details.get("claim_boundary"),
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
    score_details = score_capability_surface(
        surface,
        {
            str(item.get("benchmark_id")): float(item["score"])
            for item in surface_artifacts
            if item.get("benchmark_id") and isinstance(item.get("score"), (int, float))
        },
    )
    if score_details.get("reason") == "surface_score_policy_missing":
        score = round(sum(scores) / float(len(scores)), 6) if scores and state in ("scored", "partial") else None
    else:
        score = score_details.get("score") if state in ("scored", "partial") else None
    confidence_label = _conservative_confidence_label(surface_artifacts)
    return {
        "surface": surface,
        "state": state,
        "score": score,
        "score_observed": score_details.get("observed_weighted_score"),
        "score_label": score_details.get("score_label"),
        "score_version": score_details.get("score_version"),
        "score_method": score_details.get("score_method"),
        "score_ready": bool(score_details.get("score_ready")),
        "score_coverage": score_details.get("coverage"),
        "score_components": list(score_details.get("components") or []),
        "score_claim_boundary": score_details.get("claim_boundary"),
        "lane": _strongest_lane([item.get("lane") for item in surface_artifacts]),
        "confidence_label": confidence_label,
        "confidence_explanation": _confidence_explanation(confidence_label),
        "experimental": any(bool(item.get("experimental")) for item in surface_artifacts),
        "repetition_count": sum(int(item.get("repetition_count") or 0) for item in surface_artifacts),
        "task_count": sum(int(item.get("task_count") or 0) for item in surface_artifacts),
        "failure_count": sum(int(item.get("failure_count") or 0) for item in surface_artifacts),
        "partial_count": sum(int(item.get("partial_count") or 0) for item in surface_artifacts),
        "repeatability": _surface_repeatability_summary(surface_artifacts),
        "task_performance": _surface_task_performance_summary(surface_artifacts),
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
    if lane == "decision" and CONFIDENCE_ORDER[strongest] > CONFIDENCE_ORDER["repeated_local_sample"]:
        return "repeated_local_sample"
    if lane == "smoke" and strongest != "single_smoke":
        return "single_smoke"
    return _canonical_confidence_label(strongest)


def _confidence_for_lane(lane: str) -> str:
    if lane == "smoke":
        return "single_smoke"
    if lane == "reference":
        return "sampled_reference"
    if lane == "gold":
        return "gold"
    return "thin_local_sample"


def _canonical_confidence_label(label: Optional[str]) -> Optional[str]:
    if label is None:
        return None
    return LEGACY_CONFIDENCE_ALIASES.get(label, label)


def _confidence_from_artifact(
    lane: str,
    label: Optional[str],
    repetition_count: int,
    state: str,
) -> str:
    canonical = _canonical_confidence_label(label) or _confidence_for_lane(lane)
    if lane == "decision" and canonical == "thin_local_sample" and repetition_count >= 2 and state in ("scored", "partial"):
        return "repeated_local_sample"
    return canonical


def _confidence_explanation(label: Optional[str]) -> str:
    return {
        None: "No evidence is present for this surface yet.",
        "single_smoke": "Single smoke evidence checks that the setup can run; it is not enough for a decision-grade claim.",
        "thin_local_sample": "Thin local evidence can guide setup choice, but needs repeats or broader samples before stronger claims.",
        "repeated_local_sample": "Repeated local evidence reports repeatability and instability metrics for this setup.",
        "sampled_reference": "Sampled reference evidence uses a broader benchmark protocol, but remains scoped to its sample and protocol.",
        "stronger_local_sample": "Stronger local evidence combines broader local sampling with repeatability controls.",
        "gold": "Gold evidence has the strongest protocol controls in this contract.",
    }.get(label, "This evidence label is accepted for backward compatibility; use canonical v0.3.2 labels for new artifacts.")


def _repeatability_summary(
    summary: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    repetition_count: int,
    failure_count: int,
    partial_count: int,
) -> Dict[str, Any]:
    latency_values = _metric_values(tasks, "latency_ms")
    ttft_values = _metric_values(tasks, "time_to_first_token_ms")
    tokens_per_second_values = _metric_values(tasks, "tokens_per_second")
    task_scores = _metric_values(tasks, "score")
    pass_values = [1.0 if task.get("state") == "scored" and task.get("score") == 1.0 else 0.0 for task in tasks if task.get("state") in ("scored", "failed")]

    if not latency_values:
        latency_values = _summary_metric_values(summary, ("latency_median_ms", "latency_p50_ms", "latency_p95_ms", "duration_seconds"))
    if not ttft_values:
        ttft_values = _summary_metric_values(summary, ("time_to_first_token_ms", "ttft_median_ms", "ttft_p50_ms", "ttft_p95_ms"))
    if not tokens_per_second_values:
        tokens_per_second_values = _summary_metric_values(summary, ("tokens_per_second", "tokens_per_second_median"))
    if not task_scores and isinstance(summary.get("score"), (int, float)):
        task_scores = [float(summary["score"])]

    sample_count = max(repetition_count, len(tasks), 1)
    total_attempts = max(len(tasks), sample_count)
    failure_rate = round(float(failure_count + partial_count) / float(total_attempts), 6) if total_attempts else 0.0
    stats = {
        "sample_count": sample_count,
        "repetition_count": repetition_count,
        "failure_rate": failure_rate,
        "latency_median_ms": _percentile(latency_values, 0.50),
        "latency_p95_ms": _percentile(latency_values, 0.95),
        "latency_variance": _variance(latency_values),
        "ttft_median_ms": _percentile(ttft_values, 0.50),
        "ttft_p95_ms": _percentile(ttft_values, 0.95),
        "ttft_variance": _variance(ttft_values),
        "tokens_per_second_median": _percentile(tokens_per_second_values, 0.50),
        "tokens_per_second_p95": _percentile(tokens_per_second_values, 0.95),
        "tokens_per_second_variance": _variance(tokens_per_second_values),
        "capability_pass_rate_median": _percentile(pass_values, 0.50),
        "capability_pass_rate_variance": _variance(pass_values),
        "score_variance": _variance(task_scores),
    }
    reasons = _instability_reasons(stats, latency_values, ttft_values, tokens_per_second_values)
    stats["unstable"] = bool(reasons)
    stats["instability_reasons"] = reasons
    return stats


def _surface_repeatability_summary(artifacts: List[Dict[str, Any]]) -> Dict[str, Any]:
    summaries = [dict(item.get("repeatability") or {}) for item in artifacts]
    sample_count = sum(int(item.get("sample_count") or 0) for item in summaries)
    repetition_count = sum(int(item.get("repetition_count") or 0) for item in summaries)
    reasons = sorted({reason for item in summaries for reason in list(item.get("instability_reasons") or [])})
    return {
        "sample_count": sample_count,
        "repetition_count": repetition_count,
        "failure_rate": _weighted_average(summaries, "failure_rate", "sample_count"),
        "latency_median_ms": _median_of_summaries(summaries, "latency_median_ms"),
        "latency_p95_ms": _max_summary_value(summaries, "latency_p95_ms"),
        "latency_variance": _max_summary_value(summaries, "latency_variance"),
        "ttft_median_ms": _median_of_summaries(summaries, "ttft_median_ms"),
        "ttft_p95_ms": _max_summary_value(summaries, "ttft_p95_ms"),
        "ttft_variance": _max_summary_value(summaries, "ttft_variance"),
        "tokens_per_second_median": _median_of_summaries(summaries, "tokens_per_second_median"),
        "tokens_per_second_p95": _max_summary_value(summaries, "tokens_per_second_p95"),
        "tokens_per_second_variance": _max_summary_value(summaries, "tokens_per_second_variance"),
        "capability_pass_rate_median": _median_of_summaries(summaries, "capability_pass_rate_median"),
        "capability_pass_rate_variance": _max_summary_value(summaries, "capability_pass_rate_variance"),
        "score_variance": _max_summary_value(summaries, "score_variance"),
        "unstable": any(bool(item.get("unstable")) for item in summaries),
        "instability_reasons": reasons,
    }


def _surface_task_performance_summary(artifacts: List[Dict[str, Any]]) -> Dict[str, Any]:
    summaries = [dict(item.get("task_performance") or {}) for item in artifacts]
    attempted = sum(int(item.get("attempted_task_count") or 0) for item in summaries)
    timed = sum(int(item.get("timed_task_count") or 0) for item in summaries)
    output_measured = sum(int(item.get("output_token_task_count") or 0) for item in summaries)
    sources = sorted({source for item in summaries for source in list(item.get("measurement_sources") or [])})
    total_elapsed = [float(item["total_elapsed_seconds"]) for item in summaries if isinstance(item.get("total_elapsed_seconds"), (int, float))]
    total_input = [int(item["total_input_tokens"]) for item in summaries if isinstance(item.get("total_input_tokens"), int)]
    total_output = [int(item["total_output_tokens"]) for item in summaries if isinstance(item.get("total_output_tokens"), int)]
    return {
        "attempted_task_count": attempted,
        "completed_task_count": sum(int(item.get("completed_task_count") or 0) for item in summaries),
        "timed_task_count": timed,
        "output_token_task_count": output_measured,
        "timing_coverage_fraction": round(timed / float(attempted), 6) if attempted else 0.0,
        "output_token_coverage_fraction": round(output_measured / float(attempted), 6) if attempted else 0.0,
        "time_per_task_seconds_median": _median_of_summaries(summaries, "time_per_task_seconds_median"),
        "time_per_task_seconds_p95": _max_summary_value(summaries, "time_per_task_seconds_p95"),
        "time_to_first_token_ms_median": _median_of_summaries(summaries, "time_to_first_token_ms_median"),
        "output_tokens_per_task_median": _median_of_summaries(summaries, "output_tokens_per_task_median"),
        "output_tokens_per_task_p95": _max_summary_value(summaries, "output_tokens_per_task_p95"),
        "decode_tokens_per_second_median": _median_of_summaries(summaries, "decode_tokens_per_second_median"),
        "decode_tokens_per_second_p95": _max_summary_value(summaries, "decode_tokens_per_second_p95"),
        "total_elapsed_seconds": round(sum(total_elapsed), 6) if total_elapsed else None,
        "total_input_tokens": sum(total_input) if total_input else None,
        "total_output_tokens": sum(total_output) if total_output else None,
        "measurement_sources": sources,
        "aggregation_method": "benchmark_summary_rollup_v1",
        "measurement_status": "measured" if timed or output_measured else "not_reported_by_backend",
    }


def _metric_values(items: List[Dict[str, Any]], key: str) -> List[float]:
    values = []
    for item in items:
        value = item.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            values.append(float(value))
    return values


def _summary_metric_values(summary: Dict[str, Any], keys) -> List[float]:
    values = []
    for key in keys:
        value = summary.get(key)
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            values.append(float(value) * 1000.0 if key == "duration_seconds" else float(value))
    return values


def _percentile(values: List[float], percentile: float) -> Optional[float]:
    values = sorted(value for value in values if math.isfinite(value))
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 6)
    index = (len(values) - 1) * percentile
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return round(values[lower], 6)
    weight = index - lower
    return round(values[lower] * (1.0 - weight) + values[upper] * weight, 6)


def _variance(values: List[float]) -> Optional[float]:
    values = [value for value in values if math.isfinite(value)]
    if len(values) < 2:
        return None
    mean = sum(values) / float(len(values))
    return round(sum((value - mean) ** 2 for value in values) / float(len(values)), 6)


def _coefficient_of_variation(values: List[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    mean = sum(values) / float(len(values))
    if mean == 0:
        return None
    variance = _variance(values)
    return None if variance is None else math.sqrt(variance) / abs(mean)


def _instability_reasons(
    stats: Dict[str, Any],
    latency_values: List[float],
    ttft_values: List[float],
    tokens_per_second_values: List[float],
) -> List[str]:
    reasons = []
    if stats["failure_rate"] >= 0.2:
        reasons.append("failure_rate_high")
    for key, values, threshold in (
        ("latency", latency_values, 0.35),
        ("ttft", ttft_values, 0.50),
        ("tokens_per_second", tokens_per_second_values, 0.35),
    ):
        coefficient = _coefficient_of_variation(values)
        if coefficient is not None and coefficient > threshold:
            reasons.append("%s_variance_high" % key)
    if stats.get("capability_pass_rate_variance") is not None and stats["capability_pass_rate_variance"] > 0.20:
        reasons.append("capability_pass_rate_variance_high")
    return reasons


def _weighted_average(summaries: List[Dict[str, Any]], value_key: str, weight_key: str) -> Optional[float]:
    total = 0.0
    weight_total = 0.0
    for item in summaries:
        value = item.get(value_key)
        weight = item.get(weight_key)
        if isinstance(value, (int, float)) and isinstance(weight, int) and weight > 0:
            total += float(value) * float(weight)
            weight_total += float(weight)
    return None if weight_total == 0 else round(total / weight_total, 6)


def _median_of_summaries(summaries: List[Dict[str, Any]], key: str) -> Optional[float]:
    return _percentile([float(item[key]) for item in summaries if isinstance(item.get(key), (int, float))], 0.50)


def _max_summary_value(summaries: List[Dict[str, Any]], key: str) -> Optional[float]:
    values = [float(item[key]) for item in summaries if isinstance(item.get(key), (int, float))]
    return None if not values else round(max(values), 6)


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
