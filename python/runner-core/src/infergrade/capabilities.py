import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from infergrade import __version__
from infergrade.benchmark_catalog import (
    capability_benchmark_ids_for_request,
    resolve_request_selection,
    selection_metadata_for_request,
)
from infergrade.capability_contract import validate_capability_run_artifact
from infergrade.capability_summary import write_capability_summary_artifact
from infergrade.images import install_image
from infergrade.models import CapabilityExecution, FidelityExecution, RunRequest
from infergrade.utils import ensure_dir, env_value, read_json, stable_hash, utcnow_iso, write_json

CAPABILITY_REGISTRY_VERSION = "2026-04-multiturn-preview"
CODING_STATIC_REPAIR_FIXTURE_REVISION = "2026-05-coding-static-preview"
REASONING_EXACT_ANSWER_FIXTURE_REVISION = "2026-05-reasoning-exact-preview"
_DOMINANT_GENERATION_FAILURE_RATE = 0.5

DEFAULT_CAPABILITY_IMAGES = {
    "ifeval": env_value("INFERGRADE_IFEVAL_IMAGE", "QUANTBENCH_IFEVAL_IMAGE", "infergrade-ifeval:local"),
    "evalplus_humaneval": env_value("INFERGRADE_EVALPLUS_IMAGE", "QUANTBENCH_EVALPLUS_IMAGE", "infergrade-evalplus:local"),
    "evalplus_mbpp": env_value("INFERGRADE_EVALPLUS_IMAGE", "QUANTBENCH_EVALPLUS_IMAGE", "infergrade-evalplus:local"),
    "mmlu_pro_reference_v1": env_value("INFERGRADE_MMLU_PRO_IMAGE", "QUANTBENCH_MMLU_PRO_IMAGE", "infergrade-mmlu-pro:local"),
}

_LISTENER_RUNS_DIR = "/app/runs"


@dataclass(frozen=True)
class CapabilityBenchmarkSpec:
    benchmark_id: str
    display_name: str
    benchmark_kind: str
    primary_metric_name: str
    generation_max_tokens: int
    container_image: str = ""
    execution_mode: str = "container"
    container_args: List[str] = field(default_factory=list)
    case_limits: Dict[str, int] = field(default_factory=dict)


CAPABILITY_BENCHMARKS: Dict[str, CapabilityBenchmarkSpec] = {
    "ifeval": CapabilityBenchmarkSpec(
        benchmark_id="ifeval",
        display_name="IFEval",
        benchmark_kind="instruction_following",
        primary_metric_name="prompt_strict_accuracy",
        generation_max_tokens=640,
        container_image=DEFAULT_CAPABILITY_IMAGES["ifeval"],
        case_limits={"canary": 25, "standard": 100, "gold": 541},
    ),
    "evalplus_humaneval": CapabilityBenchmarkSpec(
        benchmark_id="evalplus_humaneval",
        display_name="EvalPlus HumanEval+",
        benchmark_kind="code_generation",
        primary_metric_name="pass_at_1_plus",
        generation_max_tokens=512,
        container_image=DEFAULT_CAPABILITY_IMAGES["evalplus_humaneval"],
        container_args=["--dataset", "humaneval"],
        case_limits={"canary": 20, "standard": 164, "gold": 164},
    ),
    "evalplus_mbpp": CapabilityBenchmarkSpec(
        benchmark_id="evalplus_mbpp",
        display_name="EvalPlus MBPP+",
        benchmark_kind="code_generation",
        primary_metric_name="pass_at_1_plus",
        generation_max_tokens=512,
        container_image=DEFAULT_CAPABILITY_IMAGES["evalplus_mbpp"],
        container_args=["--dataset", "mbpp"],
        case_limits={"canary": 25, "standard": 100, "gold": 378},
    ),
    "multiturn_chat_memory_v1": CapabilityBenchmarkSpec(
        benchmark_id="multiturn_chat_memory_v1",
        display_name="Multi-turn chat memory",
        benchmark_kind="multiturn_instruction_retention",
        primary_metric_name="constraint_retention_accuracy",
        generation_max_tokens=96,
        execution_mode="native",
        case_limits={"canary": 3, "standard": 5, "gold": 5},
    ),
    "coding_static_repair_v1": CapabilityBenchmarkSpec(
        benchmark_id="coding_static_repair_v1",
        display_name="Coding static repair",
        benchmark_kind="static_code_repair",
        primary_metric_name="static_constraint_accuracy",
        generation_max_tokens=256,
        execution_mode="native",
        case_limits={"canary": 2, "standard": 3, "gold": 3},
    ),
    "reasoning_exact_answer_v1": CapabilityBenchmarkSpec(
        benchmark_id="reasoning_exact_answer_v1",
        display_name="Reasoning exact answer",
        benchmark_kind="exact_reasoning",
        primary_metric_name="exact_answer_accuracy",
        generation_max_tokens=32,
        execution_mode="native",
        case_limits={"canary": 2, "standard": 3, "gold": 3},
    ),
    "mmlu_pro_reference_v1": CapabilityBenchmarkSpec(
        benchmark_id="mmlu_pro_reference_v1",
        display_name="MMLU-Pro reference",
        benchmark_kind="multiple_choice",
        primary_metric_name="accuracy",
        generation_max_tokens=64,
        container_image=DEFAULT_CAPABILITY_IMAGES["mmlu_pro_reference_v1"],
        case_limits={"canary": 25, "standard": 100, "gold": 300},
    ),
    "perplexity_reference_v1": CapabilityBenchmarkSpec(
        benchmark_id="perplexity_reference_v1",
        display_name="Quant fidelity reference",
        benchmark_kind="quant_fidelity",
        primary_metric_name="perplexity",
        generation_max_tokens=0,
        execution_mode="fidelity",
        case_limits={"canary": 1, "standard": 1, "gold": 1},
    ),
}


CAPABILITY_SUITES: Dict[str, Dict[str, tuple]] = {
    "agentic_coding": {
        "canary": ("coding_canary_v2", ["EvalPlus HumanEval+"]),
        "standard": ("coding_standard_v3", ["EvalPlus HumanEval+", "EvalPlus MBPP+"]),
        "gold": ("coding_gold_v2", ["EvalPlus HumanEval+", "EvalPlus MBPP+"]),
    },
    "general_assistant": {
        "canary": ("assistant_canary_v2", ["IFEval"]),
        "standard": ("assistant_standard_v3", ["IFEval", "Multi-turn chat memory"]),
        "gold": ("assistant_gold_v3", ["IFEval", "Multi-turn chat memory"]),
    },
}


SUITE_BENCHMARK_IDS: Dict[str, Dict[str, List[str]]] = {
    "agentic_coding": {
        "canary": ["evalplus_humaneval"],
        "standard": ["evalplus_humaneval", "evalplus_mbpp"],
        "gold": ["evalplus_humaneval", "evalplus_mbpp"],
    },
    "general_assistant": {
        "canary": ["ifeval"],
        "standard": ["ifeval", "multiturn_chat_memory_v1"],
        "gold": ["ifeval", "multiturn_chat_memory_v1"],
    },
}


def resolve_capability_suite(use_case: Optional[str], tier: str):
    if not use_case:
        return None
    use_case_suites = CAPABILITY_SUITES.get(use_case)
    if not use_case_suites or tier not in use_case_suites:
        return None
    suite_id, components = use_case_suites[tier]
    return {
        "use_case": use_case,
        "suite_id": suite_id,
        "benchmark_tier": tier,
        "components": components,
        "benchmark_ids": list(SUITE_BENCHMARK_IDS[use_case][tier]),
    }


def capability_registry_for_request(request: RunRequest) -> List[Dict[str, Any]]:
    benchmark_ids = capability_benchmark_ids_for_request(request)
    return _capability_registry_for_benchmark_ids(benchmark_ids)


def _capability_registry_for_benchmark_ids(benchmark_ids: List[str]) -> List[Dict[str, Any]]:
    registry: List[Dict[str, Any]] = []
    for benchmark_id in benchmark_ids:
        if benchmark_id not in CAPABILITY_BENCHMARKS:
            continue
        spec = CAPABILITY_BENCHMARKS[benchmark_id]
        registry.append(
            {
                "benchmark_id": benchmark_id,
                "display_name": spec.display_name,
                "benchmark_kind": spec.benchmark_kind,
                "primary_metric_name": spec.primary_metric_name,
                "generation_max_tokens": spec.generation_max_tokens,
            }
        )
    return registry


def summarize_capability_execution(
    request: RunRequest,
    execution: CapabilityExecution,
    completed_at: Optional[str] = None,
) -> Dict[str, Any]:
    selection = selection_metadata_for_request(request)
    planned_benchmark_ids = list(execution.benchmark_check_ids or capability_benchmark_ids_for_request(request))
    benchmark_registry = _capability_registry_for_benchmark_ids(planned_benchmark_ids)
    benchmark_results = dict(execution.benchmark_results or {})
    simulated_scored_ids = [
        benchmark_id for benchmark_id in planned_benchmark_ids if benchmark_id in dict(execution.component_scores or {})
    ]
    executed_benchmark_ids = [
        benchmark_id for benchmark_id in planned_benchmark_ids if benchmark_id in benchmark_results or benchmark_id in simulated_scored_ids
    ]
    scored_benchmark_ids = [
        benchmark_id
        for benchmark_id in executed_benchmark_ids
        if _benchmark_counts_as_scored(benchmark_results.get(benchmark_id) or {})
        or benchmark_id in simulated_scored_ids
    ]
    missing_benchmark_ids = [benchmark_id for benchmark_id in planned_benchmark_ids if benchmark_id not in scored_benchmark_ids]
    planned_count = len(planned_benchmark_ids)
    scored_count = len(scored_benchmark_ids)
    coverage_fraction = round(scored_count / float(planned_count), 4) if planned_count else 0.0
    coverage_state = "complete" if planned_count and scored_count == planned_count else ("partial" if scored_count else "missing")
    state = _capability_state_for_request(request, execution, None, scored_count)
    reason_codes = _capability_reason_codes(request, execution, None, scored_count, planned_count)
    component_reports = [
        _component_report_for_benchmark(request, benchmark_id, benchmark_results.get(benchmark_id), execution.component_scores)
        for benchmark_id in planned_benchmark_ids
    ]
    return {
        "use_case": execution.use_case or request.use_case,
        "capability_suite_id": execution.suite_id,
        "capability_suite_ids": list(execution.suite_ids or selection.get("capability_suite_ids") or []),
        "benchmark_tier": execution.benchmark_tier or request.tier,
        "benchmark_group_ids": list(execution.benchmark_group_ids or selection.get("benchmark_group_ids") or []),
        "benchmark_selection": selection,
        "selected_benchmark_check_ids": list(execution.benchmark_check_ids or selection.get("benchmark_check_ids") or []),
        "benchmark_components": list(execution.components or []),
        "benchmark_registry_version": CAPABILITY_REGISTRY_VERSION,
        "benchmark_registry": benchmark_registry,
        "benchmark_results": benchmark_results,
        "capability_score": execution.score,
        "capability_score_method": execution.score_method,
        "capability_component_scores": dict(execution.component_scores or {}),
        "capability_component_reports": component_reports,
        "capability_confidence": execution.confidence,
        "capability_artifacts": dict(execution.artifacts or {}),
        "capability_run_count": 1 if execution.status not in ("skipped", "failed") or scored_count else 0,
        "capability_timestamp": completed_at if execution.status not in ("skipped", "failed") else None,
        "capability_status": execution.status,
        "capability_state": state,
        "capability_reason_codes": reason_codes,
        "benchmark_coverage": {
            "planned_benchmark_ids": planned_benchmark_ids,
            "executed_benchmark_ids": executed_benchmark_ids,
            "scored_benchmark_ids": scored_benchmark_ids,
            "missing_benchmark_ids": missing_benchmark_ids,
            "planned_count": planned_count,
            "executed_count": len(executed_benchmark_ids),
            "scored_count": scored_count,
            "coverage_fraction": coverage_fraction,
            "coverage_state": coverage_state,
        },
    }


