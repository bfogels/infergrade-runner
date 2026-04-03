import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from infergrade.benchmark_catalog import (
    capability_benchmark_ids_for_request,
    resolve_request_selection,
    selection_metadata_for_request,
)
from infergrade.images import install_image
from infergrade.models import CapabilityExecution, RunRequest
from infergrade.utils import ensure_dir, env_value, read_json, stable_hash, write_json

CAPABILITY_REGISTRY_VERSION = "2026-04-alpha"

DEFAULT_CAPABILITY_IMAGES = {
    "ifeval": env_value("INFERGRADE_IFEVAL_IMAGE", "QUANTBENCH_IFEVAL_IMAGE", "infergrade-ifeval:local"),
    "evalplus_humaneval": env_value("INFERGRADE_EVALPLUS_IMAGE", "QUANTBENCH_EVALPLUS_IMAGE", "infergrade-evalplus:local"),
    "evalplus_mbpp": env_value("INFERGRADE_EVALPLUS_IMAGE", "QUANTBENCH_EVALPLUS_IMAGE", "infergrade-evalplus:local"),
}

_LISTENER_RUNS_DIR = "/app/runs"


@dataclass(frozen=True)
class CapabilityBenchmarkSpec:
    benchmark_id: str
    display_name: str
    benchmark_kind: str
    primary_metric_name: str
    generation_max_tokens: int
    container_image: str
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
}


CAPABILITY_SUITES: Dict[str, Dict[str, tuple]] = {
    "agentic_coding": {
        "canary": ("coding_canary_v2", ["EvalPlus HumanEval+"]),
        "standard": ("coding_standard_v3", ["EvalPlus HumanEval+", "EvalPlus MBPP+"]),
        "gold": ("coding_gold_v2", ["EvalPlus HumanEval+", "EvalPlus MBPP+"]),
    },
    "general_assistant": {
        "canary": ("assistant_canary_v2", ["IFEval"]),
        "standard": ("assistant_standard_v2", ["IFEval"]),
        "gold": ("assistant_gold_v2", ["IFEval"]),
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
        "standard": ["ifeval"],
        "gold": ["ifeval"],
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
    registry: List[Dict[str, Any]] = []
    for benchmark_id in benchmark_ids:
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
    benchmark_registry = capability_registry_for_request(request)
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
        if _benchmark_primary_metric_value(benchmark_results.get(benchmark_id) or {}) is not None
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
        for benchmark_id in (suite or {}).get("benchmark_ids", [])
    ):
        codes.append("benchmark_component_failed")
    if execution.status == "failed":
        codes.append("benchmark_execution_failed")
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
            summary["generation_failure_count"] = len(
                [item for item in predictions if item.get("generation_status") != "completed"]
            )
            write_json(os.path.join(benchmark_dir, "summary.json"), summary)
            if progress_callback:
                progress_callback(
                    {
                        "event": "benchmark_completed",
                        "benchmark_id": benchmark_id,
                        "display_name": spec.display_name,
                        "total_cases": len(cases),
                        "completed_cases": len(cases),
                        "status": "completed",
                        "primary_metric": summary.get("primary_metric", {}).get("value"),
                        "message": "Capability benchmark %s completed." % spec.display_name,
                    }
                )
            benchmark_results[benchmark_id] = summary
            benchmark_artifacts[benchmark_id] = {
                "benchmark_dir": benchmark_dir,
                "cases_path": os.path.join(benchmark_dir, "cases.jsonl"),
                "predictions_path": os.path.join(benchmark_dir, "predictions.jsonl"),
                "summary_path": os.path.join(benchmark_dir, "summary.json"),
            }
            primary_value = summary.get("primary_metric", {}).get("value")
            if primary_value is not None:
                component_scores[benchmark_id] = round(float(primary_value), 6)
                completed += 1
        except Exception as exc:
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
            benchmark_results[benchmark_id] = {
                "benchmark_id": benchmark_id,
                "display_name": spec.display_name,
                "status": "failed",
                "error": str(exc),
                "primary_metric": {
                    "name": spec.primary_metric_name,
                    "value": None,
                },
            }
            benchmark_artifacts[benchmark_id] = {"benchmark_dir": benchmark_dir}

    status = "failed"
    if completed == len(benchmark_ids):
        status = "completed"
    elif completed > 0:
        status = "partial"

    score = None
    if component_scores:
        score = round(sum(component_scores.values()) / float(len(component_scores)), 6)

    confidence = None
    if status == "completed":
        confidence = 0.9
    elif status == "partial":
        confidence = 0.6

    return CapabilityExecution(
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


def _prepare_benchmark_cases(spec: CapabilityBenchmarkSpec, benchmark_dir: str, tier: str) -> None:
    limit = spec.case_limits.get(tier)
    command = ["prepare", "--output-dir", "/work"]
    command.extend(spec.container_args)
    if limit:
        command.extend(["--limit", str(limit)])
    _run_capability_container(spec.container_image, benchmark_dir, command)


def _evaluate_benchmark(spec: CapabilityBenchmarkSpec, benchmark_dir: str) -> Dict[str, Any]:
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
        if spec.benchmark_kind == "instruction_following":
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
