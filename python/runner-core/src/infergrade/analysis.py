import os
from typing import Any, Dict, Iterable, List, Sequence

from infergrade.utils import read_json


def load_results_from_path(path: str) -> List[Dict[str, Any]]:
    if os.path.isdir(path):
        results_dir = os.path.join(path, "results")
        if os.path.isdir(results_dir):
            payloads = []
            for filename in sorted(os.listdir(results_dir)):
                if filename.endswith(".json"):
                    payloads.append(read_json(os.path.join(results_dir, filename)))
            return payloads
        return []
    if path.endswith(".json"):
        return [read_json(path)]
    return []


def load_results(paths: Sequence[str]) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []
    for path in paths:
        payloads.extend(load_results_from_path(path))
    return payloads


def summarize_bundle(bundle_dir: str) -> Dict[str, Any]:
    manifest = read_json(os.path.join(bundle_dir, "manifest.json"))
    validation_path = os.path.join(bundle_dir, "validation.json")
    validation = read_json(validation_path) if os.path.exists(validation_path) else None
    results = load_results_from_path(bundle_dir)
    return {
        "bundle_id": manifest["bundle_id"],
        "result_count": len(results),
        "result_ids": [item["result_id"] for item in results],
        "benchmark_subject_ids": sorted(
            {
                item.get("ontology", {}).get("benchmark_subject", {}).get("subject_id")
                for item in results
                if item.get("ontology", {}).get("benchmark_subject", {}).get("subject_id")
            }
        ),
        "checkpoints": sorted(
            {
                item.get("ontology", {}).get("checkpoint", {}).get("checkpoint_name")
                for item in results
                if item.get("ontology", {}).get("checkpoint", {}).get("checkpoint_name")
            }
        ),
        "model_families": sorted(
            {
                item.get("ontology", {}).get("model_family", {}).get("family_name")
                for item in results
                if item.get("ontology", {}).get("model_family", {}).get("family_name")
            }
        ),
        "deployment_profiles": [item.get("deployment", {}).get("deployment_profile_id") for item in results],
        "use_cases": sorted(
            {
                item.get("capability", {}).get("use_case")
                for item in results
                if item.get("capability", {}).get("use_case")
            }
        ),
        "verification_levels": sorted(
            {
                item.get("verification", {}).get("verification_level")
                for item in results
                if item.get("verification", {}).get("verification_level")
            }
        ),
        "comparison_grade_candidates": sorted(
            {
                item.get("verification", {}).get("local_comparison_grade_candidate")
                for item in results
                if item.get("verification", {}).get("local_comparison_grade_candidate")
            }
        ),
        "created_at": manifest.get("created_at"),
        "validation": validation,
        "results": [_brief_result(item) for item in results],
    }


def _brief_result(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "result_id": result.get("result_id"),
        "benchmark_subject_id": result.get("ontology", {}).get("benchmark_subject", {}).get("subject_id"),
        "checkpoint_name": result.get("ontology", {}).get("checkpoint", {}).get("checkpoint_name"),
        "model_family": result.get("ontology", {}).get("model_family", {}).get("family_name"),
        "quantization_label": result.get("ontology", {}).get("quantization", {}).get("quantization_label"),
        "backend_engine": result.get("ontology", {}).get("runtime_binding", {}).get("backend_engine"),
        "deployment_profile_id": result.get("deployment", {}).get("deployment_profile_id"),
        "use_case": result.get("capability", {}).get("use_case"),
        "verification_level": result.get("verification", {}).get("verification_level"),
        "comparison_grade_candidate": result.get("verification", {}).get("local_comparison_grade_candidate"),
        "ttft_p50_ms": result.get("deployment", {}).get("ttft_p50_ms"),
        "decode_tokens_per_second_p50": result.get("deployment", {}).get("decode_tokens_per_second_p50"),
        "capability_score": result.get("capability", {}).get("capability_score"),
        "benchmark_job_cost_usd": result.get("cost", {}).get("benchmark_job_cost_usd"),
    }


def filter_results(
    results: Iterable[Dict[str, Any]],
    use_case: str = None,
    deployment_profile: str = None,
    verification_levels: Sequence[str] = (),
    max_vram_gb: float = None,
) -> List[Dict[str, Any]]:
    verification_levels = set(verification_levels or [])
    filtered = []
    for result in results:
        if use_case and result.get("capability", {}).get("use_case") != use_case:
            continue
        if deployment_profile and result.get("deployment", {}).get("deployment_profile_id") != deployment_profile:
            continue
        if verification_levels and result.get("verification", {}).get("verification_level") not in verification_levels:
            continue
        if max_vram_gb is not None:
            vram = result.get("hardware", {}).get("accelerator_vram_gb")
            if vram is None or vram > max_vram_gb:
                continue
        filtered.append(result)
    return filtered


def pareto_frontier(results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results = list(results)
    frontier = []
    for candidate in results:
        dominated = False
        for other in results:
            if other is candidate:
                continue
            if _dominates(other, candidate):
                dominated = True
                break
        if not dominated:
            frontier.append(candidate)
    return frontier


def _dominates(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    left_capability = left.get("capability", {}).get("capability_score")
    right_capability = right.get("capability", {}).get("capability_score")
    left_speed = left.get("deployment", {}).get("decode_tokens_per_second_p50")
    right_speed = right.get("deployment", {}).get("decode_tokens_per_second_p50")
    left_ttft = left.get("deployment", {}).get("ttft_p50_ms")
    right_ttft = right.get("deployment", {}).get("ttft_p50_ms")
    left_cost = left.get("cost", {}).get("benchmark_job_cost_usd")
    right_cost = right.get("cost", {}).get("benchmark_job_cost_usd")

    def compare_higher(a, b):
        return a is not None and b is not None and a >= b

    def compare_lower(a, b):
        return a is not None and b is not None and a <= b

    metrics_ok = [
        compare_higher(left_capability, right_capability) if right_capability is not None else True,
        compare_higher(left_speed, right_speed) if right_speed is not None else True,
        compare_lower(left_ttft, right_ttft) if right_ttft is not None else True,
        compare_lower(left_cost, right_cost) if right_cost is not None else True,
    ]
    if not all(metrics_ok):
        return False
    strictly_better = any(
        [
            left_capability is not None and right_capability is not None and left_capability > right_capability,
            left_speed is not None and right_speed is not None and left_speed > right_speed,
            left_ttft is not None and right_ttft is not None and left_ttft < right_ttft,
            left_cost is not None and right_cost is not None and left_cost < right_cost,
        ]
    )
    return strictly_better


def recommend(
    paths: Sequence[str],
    use_case: str = None,
    deployment_profile: str = None,
    max_vram_gb: float = None,
    verification_levels: Sequence[str] = (),
) -> Dict[str, Any]:
    results = load_results(paths)
    filtered = filter_results(
        results,
        use_case=use_case,
        deployment_profile=deployment_profile,
        verification_levels=verification_levels,
        max_vram_gb=max_vram_gb,
    )
    frontier = pareto_frontier(filtered)
    return {
        "input_count": len(results),
        "filtered_count": len(filtered),
        "frontier_count": len(frontier),
        "results": [_brief_result(item) for item in frontier],
    }