def capability_images_for_request(request: RunRequest) -> List[Dict[str, str]]:
    benchmark_ids = capability_benchmark_ids_for_request(request)
    if request.capability == "none" or not benchmark_ids:
        return []
    images = []
    for benchmark_id in benchmark_ids:
        spec = CAPABILITY_BENCHMARKS[benchmark_id]
        if spec.execution_mode != "container":
            continue
        images.append(
            {
                "benchmark_id": benchmark_id,
                "display_name": spec.display_name,
                "image": spec.container_image,
            }
        )
    return images


def _benchmark_primary_metric_value(summary: Dict[str, Any]) -> Optional[float]:
    primary_metric = (summary or {}).get("primary_metric") or {}
    value = primary_metric.get("value")
    try:
        return None if value is None else round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _benchmark_counts_as_scored(summary: Dict[str, Any]) -> bool:
    return _benchmark_primary_metric_value(summary) is not None and str((summary or {}).get("status") or "") not in {
        "failed",
        "degraded",
    }


def _component_report_for_benchmark(
    request: RunRequest,
    benchmark_id: str,
    benchmark_result: Optional[Dict[str, Any]],
    component_scores: Dict[str, float],
) -> Dict[str, Any]:
    spec = CAPABILITY_BENCHMARKS[benchmark_id]
    benchmark_result = dict(benchmark_result or {})
    total_cases = benchmark_result.get("total_cases")
    if total_cases is None:
        total_cases = spec.case_limits.get(request.tier)
    primary_metric_value = _benchmark_primary_metric_value(benchmark_result)
    component_score = component_scores.get(benchmark_id)
    if primary_metric_value is None and component_score is not None:
        primary_metric_value = component_score
    status = str(
        benchmark_result.get("status")
        or ("simulated" if benchmark_result == {} and component_score is not None else ("completed" if primary_metric_value is not None else "not_run"))
    )
    return {
        "benchmark_id": benchmark_id,
        "display_name": spec.display_name,
        "benchmark_kind": spec.benchmark_kind,
        "primary_metric_name": spec.primary_metric_name,
        "primary_metric_value": primary_metric_value,
        "component_score": component_score,
        "status": status,
        "completed_cases": benchmark_result.get("completed_cases"),
        "total_cases": total_cases,
        "generation_failure_count": benchmark_result.get("generation_failure_count"),
        "generation_failure_rate": benchmark_result.get("generation_failure_rate"),
        "generation_failure_severity": benchmark_result.get("generation_failure_severity"),
    }


def _capability_state_for_request(
    request: RunRequest,
    execution: CapabilityExecution,
    suite: Optional[Dict[str, Any]],
    scored_count: int,
) -> str:
    if not request.use_case and not execution.suite_ids:
        return "not_comparable"
    if request.capability == "none" or execution.status == "skipped":
        return "skipped"
    if execution.status == "failed":
        return "failed"
    if execution.status == "partial":
        return "partial"
    if execution.status in ("completed", "simulated") and execution.score is not None:
        return "scored"
    if scored_count:
        return "partial"
    return "not_yet_benchmarked"


def _capability_reason_codes(
    request: RunRequest,
    execution: CapabilityExecution,
    suite: Optional[Dict[str, Any]],
    scored_count: int,
    planned_count: int,
) -> List[str]:
    codes: List[str] = []
    benchmark_ids = _planned_benchmark_ids(execution, suite, request)
    if not request.use_case and not execution.suite_ids:
        codes.append("use_case_missing")
    if suite is None and request.use_case and not execution.suite_ids:
        codes.append("suite_unavailable_for_use_case")
    if request.capability == "none" or execution.status == "skipped":
        codes.append("capability_disabled")
    if execution.status == "simulated":
        codes.append("simulated_capability_signal")
    if execution.status in ("completed", "simulated") and execution.score is not None:
        codes.append("benchmark_suite_scored")
    if execution.status == "partial" or (planned_count and scored_count and scored_count < planned_count):
        codes.append("partial_coverage")
    if any(
        str((execution.benchmark_results or {}).get(benchmark_id, {}).get("status")) == "failed"
        for benchmark_id in benchmark_ids
    ):
        codes.append("benchmark_component_failed")
    if execution.status == "failed":
        codes.append("benchmark_execution_failed")
    if any(
        str((execution.benchmark_results or {}).get(benchmark_id, {}).get("generation_failure_severity")) == "dominant"
        for benchmark_id in benchmark_ids
    ):
        codes.append("generation_failures_dominant")
    if any(
        str((execution.benchmark_results or {}).get(benchmark_id, {}).get("generation_failure_severity")) == "all_failed"
        for benchmark_id in benchmark_ids
    ):
        codes.append("generation_failures_exhausted")
    if not codes and planned_count:
        codes.append("benchmark_not_yet_run")
    if not codes:
        codes.append("capability_not_comparable")
    return codes


