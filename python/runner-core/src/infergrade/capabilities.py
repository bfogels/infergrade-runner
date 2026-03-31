import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from infergrade.images import install_image
from infergrade.models import CapabilityExecution, RunRequest
from infergrade.utils import ensure_dir, env_value, read_json, stable_hash, write_json


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
        "standard": ("coding_standard_v2", ["EvalPlus HumanEval+"]),
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
        "standard": ["evalplus_humaneval"],
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
    suite_id, components = CAPABILITY_SUITES[use_case][tier]
    return {
        "use_case": use_case,
        "suite_id": suite_id,
        "benchmark_tier": tier,
        "components": components,
        "benchmark_ids": list(SUITE_BENCHMARK_IDS[use_case][tier]),
    }


def capability_images_for_request(request: RunRequest) -> List[Dict[str, str]]:
    suite = resolve_capability_suite(request.use_case, request.tier)
    if request.capability == "none" or suite is None:
        return []
    images = []
    for benchmark_id in suite["benchmark_ids"]:
        spec = CAPABILITY_BENCHMARKS[benchmark_id]
        images.append(
            {
                "benchmark_id": benchmark_id,
                "display_name": spec.display_name,
                "image": spec.container_image,
            }
        )
    return images


def execute_capability_suite(
    adapter,
    request: RunRequest,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> CapabilityExecution:
    suite = resolve_capability_suite(request.use_case, request.tier)
    if suite is None:
        return CapabilityExecution(
            use_case=request.use_case,
            suite_id=None,
            benchmark_tier=request.tier,
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

    for benchmark_id in suite["benchmark_ids"]:
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
    if completed == len(suite["benchmark_ids"]):
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
        suite_id=suite["suite_id"],
        benchmark_tier=suite["benchmark_tier"],
        components=suite["components"],
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