def execute_capability_suite(
    adapter,
    request: RunRequest,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> CapabilityExecution:
    selection = resolve_request_selection(request)
    benchmark_ids = capability_benchmark_ids_for_request(request)
    suite_ids = list(selection.get("suite_ids") or [])
    group_ids = list(selection.get("group_ids") or [])
    primary_suite_id = suite_ids[0] if suite_ids else None
    if not benchmark_ids:
        return CapabilityExecution(
            use_case=request.use_case,
            suite_id=primary_suite_id,
            suite_ids=suite_ids,
            benchmark_tier=request.tier,
            benchmark_group_ids=group_ids,
            benchmark_check_ids=benchmark_ids,
            components=[],
            score=None,
            score_method=None,
            component_scores={},
            confidence=None,
            status="skipped",
            benchmark_results={},
            artifacts={},
        )

    benchmark_root = os.path.join(request.output_dir or os.path.join("runs", "infergrade_capability"), "artifacts", "capability")
    ensure_dir(benchmark_root)

    component_scores: Dict[str, float] = {}
    benchmark_results: Dict[str, Any] = {}
    benchmark_artifacts: Dict[str, Any] = {}
    completed = 0
    degraded = 0
    hard_failed = 0

    for benchmark_id in benchmark_ids:
        spec = CAPABILITY_BENCHMARKS[benchmark_id]
        benchmark_dir = os.path.join(benchmark_root, benchmark_id)
        ensure_dir(benchmark_dir)
        try:
            _prepare_benchmark_cases(spec, benchmark_dir, request.tier)
            cases = _read_jsonl(os.path.join(benchmark_dir, "cases.jsonl"))
            if progress_callback:
                progress_callback(
                    {
                        "event": "benchmark_started",
                        "benchmark_id": benchmark_id,
                        "display_name": spec.display_name,
                        "total_cases": len(cases),
                        "message": "Capability benchmark %s started (%d cases)." % (spec.display_name, len(cases)),
                    }
                )
            predictions = _generate_predictions(adapter, request, spec, cases, progress_callback=progress_callback)
            _write_jsonl(os.path.join(benchmark_dir, "predictions.jsonl"), predictions)
            summary = _evaluate_benchmark(spec, benchmark_dir)
            failure_count = len([item for item in predictions if item.get("generation_status") != "completed"])
            failure_severity = _generation_failure_severity(len(cases), failure_count)
            summary["generation_failure_count"] = failure_count
            summary["generation_failure_rate"] = round(failure_count / float(len(cases)), 4) if cases else 0.0
            summary["generation_failure_severity"] = failure_severity
            summary["completed_cases"] = len(cases) - failure_count
            summary["total_cases"] = len(cases)
            if failure_severity == "all_failed":
                summary["status"] = "failed"
                summary["error"] = (
                    "All generations failed before evaluation completed. "
                    "This usually indicates an incompatible backend/model combination or a runtime generation failure."
                )
                if isinstance(summary.get("primary_metric"), dict):
                    summary["primary_metric"]["value"] = None
            elif failure_severity == "dominant":
                summary["status"] = "degraded"
                summary["warning"] = (
                    "Most generations failed before evaluation completed. "
                    "Treat this capability benchmark as degraded rather than a healthy score."
                )
            elif failure_severity == "partial":
                summary["status"] = "partial"
                summary["warning"] = (
                    "Some generations failed before evaluation completed. "
                    "Treat this capability benchmark as partial rather than a complete score."
                )
            write_json(os.path.join(benchmark_dir, "summary.json"), summary)
            capability_run_path = None
            if spec.execution_mode == "native":
                capability_run_path = _write_native_capability_run_artifact(
                    request=request,
                    spec=spec,
                    benchmark_dir=benchmark_dir,
                    cases=cases,
                    predictions=predictions,
                    summary=summary,
                )
            elif spec.benchmark_id in {"evalplus_humaneval", "evalplus_mbpp"}:
                capability_run_path = _write_evalplus_capability_run_artifact(
                    request=request,
                    spec=spec,
                    benchmark_dir=benchmark_dir,
                    cases=cases,
                    predictions=predictions,
                    summary=summary,
                )
            elif spec.benchmark_id == "mmlu_pro_reference_v1":
                capability_run_path = _write_mmlu_pro_capability_run_artifact(
                    request=request,
                    spec=spec,
                    benchmark_dir=benchmark_dir,
                    cases=cases,
                    predictions=predictions,
                    summary=summary,
                )
            if progress_callback:
                progress_callback(
                    {
                        "event": "benchmark_completed",
                        "benchmark_id": benchmark_id,
                        "display_name": spec.display_name,
                        "total_cases": len(cases),
                        "completed_cases": len(cases) - failure_count,
                        "status": summary.get("status") or "completed",
                        "primary_metric": summary.get("primary_metric", {}).get("value"),
                        "error": summary.get("error") or summary.get("warning"),
                        "message": (
                            "Capability benchmark %s failed before evaluation produced a trustworthy score."
                            if summary.get("status") == "failed"
                            else (
                                "Capability benchmark %s completed with degraded generation quality."
                                if summary.get("status") == "degraded"
                                else "Capability benchmark %s completed."
                            )
                        ) % spec.display_name,
                    }
                )
            benchmark_results[benchmark_id] = summary
            benchmark_artifacts[benchmark_id] = {
                "benchmark_dir": benchmark_dir,
                "cases_path": os.path.join(benchmark_dir, "cases.jsonl"),
                "predictions_path": os.path.join(benchmark_dir, "predictions.jsonl"),
                "summary_path": os.path.join(benchmark_dir, "summary.json"),
            }
            if capability_run_path:
                benchmark_artifacts[benchmark_id]["capability_run_path"] = capability_run_path
            primary_value = summary.get("primary_metric", {}).get("value")
            summary_status = str(summary.get("status") or "")
            if primary_value is not None and failure_severity == "none" and summary_status == "completed":
                component_scores[benchmark_id] = round(float(primary_value), 6)
                completed += 1
            elif failure_severity in {"dominant", "partial"} or summary_status in {"degraded", "partial"}:
                degraded += 1
            elif failure_severity == "all_failed":
                hard_failed += 1
        except Exception as exc:
            failure_summary = {
                "benchmark_id": benchmark_id,
                "display_name": spec.display_name,
                "status": "failed",
                "error": str(exc),
                "primary_metric": {
                    "name": spec.primary_metric_name,
                    "value": None,
                },
            }
            summary_path = os.path.join(benchmark_dir, "summary.json")
            write_json(summary_path, failure_summary)
            if progress_callback:
                progress_callback(
                    {
                        "event": "benchmark_completed",
                        "benchmark_id": benchmark_id,
                        "display_name": spec.display_name,
                        "status": "failed",
                        "message": "Capability benchmark %s failed." % spec.display_name,
                        "error": str(exc),
                    }
                )
            benchmark_results[benchmark_id] = failure_summary
            benchmark_artifacts[benchmark_id] = {
                "benchmark_dir": benchmark_dir,
                "summary_path": summary_path,
            }

    status = "failed"
    if completed == len(benchmark_ids):
        status = "completed"
    elif completed > 0 or degraded > 0:
        status = "partial"
    elif hard_failed == len(benchmark_ids):
        status = "failed"

    score = None
    if component_scores:
        score = round(sum(component_scores.values()) / float(len(component_scores)), 6)

    confidence = None
    if status == "completed":
        confidence = 0.9
    elif status == "partial":
        confidence = 0.6

    execution = CapabilityExecution(
        use_case=request.use_case,
        suite_id=primary_suite_id,
        suite_ids=suite_ids,
        benchmark_tier=request.tier,
        benchmark_group_ids=group_ids,
        benchmark_check_ids=benchmark_ids,
        components=[CAPABILITY_BENCHMARKS[item].display_name for item in benchmark_ids],
        score=score,
        score_method="mean_primary_metric_v1",
        component_scores=component_scores,
        confidence=confidence,
        status=status,
        benchmark_results=benchmark_results,
        artifacts=benchmark_artifacts,
    )
    summary_path = write_capability_summary_artifact(request, execution, request.output_dir or os.path.dirname(os.path.dirname(benchmark_root)))
    execution.artifacts["_summary"] = {"capability_summary_path": summary_path}
    return execution


def attach_quant_fidelity_capability_artifact(
    request: RunRequest,
    execution: CapabilityExecution,
    fidelity: FidelityExecution,
    output_dir: str,
    ontology: Dict[str, Any],
    environment: Dict[str, Any],
    runtime_metadata: Dict[str, Any],
    backend_version: str,
) -> Optional[str]:
    """Write the selected quant-fidelity reference artifact and refresh summary discovery."""
    if "perplexity_reference_v1" not in list(request.benchmark_check_ids or []):
        return None
    benchmark_dir = os.path.join(output_dir, "artifacts", "capability", "perplexity_reference_v1")
    ensure_dir(benchmark_dir)
    raw_path = os.path.join(benchmark_dir, "fidelity_raw.json")
    scoring_path = os.path.join(benchmark_dir, "summary.json")
    final_comparability_key = _quant_fidelity_comparability_key(
        ontology=ontology,
        request=request,
        corpus_id=_quant_fidelity_metric_or_context(fidelity, "corpus_id"),
        corpus_revision=_quant_fidelity_metric_or_context(fidelity, "corpus_revision"),
        protocol_id=_quant_fidelity_metric_or_context(fidelity, "protocol_id"),
        protocol_parameters=_quant_fidelity_metric_or_context(fidelity, "protocol_parameters"),
    )
    _finalize_quant_fidelity_metrics(fidelity, final_comparability_key)
    write_json(
        raw_path,
        {
            "state": fidelity.state,
            "reason_codes": list(fidelity.reason_codes or []),
            "context": dict(fidelity.context or {}),
            "metrics": dict(fidelity.metrics or {}),
            "artifacts": dict(fidelity.artifacts or {}),
        },
    )
    summary_payload = _quant_fidelity_summary_payload(fidelity)
    summary_payload["comparability_key"] = final_comparability_key
    write_json(scoring_path, summary_payload)
    capability_run_path = _write_quant_fidelity_capability_run_artifact(
        request=request,
        fidelity=fidelity,
        summary=summary_payload,
        benchmark_dir=benchmark_dir,
        ontology=ontology,
        environment=environment,
        runtime_metadata=runtime_metadata,
        backend_version=backend_version,
    )
    execution.artifacts["perplexity_reference_v1"] = {
        "benchmark_dir": benchmark_dir,
        "summary_path": scoring_path,
        "raw_path": raw_path,
        "capability_run_path": capability_run_path,
    }
    execution.benchmark_results["perplexity_reference_v1"] = summary_payload
    if "perplexity_reference_v1" not in list(execution.benchmark_check_ids or []):
        execution.benchmark_check_ids = list(execution.benchmark_check_ids or []) + ["perplexity_reference_v1"]
    summary_path = write_capability_summary_artifact(request, execution, output_dir)
    execution.artifacts["_summary"] = {"capability_summary_path": summary_path}
    return capability_run_path


def _quant_fidelity_metric_or_context(fidelity: FidelityExecution, key: str) -> Any:
    metric = dict((fidelity.metrics or {}).get("perplexity") or {})
    if metric.get(key) is not None:
        return metric.get(key)
    return dict(fidelity.context or {}).get(key)


def _finalize_quant_fidelity_metrics(fidelity: FidelityExecution, comparability_key: str) -> None:
    metrics = fidelity.metrics or {}
    metric = metrics.get("perplexity")
    if isinstance(metric, dict):
        metric["comparability_key"] = comparability_key


def _quant_fidelity_summary_payload(fidelity: FidelityExecution) -> Dict[str, Any]:
    metric = dict((fidelity.metrics or {}).get("perplexity") or {})
    measured = fidelity.state == "measured" and metric.get("value") is not None
    if measured:
        state = "scored"
    elif fidelity.state == "skipped":
        state = "skipped"
    elif fidelity.state == "not_comparable":
        state = "not_comparable"
    elif "simulated_run_skips_fidelity" in list(fidelity.reason_codes or []):
        state = "not_comparable"
    else:
        state = "failed"
    return {
        "benchmark_id": "perplexity_reference_v1",
        "display_name": "Quant fidelity reference",
        "status": "completed" if measured else fidelity.state,
        "state": state,
        "primary_metric": {
            "name": "perplexity",
            "value": metric.get("value") if measured else None,
            "lower_is_better": True,
        },
        "metrics": {
            "perplexity": metric.get("value"),
            "stderr": metric.get("stderr"),
            "bits_per_byte": metric.get("bits_per_byte"),
            "tokens_scored": metric.get("corpus_token_count"),
            "bytes_scored": metric.get("corpus_byte_count"),
            "duration_seconds": metric.get("duration_seconds"),
        },
        "reason_codes": list(fidelity.reason_codes or []),
        "comparability_key": metric.get("comparability_key"),
        "corpus_id": metric.get("corpus_id") or (fidelity.context or {}).get("corpus_id"),
        "corpus_revision": metric.get("corpus_revision") or (fidelity.context or {}).get("corpus_revision"),
        "protocol_id": metric.get("protocol_id") or (fidelity.context or {}).get("protocol_id"),
        "protocol_parameters": metric.get("protocol_parameters") or (fidelity.context or {}).get("protocol_parameters"),
        "claim_boundary": (
            "Same-family quant-fidelity reference evidence only; not a cross-model score or general capability measure."
        ),
    }


def _write_quant_fidelity_capability_run_artifact(
    request: RunRequest,
    fidelity: FidelityExecution,
    summary: Dict[str, Any],
    benchmark_dir: str,
    ontology: Dict[str, Any],
    environment: Dict[str, Any],
    runtime_metadata: Dict[str, Any],
    backend_version: str,
) -> str:
    metric = dict((fidelity.metrics or {}).get("perplexity") or {})
    context = dict(fidelity.context or {})
    measured = summary.get("state") == "scored"
    error_class = None if measured else _quant_fidelity_error_class(fidelity)
    task_state = "scored" if measured else str(summary.get("state") or "failed")
    failed_count = 1 if task_state == "failed" else 0
    skipped_count = 1 if task_state == "skipped" else 0
    not_comparable_count = 1 if task_state == "not_comparable" else 0
    comparability_key = str(summary.get("comparability_key") or _quant_fidelity_comparability_key(
        ontology=ontology,
        request=request,
        corpus_id=summary.get("corpus_id"),
        corpus_revision=summary.get("corpus_revision"),
        protocol_id=summary.get("protocol_id"),
        protocol_parameters=summary.get("protocol_parameters"),
    ))
    protocol_parameters = dict(summary.get("protocol_parameters") or {})
    artifact = {
        "artifact_spec_version": "0.1.0",
        "artifact_kind": "capability_run",
        "capability_run_id": "caprun_perplexity_reference_v1_%s" % stable_hash(
            {
                "model": request.model,
                "artifact": request.quant_artifact_sha256 or request.quant_artifact,
                "metric": metric.get("value"),
                "comparability_key": comparability_key,
                "state": summary.get("state"),
            },
            length=10,
        ),
        "created_at": utcnow_iso(),
        "runner": {
            "name": "infergrade-runner",
            "version": __version__,
            "contract_version": "0.1.0",
        },
        "evidence": {
            "lane": "reference",
            "surface": "quant_fidelity",
            "grade": "sampled_reference",
            "experimental": True,
            "confidence_label": "sampled_reference",
        },
        "subject": {
            "model": {
                "model": request.model,
                "model_family": dict(ontology.get("model_family") or {}),
                "checkpoint": dict(ontology.get("checkpoint") or {}),
                "quantization": dict(ontology.get("quantization") or {}),
                "artifact": dict(ontology.get("artifact") or {}),
                "quant_artifact": request.quant_artifact,
                "quant_artifact_sha256": request.quant_artifact_sha256,
                "quant_artifact_filename": request.quant_artifact_filename,
                "tokenizer_id": _quant_fidelity_tokenizer_id(request, ontology),
                "comparability_key": comparability_key,
            },
            "runtime": {
                "backend": request.backend,
                "backend_version": backend_version,
                "execution_mode": request.execution_mode,
                "runtime_metadata": dict(runtime_metadata or {}),
            },
            "hardware": {
                "source": "run_bundle_environment",
                "snapshot": dict(environment or {}),
            },
            "generation_preset": {
                "generation_preset_id": request.generation_preset,
            },
        },
        "protocol": {
            "task_family": "quant_fidelity",
            "prompt_version": None,
            "task_version": "perplexity_reference_v1",
            "fixture_revision": str(summary.get("corpus_revision") or context.get("corpus_revision") or "unknown"),
            "dataset_revision": str(summary.get("corpus_revision") or context.get("corpus_revision") or "unknown"),
            "corpus": {
                "id": summary.get("corpus_id") or context.get("corpus_id"),
                "revision": summary.get("corpus_revision") or context.get("corpus_revision"),
            },
            "protocol_id": summary.get("protocol_id") or context.get("protocol_id"),
            "parameters": protocol_parameters,
            "scorer_type": "perplexity",
            "scoring_policy": "quant_fidelity_perplexity_v1",
            "repetitions": 1,
        },
        "summary": {
            "state": summary.get("state"),
            "score": metric.get("value") if measured else None,
            "score_dimension": "quant_fidelity_perplexity",
            "passed_count": 1 if measured else 0,
            "failed_count": failed_count,
            "partial_count": 0,
            "skipped_count": skipped_count,
            "not_comparable_count": not_comparable_count,
            "duration_seconds": metric.get("duration_seconds"),
            "time_to_first_token_ms": None,
            "tokens_per_second": None,
            "input_tokens": metric.get("corpus_token_count"),
            "output_tokens": None,
            "primary_metric": summary.get("primary_metric"),
            "metrics": summary.get("metrics"),
            "comparability_key": comparability_key,
            "lower_is_better": True,
        },
        "tasks": [
            {
                "task_id": "perplexity_reference_v1",
                "task_family": "quant_fidelity",
                "state": task_state,
                "score": metric.get("value") if measured else None,
                "score_dimension": "quant_fidelity_perplexity",
                "scorer_type": "perplexity" if measured else None,
                "scoring_policy": "quant_fidelity_perplexity_v1" if measured else None,
                "output_artifact": "fidelity_raw.json",
                "error_class": error_class,
                "latency_ms": None,
                "time_to_first_token_ms": None,
                "tokens_per_second": None,
                "input_tokens": metric.get("corpus_token_count"),
                "output_tokens": None,
                "metrics": summary.get("metrics"),
            }
        ],
        "artifacts": {
            "manifest": "capability_run.json",
            "raw_outputs": ["fidelity_raw.json"],
            "scoring_outputs": ["summary.json"],
            "supporting_files": [],
        },
        "claim_boundary": {
            "supported_claims": [
                "This quant artifact produced the recorded perplexity on the pinned corpus and protocol.",
                "Runs are directly comparable only when the same-family comparability key matches.",
            ],
            "unsupported_claims": [
                "This is not a global model-quality score.",
                "This is not assistant, coding, reasoning, LiveCodeBench, SWE-bench, or repo-edit proof.",
                "This is not gold evidence.",
                "This is not leaderboard-grade evidence.",
                "This must not be compared across different model families, checkpoints, tokenizers, corpora, or protocols.",
            ],
        },
    }
    errors = validate_capability_run_artifact(artifact)
    if errors:
        raise ValueError("Invalid capability_run artifact: %s" % "; ".join(errors))
    path = os.path.join(benchmark_dir, "capability_run.json")
    write_json(path, artifact)
    return path


def _quant_fidelity_tokenizer_id(request: RunRequest, ontology: Dict[str, Any]) -> str:
    hints = dict(request.ontology_hints or {})
    if hints.get("tokenizer_id"):
        return str(hints["tokenizer_id"])
    checkpoint = dict(ontology.get("checkpoint") or {})
    checkpoint_name = checkpoint.get("checkpoint_name") or request.model.split("/")[-1]
    return "%s_default" % re.sub(r"[^a-z0-9]+", "_", str(checkpoint_name).lower()).strip("_")


def _quant_fidelity_comparability_key(
    ontology: Dict[str, Any],
    request: RunRequest,
    corpus_id: Any,
    corpus_revision: Any,
    protocol_id: Any,
    protocol_parameters: Any,
) -> str:
    family = dict(ontology.get("model_family") or {})
    checkpoint = dict(ontology.get("checkpoint") or {})
    return stable_hash(
        {
            "family_name": family.get("family_name"),
            "checkpoint_name": checkpoint.get("checkpoint_name"),
            "tokenizer_id": _quant_fidelity_tokenizer_id(request, ontology),
            "corpus_id": corpus_id,
            "corpus_revision": corpus_revision,
            "protocol_id": protocol_id,
            "protocol_parameters": protocol_parameters,
        },
        length=24,
    )


def _quant_fidelity_error_class(fidelity: FidelityExecution) -> str:
    codes = [str(code) for code in list(fidelity.reason_codes or [])]
    if "fidelity_check_not_selected" in codes:
        return "skipped"
    if "execution_mode_not_supported_for_fidelity" in codes:
        return "protocol_mismatch"
    if "simulated_run_skips_fidelity" in codes:
        return "not_comparable"
    if "perplexity_measurement_failed" in codes:
        return "runtime_failure"
    return codes[0] if codes else "scoring_failed"


def _generation_failure_severity(total_cases: int, failure_count: int) -> str:
    if total_cases <= 0 or failure_count <= 0:
        return "none"
    if failure_count >= total_cases:
        return "all_failed"
    if (failure_count / float(total_cases)) >= _DOMINANT_GENERATION_FAILURE_RATE:
        return "dominant"
    return "partial"


def _write_native_capability_run_artifact(
    request: RunRequest,
    spec: CapabilityBenchmarkSpec,
    benchmark_dir: str,
    cases: List[Dict[str, Any]],
    predictions: List[Dict[str, Any]],
    summary: Dict[str, Any],
) -> str:
    check_metadata = _selected_check_metadata(request, spec.benchmark_id)
    primary_metric = dict(summary.get("primary_metric") or {})
    score = primary_metric.get("value")
    summary_state = _capability_artifact_state(summary.get("status"), score, summary.get("generation_failure_severity"))
    task_scores = {
        str(item.get("case_id") or ""): item
        for item in list(summary.get("case_results") or [])
    }
    tasks = []
    for prediction in predictions:
        case_id = str(prediction.get("case_id") or "")
        case = _case_by_id(cases, case_id)
        case_score = task_scores.get(case_id, {})
        generation_status = str(prediction.get("generation_status") or "")
        task_error_class = _native_task_error_class(generation_status, case_score)
        task_state = "failed" if task_error_class else ("scored" if case_score.get("score") is not None else "failed")
        tasks.append(
            {
                "task_id": str(case.get("task_id") or case_id),
                "task_family": spec.benchmark_kind,
                "state": task_state,
                "score": case_score.get("score") if task_state == "scored" else None,
                "score_dimension": check_metadata.get("score_dimension") or spec.benchmark_kind,
                "scorer_type": _native_scorer_type(spec) if task_state == "scored" else None,
                "scoring_policy": summary.get("scoring_policy") if task_state == "scored" else None,
                "output_artifact": "predictions.jsonl#%s" % case_id,
                "error_class": None if task_state == "scored" else (task_error_class or "scoring_failed"),
                "latency_ms": None,
                "time_to_first_token_ms": None,
                "tokens_per_second": None,
                "input_tokens": None,
                "output_tokens": None,
            }
        )
    artifact = {
        "artifact_spec_version": "0.1.0",
        "artifact_kind": "capability_run",
        "capability_run_id": "caprun_%s_%s" % (
            spec.benchmark_id,
            stable_hash(
                {
                    "model": request.model,
                    "benchmark_id": spec.benchmark_id,
                    "summary": summary,
                },
                length=10,
            ),
        ),
        "created_at": utcnow_iso(),
        "runner": {
            "name": "infergrade-runner",
            "version": __version__,
            "contract_version": "0.1.0",
        },
        "evidence": {
            "lane": check_metadata.get("evidence_lane_id") or "decision",
            "surface": check_metadata.get("surface_id") or "local_assistant_capability",
            "grade": "thin_local_sample",
            "experimental": True,
            "confidence_label": "thin_local_sample",
        },
        "subject": {
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
            "generation_preset": {
                "generation_preset_id": request.generation_preset,
                "max_tokens": spec.generation_max_tokens,
            },
        },
        "protocol": {
            "task_family": spec.benchmark_kind,
            "prompt_version": spec.benchmark_id,
            "task_version": spec.benchmark_id,
            "fixture_revision": _native_fixture_revision(spec),
            "dataset_revision": None,
            "scorer_type": _native_scorer_type(spec),
            "scoring_policy": summary.get("scoring_policy") or _native_scoring_policy(spec),
            "repetitions": 1,
        },
        "summary": {
            "state": summary_state,
            "score": score if summary_state in ("scored", "partial") else None,
            "score_dimension": check_metadata.get("score_dimension") or spec.benchmark_kind,
            "passed_count": summary.get("metrics", {}).get("passed_constraints"),
            "failed_count": summary.get("generation_failure_count"),
            "partial_count": summary.get("metrics", {}).get("malformed_output_count", 0),
            "skipped_count": 0,
            "not_comparable_count": 0,
            "duration_seconds": None,
            "time_to_first_token_ms": None,
            "tokens_per_second": None,
            "input_tokens": None,
            "output_tokens": None,
        },
        "tasks": tasks,
        "artifacts": {
            "manifest": "capability_run.json",
            "raw_outputs": ["predictions.jsonl"],
            "scoring_outputs": ["summary.json"],
            "supporting_files": ["cases.jsonl"],
        },
        "claim_boundary": _native_artifact_claim_boundary(spec, summary_state),
    }
    errors = validate_capability_run_artifact(artifact)
    if errors:
        raise ValueError("Invalid capability_run artifact: %s" % "; ".join(errors))
    path = os.path.join(benchmark_dir, "capability_run.json")
    write_json(path, artifact)
    return path


def _native_task_error_class(generation_status: str, case_score: Dict[str, Any]) -> Optional[str]:
    if generation_status != "completed":
        return "generation_failed"
    if str(case_score.get("state") or "") == "failed":
        return str(case_score.get("error_class") or "scoring_failed")
    return None


def _write_mmlu_pro_capability_run_artifact(
    request: RunRequest,
    spec: CapabilityBenchmarkSpec,
    benchmark_dir: str,
    cases: List[Dict[str, Any]],
    predictions: List[Dict[str, Any]],
    summary: Dict[str, Any],
) -> str:
    check_metadata = _selected_check_metadata(request, spec.benchmark_id)
    primary_metric = dict(summary.get("primary_metric") or {})
    score = primary_metric.get("value")
    summary_state = _capability_artifact_state(summary.get("status"), score, summary.get("generation_failure_severity"))
    case_results = {
        str(item.get("task_id") or item.get("case_id") or ""): dict(item)
        for item in list(summary.get("case_results") or [])
    }
    metadata = _read_optional_json(os.path.join(benchmark_dir, "benchmark_metadata.json"))
    tasks = []
    for prediction in predictions:
        task_id = str(prediction.get("task_id") or prediction.get("case_id") or "")
        case = _case_by_task_id(cases, task_id)
        result = case_results.get(task_id, {})
        generation_status = str(prediction.get("generation_status") or "")
        predicted = result.get("predicted")
        if generation_status != "completed":
            task_state = "failed"
            task_score = None
            error_class = "generation_failed"
        elif predicted is None:
            task_state = "failed"
            task_score = None
            error_class = "malformed_output"
        else:
            task_state = "scored"
            task_score = 1.0 if result.get("correct") else 0.0
            error_class = None
        tasks.append(
            {
                "task_id": task_id or str(case.get("task_id") or ""),
                "task_family": spec.benchmark_kind,
                "state": task_state,
                "score": task_score,
                "score_dimension": check_metadata.get("score_dimension") or spec.benchmark_kind,
                "scorer_type": "multiple_choice" if task_state == "scored" else None,
                "scoring_policy": summary.get("scoring_policy") if task_state == "scored" else None,
                "output_artifact": "predictions.jsonl#%s" % (task_id or str(case.get("case_id") or "")),
                "error_class": error_class,
                "latency_ms": None,
                "time_to_first_token_ms": None,
                "tokens_per_second": None,
                "input_tokens": None,
                "output_tokens": None,
                "category": result.get("category") or case.get("category"),
                "expected": result.get("expected") or case.get("answer"),
                "predicted": predicted,
            }
        )
    metrics = dict(summary.get("metrics") or {})
    artifact = {
        "artifact_spec_version": "0.1.0",
        "artifact_kind": "capability_run",
        "capability_run_id": "caprun_%s_%s" % (
            spec.benchmark_id,
            stable_hash(
                {
                    "model": request.model,
                    "benchmark_id": spec.benchmark_id,
                    "dataset_revision": metadata.get("dataset_revision"),
                    "summary": summary,
                },
                length=10,
            ),
        ),
        "created_at": utcnow_iso(),
        "runner": {
            "name": "infergrade-runner",
            "version": __version__,
            "contract_version": "0.1.0",
        },
        "evidence": {
            "lane": "reference",
            "surface": check_metadata.get("surface_id") or "local_reasoning_capability",
            "grade": "sampled_reference",
            "experimental": True,
            "confidence_label": "sampled_reference",
        },
        "subject": {
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
            "generation_preset": {
                "generation_preset_id": request.generation_preset,
                "max_tokens": spec.generation_max_tokens,
            },
        },
        "protocol": {
            "task_family": spec.benchmark_kind,
            "prompt_version": "mmlu_pro_reference_v1_prompt_v1",
            "task_version": spec.benchmark_id,
            "fixture_revision": str(metadata.get("sample_policy") or "mmlu_pro_snapshot"),
            "dataset_revision": metadata.get("dataset_revision"),
            "scorer_type": "multiple_choice",
            "scoring_policy": summary.get("scoring_policy") or "exact_multiple_choice_letter_accuracy_v1",
            "repetitions": 1,
            "sample_policy": metadata.get("sample_policy"),
            "category_count": metadata.get("category_count"),
        },
        "summary": {
            "state": summary_state,
            "score": score if summary_state in ("scored", "partial") else None,
            "score_dimension": check_metadata.get("score_dimension") or spec.benchmark_kind,
            "passed_count": metrics.get("correct_count"),
            "failed_count": metrics.get("invalid_count"),
            "partial_count": summary.get("generation_failure_count") or 0,
            "skipped_count": 0,
            "not_comparable_count": 0,
            "duration_seconds": None,
            "time_to_first_token_ms": None,
            "tokens_per_second": None,
            "input_tokens": None,
            "output_tokens": None,
            "category_metrics": dict(summary.get("category_metrics") or {}),
        },
        "tasks": tasks,
        "artifacts": {
            "manifest": "capability_run.json",
            "raw_outputs": ["predictions.jsonl"],
            "scoring_outputs": ["summary.json"],
            "supporting_files": ["cases.jsonl", "benchmark_metadata.json"],
        },
        "claim_boundary": _mmlu_pro_artifact_claim_boundary(summary_state),
    }
    errors = validate_capability_run_artifact(artifact)
    if errors:
        raise ValueError("Invalid capability_run artifact: %s" % "; ".join(errors))
    path = os.path.join(benchmark_dir, "capability_run.json")
    write_json(path, artifact)
    return path


def _write_evalplus_capability_run_artifact(
    request: RunRequest,
    spec: CapabilityBenchmarkSpec,
    benchmark_dir: str,
    cases: List[Dict[str, Any]],
    predictions: List[Dict[str, Any]],
    summary: Dict[str, Any],
) -> str:
    check_metadata = _selected_check_metadata(request, spec.benchmark_id)
    primary_metric = dict(summary.get("primary_metric") or {})
    score = primary_metric.get("value")
    summary_state = _capability_artifact_state(summary.get("status"), score, summary.get("generation_failure_severity"))
    case_results = {
        str(item.get("task_id") or item.get("case_id") or ""): dict(item)
        for item in list(summary.get("case_results") or [])
    }
    metadata = _read_optional_json(os.path.join(benchmark_dir, "benchmark_metadata.json"))
    tasks = []
    for prediction in predictions:
        task_id = str(prediction.get("task_id") or prediction.get("case_id") or "")
        case = _case_by_task_id(cases, task_id)
        result = case_results.get(task_id, {})
        generation_status = str(prediction.get("generation_status") or "")
        completion = str(prediction.get("completion") or "")
        if generation_status != "completed":
            task_state = "failed"
            task_score = None
            error_class = "generation_failed"
            scorer_type = None
            scoring_policy = None
        elif not completion.strip():
            task_state = "failed"
            task_score = None
            error_class = "malformed_output"
            scorer_type = None
            scoring_policy = None
        else:
            failure_class = str(result.get("failure_class") or "")
            passed = bool(result.get("passed"))
            task_state = "scored" if failure_class in {"", "test_failed"} else "failed"
            task_score = (1.0 if passed else 0.0) if task_state == "scored" else None
            error_class = "test_failed" if task_state == "scored" and not passed else (None if task_state == "scored" else failure_class)
            scorer_type = "unit_test" if task_state == "scored" else None
            scoring_policy = (
                summary.get("scoring_policy") or "evalplus_pass_at_1_base_plus_v1"
            ) if task_state == "scored" else None
        tasks.append(
            {
                "task_id": task_id or str(case.get("task_id") or ""),
                "task_family": spec.benchmark_kind,
                "state": task_state,
                "score": task_score,
                "score_dimension": check_metadata.get("score_dimension") or spec.benchmark_kind,
                "scorer_type": scorer_type,
                "scoring_policy": scoring_policy,
                "output_artifact": "predictions.jsonl#%s" % (task_id or str(case.get("case_id") or "")),
                "error_class": error_class,
                "latency_ms": None,
                "time_to_first_token_ms": None,
                "tokens_per_second": None,
                "input_tokens": None,
                "output_tokens": None,
                "entry_point": case.get("entry_point"),
                "dataset": metadata.get("dataset") or summary.get("dataset"),
                "base_passed": result.get("base_passed"),
                "plus_passed": result.get("plus_passed"),
                "test_failure_class": result.get("failure_class") if task_state == "scored" and task_score == 0.0 else None,
            }
        )
    metrics = dict(summary.get("metrics") or {})
    artifact = {
        "artifact_spec_version": "0.1.0",
        "artifact_kind": "capability_run",
        "capability_run_id": "caprun_%s_%s" % (
            spec.benchmark_id,
            stable_hash(
                {
                    "model": request.model,
                    "benchmark_id": spec.benchmark_id,
                    "evalplus_revision": metadata.get("evalplus_revision") or summary.get("evalplus_revision"),
                    "summary": summary,
                },
                length=10,
            ),
        ),
        "created_at": utcnow_iso(),
        "runner": {
            "name": "infergrade-runner",
            "version": __version__,
            "contract_version": "0.1.0",
        },
        "evidence": {
            "lane": check_metadata.get("evidence_lane_id") or "reference",
            "surface": check_metadata.get("surface_id") or "local_coding_capability",
            "grade": "sampled_reference",
            "experimental": True,
            "confidence_label": "sampled_reference",
        },
        "subject": {
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
                "container_image": spec.container_image,
            },
            "hardware": {
                "source": "run_bundle_environment",
            },
            "generation_preset": {
                "generation_preset_id": request.generation_preset,
                "max_tokens": spec.generation_max_tokens,
            },
        },
        "protocol": {
            "task_family": spec.benchmark_kind,
            "prompt_version": "%s_prompt_v1" % spec.benchmark_id,
            "task_version": spec.benchmark_id,
            "fixture_revision": str(
                metadata.get("sample_policy")
                or summary.get("sample_policy")
                or "%s_evalplus_revision" % (metadata.get("dataset") or summary.get("dataset") or "evalplus")
            ),
            "dataset_revision": metadata.get("evalplus_revision") or summary.get("evalplus_revision"),
            "scorer_type": "unit_test",
            "scoring_policy": summary.get("scoring_policy") or "evalplus_pass_at_1_base_plus_v1",
            "repetitions": 1,
            "sample_policy": metadata.get("sample_policy") or summary.get("sample_policy"),
            "case_count": metadata.get("case_count") or summary.get("case_count"),
            "dataset": metadata.get("dataset") or summary.get("dataset"),
        },
        "summary": {
            "state": summary_state,
            "score": score if summary_state in ("scored", "partial") else None,
            "score_dimension": check_metadata.get("score_dimension") or spec.benchmark_kind,
            "passed_count": metrics.get("passed_count"),
            "failed_count": metrics.get("failed_count"),
            "partial_count": summary.get("generation_failure_count") or 0,
            "skipped_count": 0,
            "not_comparable_count": 0,
            "duration_seconds": None,
            "time_to_first_token_ms": None,
            "tokens_per_second": None,
            "input_tokens": None,
            "output_tokens": None,
            "pass_at_1_base": metrics.get("pass_at_1_base"),
            "pass_at_1_plus": metrics.get("pass_at_1_plus"),
        },
        "tasks": tasks,
        "artifacts": {
            "manifest": "capability_run.json",
            "raw_outputs": ["predictions.jsonl", "samples.jsonl"],
            "scoring_outputs": ["summary.json", "eval_results.json"],
            "supporting_files": [
                "cases.jsonl",
                "benchmark_metadata.json",
                "%s_override.jsonl" % (metadata.get("dataset") or summary.get("dataset") or "evalplus"),
            ],
        },
        "claim_boundary": _evalplus_artifact_claim_boundary(spec.benchmark_id, summary_state),
    }
    errors = validate_capability_run_artifact(artifact)
    if errors:
        raise ValueError("Invalid capability_run artifact: %s" % "; ".join(errors))
    path = os.path.join(benchmark_dir, "capability_run.json")
    write_json(path, artifact)
    return path


def _native_scorer_type(spec: CapabilityBenchmarkSpec) -> str:
    if spec.benchmark_id == "multiturn_chat_memory_v1":
        return "exact_match"
    if spec.benchmark_id == "coding_static_repair_v1":
        return "static_check"
    if spec.benchmark_id == "reasoning_exact_answer_v1":
        return "exact_match"
    raise ValueError("Unsupported native capability benchmark: %s" % spec.benchmark_id)


def _native_scoring_policy(spec: CapabilityBenchmarkSpec) -> str:
    if spec.benchmark_id == "multiturn_chat_memory_v1":
        return "deterministic_required_phrase_match_v1"
    if spec.benchmark_id == "coding_static_repair_v1":
        return "deterministic_static_code_constraints_v1"
    if spec.benchmark_id == "reasoning_exact_answer_v1":
        return "deterministic_exact_answer_v1"
    raise ValueError("Unsupported native capability benchmark: %s" % spec.benchmark_id)


def _native_fixture_revision(spec: CapabilityBenchmarkSpec) -> str:
    if spec.benchmark_id == "multiturn_chat_memory_v1":
        return CAPABILITY_REGISTRY_VERSION
    if spec.benchmark_id == "coding_static_repair_v1":
        return CODING_STATIC_REPAIR_FIXTURE_REVISION
    if spec.benchmark_id == "reasoning_exact_answer_v1":
        return REASONING_EXACT_ANSWER_FIXTURE_REVISION
    raise ValueError("Unsupported native capability benchmark: %s" % spec.benchmark_id)


def _selected_check_metadata(request: RunRequest, benchmark_id: str) -> Dict[str, Any]:
    metadata = selection_metadata_for_request(request)
    for check in list(metadata.get("benchmark_checks") or []):
        if check.get("check_id") == benchmark_id:
            return dict(check)
    return {}


def _case_by_id(cases: List[Dict[str, Any]], case_id: str) -> Dict[str, Any]:
    for case in cases:
        candidate = str(case.get("case_id") or case.get("task_id") or stable_hash(case, length=12))
        if candidate == case_id:
            return dict(case)
    return {}


def _case_by_task_id(cases: List[Dict[str, Any]], task_id: str) -> Dict[str, Any]:
    for case in cases:
        if str(case.get("task_id") or case.get("case_id") or "") == task_id:
            return dict(case)
    return {}


def _read_optional_json(path: str) -> Dict[str, Any]:
    try:
        payload = read_json(path)
    except Exception:
        return {}
    return dict(payload or {}) if isinstance(payload, dict) else {}


def _assistant_artifact_claim_boundary(state: str) -> Dict[str, List[str]]:
    unsupported = [
        "This is not a global assistant capability score.",
        "This is not public leaderboard evidence.",
        "This does not prove broad factual accuracy or reasoning ability.",
    ]
    if state == "scored":
        supported = [
            "This local setup completed the pinned multi-turn assistant memory fixture set.",
            "The score reports deterministic phrase-retention checks for this thin local sample.",
        ]
    elif state == "partial":
        supported = [
            "This local setup attempted the pinned multi-turn assistant memory fixture set with partial generation failures.",
            "The artifact preserves scored and failed task rows separately for this thin local sample.",
        ]
    elif state == "failed":
        supported = [
            "This local setup attempted the pinned multi-turn assistant memory fixture set.",
            "The artifact preserves generation failures as failed task rows without converting them to zero scores.",
        ]
    else:
        supported = [
            "This artifact records that the pinned multi-turn assistant memory fixture set was not yet scored.",
        ]
    return {"supported_claims": supported, "unsupported_claims": unsupported}


def _coding_artifact_claim_boundary(state: str) -> Dict[str, List[str]]:
    unsupported = [
        "This is not a global coding capability score.",
        "This is not public leaderboard evidence.",
        "This is not a SWE-bench or LiveCodeBench result.",
        "This does not prove arbitrary repository-editing or unit-test execution skill.",
    ]
    if state == "scored":
        supported = [
            "This local setup completed the pinned coding static-repair fixture set.",
            "The score reports deterministic static code-output constraints for this thin local sample.",
        ]
    elif state == "partial":
        supported = [
            "This local setup attempted the pinned coding static-repair fixture set with partial generation or malformed-output failures.",
            "The artifact preserves scored and failed task rows separately for this thin local sample.",
        ]
    elif state == "failed":
        supported = [
            "This local setup attempted the pinned coding static-repair fixture set.",
            "The artifact preserves generation and malformed-output failures without converting them to broad coding scores.",
        ]
    else:
        supported = [
            "This artifact records that the pinned coding static-repair fixture set was not yet scored.",
        ]
    return {"supported_claims": supported, "unsupported_claims": unsupported}


def _native_artifact_claim_boundary(spec: CapabilityBenchmarkSpec, state: str) -> Dict[str, List[str]]:
    if spec.benchmark_id == "multiturn_chat_memory_v1":
        return _assistant_artifact_claim_boundary(state)
    if spec.benchmark_id == "coding_static_repair_v1":
        return _coding_artifact_claim_boundary(state)
    if spec.benchmark_id == "reasoning_exact_answer_v1":
        return _reasoning_artifact_claim_boundary(state)
    raise ValueError("Unsupported native capability benchmark: %s" % spec.benchmark_id)


def _reasoning_artifact_claim_boundary(state: str) -> Dict[str, List[str]]:
    unsupported = [
        "This is not a global reasoning or intelligence score.",
        "This is not public leaderboard evidence.",
        "This is not MMLU-Pro, GPQA, or gold evidence.",
        "This does not prove broad factual knowledge or expert reasoning ability.",
    ]
    if state == "scored":
        supported = [
            "This local setup completed the pinned exact-answer reasoning fixture set.",
            "The score reports deterministic exact-answer checks for this thin local sample.",
        ]
    elif state == "partial":
        supported = [
            "This local setup attempted the pinned exact-answer reasoning fixture set with partial generation failures.",
            "The artifact preserves scored and failed task rows separately for this thin local sample.",
        ]
    elif state == "failed":
        supported = [
            "This local setup attempted the pinned exact-answer reasoning fixture set.",
            "The artifact preserves generation failures without converting them to broad reasoning scores.",
        ]
    else:
        supported = [
            "This artifact records that the pinned exact-answer reasoning fixture set was not yet scored.",
        ]
    return {"supported_claims": supported, "unsupported_claims": unsupported}


def _mmlu_pro_artifact_claim_boundary(state: str) -> Dict[str, List[str]]:
    unsupported = [
        "This is not a global intelligence score.",
        "This is not public leaderboard evidence.",
        "This is not gold evidence.",
        "Sampled MMLU-Pro reference evidence does not prove broad real-world assistant quality by itself.",
    ]
    if state == "scored":
        supported = [
            "This setup completed the pinned MMLU-Pro sampled reference protocol recorded in this artifact.",
            "The score reports exact multiple-choice answer-letter accuracy with category breakdowns.",
        ]
    elif state == "partial":
        supported = [
            "This setup attempted the pinned MMLU-Pro sampled reference protocol with partial generation or malformed-output failures.",
            "The artifact preserves scored, malformed, and failed task rows separately.",
        ]
    elif state == "failed":
        supported = [
            "This setup attempted the pinned MMLU-Pro sampled reference protocol.",
            "The artifact preserves generation, malformed-output, or scoring failures without turning them into a broad reasoning score.",
        ]
    else:
        supported = [
            "This artifact records that the pinned MMLU-Pro sampled reference protocol was not yet scored.",
        ]
    return {"supported_claims": supported, "unsupported_claims": unsupported}


def _evalplus_artifact_claim_boundary(benchmark_id: str, state: str) -> Dict[str, List[str]]:
    label = "HumanEval+" if benchmark_id == "evalplus_humaneval" else "MBPP+"
    unsupported = [
        "This is not a global coding capability score.",
        "This is not public leaderboard evidence.",
        "This is not gold evidence.",
        "This is not LiveCodeBench, SWE-bench, repository-edit, or broad agentic software-engineering proof.",
    ]
    if state == "scored":
        supported = [
            "This setup completed the pinned EvalPlus %s reference protocol recorded in this artifact." % label,
            "The score reports pass@1 unit-test execution results under the EvalPlus harness.",
        ]
    elif state == "partial":
        supported = [
            "This setup attempted the pinned EvalPlus %s reference protocol with partial generation or execution failures." % label,
            "The artifact preserves scored, malformed, generation, timeout, and test-failed rows separately where EvalPlus reports them.",
        ]
    elif state == "failed":
        supported = [
            "This setup attempted the pinned EvalPlus %s reference protocol." % label,
            "The artifact preserves generation, malformed-output, timeout, test, sandbox, or scoring failures without turning them into a broad coding score.",
        ]
    else:
        supported = [
            "This artifact records that the pinned EvalPlus %s reference protocol was not yet scored." % label,
        ]
    return {"supported_claims": supported, "unsupported_claims": unsupported}


def _capability_artifact_state(status: Any, score: Any, generation_failure_severity: Any = None) -> str:
    if str(generation_failure_severity or "") == "all_failed":
        return "failed"
    if str(generation_failure_severity or "") in {"partial", "dominant"}:
        return "partial"
    if str(status or "") == "failed":
        return "failed"
    if str(status or "") in {"degraded", "partial"}:
        return "partial"
    if score is not None:
        return "scored"
    return "not_yet_benchmarked"


def _planned_benchmark_ids(execution: CapabilityExecution, suite: Optional[Dict[str, Any]], request: RunRequest) -> List[str]:
    if execution.benchmark_check_ids:
        return list(execution.benchmark_check_ids)
    if suite and suite.get("benchmark_ids"):
        return list(suite.get("benchmark_ids") or [])
    return capability_benchmark_ids_for_request(request)


def _prepare_benchmark_cases(spec: CapabilityBenchmarkSpec, benchmark_dir: str, tier: str) -> None:
    if spec.execution_mode == "native":
        _prepare_native_benchmark_cases(spec, benchmark_dir, tier)
        return
    limit = spec.case_limits.get(tier)
    command = ["prepare", "--output-dir", "/work"]
    command.extend(spec.container_args)
    if limit:
        command.extend(["--limit", str(limit)])
    _run_capability_container(spec.container_image, benchmark_dir, command)


def _evaluate_benchmark(spec: CapabilityBenchmarkSpec, benchmark_dir: str) -> Dict[str, Any]:
    if spec.execution_mode == "native":
        return _evaluate_native_benchmark(spec, benchmark_dir)
    command = ["evaluate", "--output-dir", "/work"]
    command.extend(spec.container_args)
    _run_capability_container(spec.container_image, benchmark_dir, command)
    summary_path = os.path.join(benchmark_dir, "summary.json")
    return read_json(summary_path)


def _run_capability_container(image: str, benchmark_dir: str, args: List[str]) -> None:
    install_image(image)
    mount_source = _host_mount_path(os.path.abspath(benchmark_dir))
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        "%s:/work" % mount_source,
        image,
    ]
    command.extend(args)
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            "Capability container failed for image %s: %s" % (image, message or "unknown error")
        )


def _host_mount_path(path: str) -> str:
    """Translate listener-internal run paths into host paths for nested Docker binds."""
    host_runs_dir = os.environ.get("INFERGRADE_HOST_RUNS_DIR")
    if not host_runs_dir:
        return path
    listener_runs_dir = os.path.abspath(os.environ.get("INFERGRADE_LISTENER_RUNS_DIR", _LISTENER_RUNS_DIR))
    normalized_path = os.path.abspath(path)
    if normalized_path == listener_runs_dir:
        return os.path.abspath(host_runs_dir)
    prefix = listener_runs_dir + os.sep
    if normalized_path.startswith(prefix):
        relative_path = os.path.relpath(normalized_path, listener_runs_dir)
        return os.path.abspath(os.path.join(host_runs_dir, relative_path))
    return normalized_path


def _generate_predictions(
    adapter,
    request: RunRequest,
    spec: CapabilityBenchmarkSpec,
    cases: List[Dict[str, Any]],
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[Dict[str, Any]]:
    predictions = []
    total_cases = len(cases)
    for index, case in enumerate(cases, start=1):
        case_id = case.get("case_id") or case.get("task_id") or stable_hash(case, length=12)
        try:
            generated = adapter.generate_text(
                request=request,
                prompt=case["prompt"],
                max_tokens=spec.generation_max_tokens,
            )
            text = generated.get("text", "")
            status = generated.get("status", "completed")
            error = generated.get("error")
        except Exception as exc:
            text = ""
            status = "failed"
            error = str(exc)
        record = {
            "case_id": case_id,
            "benchmark_id": spec.benchmark_id,
            "generation_status": status,
            "generation_error": error,
        }
        if spec.benchmark_kind in {"instruction_following", "multiturn_instruction_retention"}:
            record["prompt"] = case["prompt"]
            record["response"] = text
        else:
            record["task_id"] = case["task_id"]
            record["completion"] = text
        predictions.append(record)
        if progress_callback:
            progress_callback(
                {
                    "event": "case_progress",
                    "benchmark_id": spec.benchmark_id,
                    "display_name": spec.display_name,
                    "completed_cases": index,
                    "total_cases": total_cases,
                    "current_case": case_id,
                    "message": "Capability benchmark %s %d/%d cases." % (spec.display_name, index, total_cases),
                }
            )
    return predictions


def _prepare_native_benchmark_cases(spec: CapabilityBenchmarkSpec, benchmark_dir: str, tier: str) -> None:
    cases = _native_benchmark_cases(spec)
    limit = spec.case_limits.get(tier)
    if limit:
        cases = cases[:limit]
    _write_jsonl(os.path.join(benchmark_dir, "cases.jsonl"), cases)


def _evaluate_native_benchmark(spec: CapabilityBenchmarkSpec, benchmark_dir: str) -> Dict[str, Any]:
    cases_by_id = {
        str(item.get("case_id") or item.get("task_id") or stable_hash(item, length=12)): item
        for item in _read_jsonl(os.path.join(benchmark_dir, "cases.jsonl"))
    }
    predictions = _read_jsonl(os.path.join(benchmark_dir, "predictions.jsonl"))
    total_constraints = 0
    passed_constraints = 0
    case_results = []
    for prediction in predictions:
        case_id = str(prediction.get("case_id") or "")
        case = cases_by_id.get(case_id) or {}
        checks = list(case.get("checks") or [])
        response = str(prediction.get("response") or prediction.get("completion") or "")
        if prediction.get("generation_status") != "completed":
            total_constraints += len(checks) if checks else 1
            case_results.append(
                {
                    "case_id": case_id,
                    "state": "failed",
                    "error_class": "generation_failed",
                    "passed_constraints": 0,
                    "total_constraints": len(checks) if checks else 1,
                    "score": None,
                }
            )
            continue
        expected_answers = list(case.get("expected_answers") or [])
        if expected_answers:
            total_constraints += 1
            expected = [_normalize_exact_answer(item) for item in expected_answers]
            extracted_answer = _extract_exact_answer(response, expected_answers)
            passed = extracted_answer in expected
            if passed:
                passed_constraints += 1
            case_results.append(
                {
                    "case_id": case_id,
                    "state": "scored",
                    "error_class": None,
                    "passed_constraints": 1 if passed else 0,
                    "total_constraints": 1,
                    "score": 1.0 if passed else 0.0,
                }
            )
            continue
        score_target = response
        if case.get("requires_code_fence"):
            extracted_code = _extract_single_code_fence(response, case.get("code_fence_language"))
            if extracted_code is None:
                total_constraints += len(checks)
                case_results.append(
                    {
                        "case_id": case_id,
                        "state": "failed",
                        "error_class": "malformed_output",
                        "passed_constraints": 0,
                        "total_constraints": len(checks),
                        "score": None,
                    }
                )
                continue
            score_target = extracted_code
        normalized_response = _normalize_score_text(score_target)
        case_passed = 0
        for check in checks:
            required_any = [_normalize_score_text(item) for item in list(check.get("required_any") or [])]
            required_all = [_normalize_score_text(item) for item in list(check.get("required_all") or [])]
            forbidden_any = [_normalize_score_text(item) for item in list(check.get("forbidden_any") or [])]
            passed = False
            if required_any:
                passed = any(item and item in normalized_response for item in required_any)
            elif required_all:
                passed = all(item and item in normalized_response for item in required_all)
            if passed and forbidden_any:
                passed = not any(item and item in normalized_response for item in forbidden_any)
            total_constraints += 1
            if passed:
                passed_constraints += 1
                case_passed += 1
        case_results.append(
            {
                "case_id": case_id,
                "state": "scored",
                "error_class": None,
                "passed_constraints": case_passed,
                "total_constraints": len(checks),
                "score": round(case_passed / float(len(checks)), 6) if checks else None,
            }
        )
    score = round(passed_constraints / float(total_constraints), 6) if total_constraints else None
    malformed_output_count = len([item for item in case_results if item.get("error_class") == "malformed_output"])
    correct_count = len([item for item in case_results if item.get("score") == 1.0])
    status = "partial" if malformed_output_count else "completed"
    return {
        "benchmark_id": spec.benchmark_id,
        "display_name": spec.display_name,
        "status": status,
        "primary_metric": {"name": spec.primary_metric_name, "value": score},
        "metrics": {
            spec.primary_metric_name: score,
            "passed_constraints": passed_constraints,
            "total_constraints": total_constraints,
            "correct_count": correct_count,
            "total_count": len(case_results),
            "malformed_output_count": malformed_output_count,
            "case_accuracy": round(
                len([item for item in case_results if item.get("score") == 1.0]) / float(len(case_results)),
                6,
            )
            if case_results
            else None,
        },
        "case_results": case_results,
        "scoring_policy": _native_scoring_policy(spec),
    }


def _normalize_score_text(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _normalize_exact_answer(value: Any) -> str:
    return _normalize_score_text(str(value or "").strip().strip(".:;!?,"))


def _extract_exact_answer(value: Any, expected_answers: List[Any]) -> Optional[str]:
    normalized = _normalize_score_text(value)
    expected = [_normalize_exact_answer(item) for item in expected_answers]
    if normalized in expected:
        return normalized

    if set(expected) <= {"yes", "no"}:
        hits = [item for item in ("yes", "no") if re.search(r"\b%s\b" % re.escape(item), normalized)]
        return hits[0] if len(hits) == 1 else None

    if all(re.fullmatch(r"-?\d+", item or "") for item in expected):
        hits = re.findall(r"\b-?\d+\b", normalized)
        unique_hits = []
        for item in hits:
            if item not in unique_hits:
                unique_hits.append(item)
        return unique_hits[0] if len(unique_hits) == 1 else None

    if all(re.fullmatch(r"[a-z]", item or "") for item in expected):
        hits = re.findall(r"\b([a-z])\b(?:\)|\.|:)?", normalized)
        unique_hits = []
        for item in hits:
            if item not in unique_hits:
                unique_hits.append(item)
        return unique_hits[0] if len(unique_hits) == 1 else None

    return None


def _extract_single_code_fence(value: str, language: Any = None) -> Optional[str]:
    text = str(value or "")
    fence_pattern = re.compile(
        r"```(?P<language>[A-Za-z0-9_+-]*)[ \t]*\r?\n(?P<code>.*?)\r?\n```",
        flags=re.DOTALL,
    )
    matches = list(fence_pattern.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    expected_language = str(language or "").strip().lower()
    actual_language = str(match.group("language") or "").strip().lower()
    if expected_language and actual_language != expected_language:
        return None
    outside = text[: match.start()] + text[match.end() :]
    if outside.strip():
        return None
    return match.group("code")


def _native_benchmark_cases(spec: CapabilityBenchmarkSpec) -> List[Dict[str, Any]]:
    if spec.benchmark_id == "multiturn_chat_memory_v1":
        return _multiturn_chat_memory_cases()
    if spec.benchmark_id == "coding_static_repair_v1":
        return _coding_static_repair_cases()
    if spec.benchmark_id == "reasoning_exact_answer_v1":
        return _reasoning_exact_answer_cases()
    raise ValueError("Unsupported native capability benchmark: %s" % spec.benchmark_id)


def _reasoning_exact_answer_cases() -> List[Dict[str, Any]]:
    return [
        {
            "case_id": "reasoning-exact-syllogism",
            "task_id": "reasoning_exact_answer_v1/syllogism",
            "prompt": (
                "Answer exactly yes or no.\n"
                "Every dax is a wug. No wug is red. Can a dax be red?"
            ),
            "expected_answers": ["no"],
        },
        {
            "case_id": "reasoning-exact-token-count",
            "task_id": "reasoning_exact_answer_v1/token-count",
            "prompt": (
                "Answer only the number.\n"
                "A box has 3 blue tokens and 2 red tokens. Add 4 blue tokens and remove 1 red token. "
                "How many blue tokens are in the box?"
            ),
            "expected_answers": ["7"],
        },
        {
            "case_id": "reasoning-exact-ordering",
            "task_id": "reasoning_exact_answer_v1/ordering",
            "prompt": (
                "Answer only the option letter.\n"
                "If A is greater than B, and B is greater than C, what is A relative to C?\n"
                "A) less than\n"
                "B) greater than\n"
                "C) equal"
            ),
            "expected_answers": ["B"],
        },
    ]


def _coding_static_repair_cases() -> List[Dict[str, Any]]:
    return [
        {
            "case_id": "coding-static-clamp-score",
            "task_id": "coding_static_repair_v1/clamp-score",
            "prompt": (
                "Return only a fenced Python code block. Repair this function without using min() or max():\n\n"
                "def clamp_score(value):\n"
                "    # Return 0 when value is below 0, 1 when above 1, otherwise the original value.\n"
                "    pass\n"
            ),
            "requires_code_fence": True,
            "code_fence_language": "python",
            "checks": [
                {"label": "function name preserved", "required_all": ["def clamp_score(value):"]},
                {"label": "lower bound branch", "required_all": ["if value < 0", "return 0"]},
                {"label": "upper bound branch", "required_all": ["if value > 1", "return 1"]},
                {"label": "identity return", "required_all": ["return value"]},
                {"label": "no min max shortcut", "required_all": ["def clamp_score"], "forbidden_any": ["min(", "max("]},
            ],
        },
        {
            "case_id": "coding-static-parse-model-pair",
            "task_id": "coding_static_repair_v1/parse-model-pair",
            "prompt": (
                "Return only a fenced Python code block. Implement parse_model_pair(text) so input like "
                "'Qwen2.5@q4_k_m' returns {'model': 'Qwen2.5', 'quant': 'q4_k_m'}. Split only once on '@' "
                "and strip whitespace from both fields.\n"
            ),
            "requires_code_fence": True,
            "code_fence_language": "python",
            "checks": [
                {"label": "function name", "required_all": ["def parse_model_pair(text):"]},
                {"label": "single split", "required_any": ["split('@', 1)", "split(\"@\", 1)"]},
                {"label": "model key", "required_any": ["'model'", "\"model\""]},
                {"label": "quant key", "required_any": ["'quant'", "\"quant\""]},
                {"label": "strip whitespace", "required_all": [".strip()"]},
            ],
        },
        {
            "case_id": "coding-static-render-status-line",
            "task_id": "coding_static_repair_v1/render-status-line",
            "prompt": (
                "Return only a fenced Python code block. Implement render_status_line(status) for a dictionary "
                "with keys state and model. The returned string must include 'status=' followed by the state and "
                "'model=' followed by the model.\n"
            ),
            "requires_code_fence": True,
            "code_fence_language": "python",
            "checks": [
                {"label": "function name", "required_all": ["def render_status_line(status):"]},
                {"label": "status label", "required_any": ["status=", "status ="]},
                {"label": "model label", "required_any": ["model=", "model ="]},
                {"label": "state field", "required_any": ["['state']", "[\"state\"]"]},
                {"label": "model field", "required_any": ["['model']", "[\"model\"]"]},
            ],
        },
    ]


def _multiturn_chat_memory_cases() -> List[Dict[str, Any]]:
    return [
        {
            "case_id": "memory-project-quant",
            "task_id": "multiturn_chat_memory_v1/memory-project-quant",
            "prompt": (
                "You are replaying a multi-turn assistant conversation. Answer only the final assistant message.\n\n"
                "User: For this conversation, remember that the project codename is HARBOR-17 and the selected quant is q4_k_m.\n"
                "Assistant: Noted.\n"
                "User: Later, if I ask for the saved setup, answer exactly: HARBOR-17 uses q4_k_m.\n"
                "Assistant: Understood.\n"
                "User: What saved setup did I pick?\n"
                "Assistant:"
            ),
            "checks": [
                {"label": "project codename retained", "required_any": ["HARBOR-17"]},
                {"label": "quant retained", "required_any": ["q4_k_m"]},
            ],
        },
        {
            "case_id": "memory-output-format",
            "task_id": "multiturn_chat_memory_v1/memory-output-format",
            "prompt": (
                "You are replaying a multi-turn assistant conversation. Answer only the final assistant message.\n\n"
                "User: Remember these two rules: use the label READY and do not use bullet points.\n"
                "Assistant: I will remember.\n"
                "User: The deployment target is local runner.\n"
                "Assistant: Noted.\n"
                "User: Give the shortest possible status update using the remembered label and target.\n"
                "Assistant:"
            ),
            "checks": [
                {"label": "ready label retained", "required_any": ["READY"]},
                {"label": "target retained", "required_any": ["local runner"]},
            ],
        },
        {
            "case_id": "memory-correction",
            "task_id": "multiturn_chat_memory_v1/memory-correction",
            "prompt": (
                "You are replaying a multi-turn assistant conversation. Answer only the final assistant message.\n\n"
                "User: Remember that my hardware is RTX 4090.\n"
                "Assistant: Remembered.\n"
                "User: Correction: my hardware is actually Apple M2 Max, not RTX 4090.\n"
                "Assistant: Updated.\n"
                "User: Which hardware should you use for the recommendation?\n"
                "Assistant:"
            ),
            "checks": [
                {"label": "correction retained", "required_any": ["Apple M2 Max"]},
            ],
        },
        {
            "case_id": "memory-two-preferences",
            "task_id": "multiturn_chat_memory_v1/memory-two-preferences",
            "prompt": (
                "You are replaying a multi-turn assistant conversation. Answer only the final assistant message.\n\n"
                "User: Remember that I prefer fast first tokens over maximum throughput.\n"
                "Assistant: Got it.\n"
                "User: Also remember that I want a public model only.\n"
                "Assistant: Noted.\n"
                "User: State my two remembered preferences in one sentence.\n"
                "Assistant:"
            ),
            "checks": [
                {"label": "latency preference retained", "required_any": ["fast first tokens", "first tokens"]},
                {"label": "public model preference retained", "required_any": ["public model", "public"]},
            ],
        },
        {
            "case_id": "memory-numeric-token",
            "task_id": "multiturn_chat_memory_v1/memory-numeric-token",
            "prompt": (
                "You are replaying a multi-turn assistant conversation. Answer only the final assistant message.\n\n"
                "User: Save this exact pairing code for the next question: IGRP-8421.\n"
                "Assistant: Saved.\n"
                "User: Do not explain it later; just return the code.\n"
                "Assistant: Understood.\n"
                "User: What was the pairing code?\n"
                "Assistant:"
            ),
            "checks": [
                {"label": "pairing code retained", "required_any": ["IGRP-8421"]},
            ],
        },
    ]


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_jsonl(path: str, rows: List[Dict[str, Any]]) -> None:
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")
