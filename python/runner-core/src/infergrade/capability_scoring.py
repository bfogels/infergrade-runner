"""Versioned, task-scoped local capability score helpers.

Scores in this module deliberately remain separate from deployment speed,
memory, cost, and quant fidelity.  A score is only headline-ready once the
Runner-owned surface policy has enough weighted benchmark coverage.
"""

from typing import Any, Dict, List, Optional

from infergrade.benchmark_catalog import check_index, load_capability_catalog, surface_score_policy_index


USE_CASE_PRIMARY_SURFACE = {
    "general_assistant": "local_assistant_capability",
    "agentic_coding": "local_coding_capability",
    "reasoning": "local_reasoning_capability",
}


def primary_surface_for_use_case(use_case: Optional[str]) -> Optional[str]:
    return USE_CASE_PRIMARY_SURFACE.get(str(use_case or ""))


def infer_surface_from_components(
    component_scores: Dict[str, float],
    catalog: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    checks = check_index(catalog)
    surfaces = {
        checks[benchmark_id].get("surface_id")
        for benchmark_id in component_scores
        if benchmark_id in checks and checks[benchmark_id].get("evidence_kind") == "capability"
    }
    surfaces.discard(None)
    return next(iter(surfaces)) if len(surfaces) == 1 else None


def score_capability_surface(
    surface_id: Optional[str],
    component_scores: Dict[str, float],
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a conservative score and inspectable coverage metadata."""
    payload = catalog or load_capability_catalog()
    checks = check_index(payload)
    policy = surface_score_policy_index(payload).get(str(surface_id or ""), {})
    if not policy:
        return {
            "surface_id": surface_id,
            "score": None,
            "observed_weighted_score": None,
            "score_ready": False,
            "reason": "surface_score_policy_missing",
            "components": [],
        }

    profile_checks = []
    for benchmark_id, check in checks.items():
        if check.get("surface_id") != surface_id or check.get("evidence_kind") != "capability":
            continue
        weight = _positive_float(check.get("primary_score_weight"))
        if weight is None:
            continue
        profile_checks.append((benchmark_id, check, weight))

    total_weight = sum(item[2] for item in profile_checks)
    observed_weight = 0.0
    weighted_total = 0.0
    components: List[Dict[str, Any]] = []
    missing_benchmark_ids = []
    for benchmark_id, check, weight in profile_checks:
        value = _score_value(component_scores.get(benchmark_id))
        if value is None:
            missing_benchmark_ids.append(benchmark_id)
        else:
            observed_weight += weight
            weighted_total += value * weight
        components.append(
            {
                "benchmark_id": benchmark_id,
                "display_name": check.get("display_name"),
                "score_dimension": check.get("score_dimension"),
                "score": value,
                "weight": round(weight, 6),
                "weighted_contribution": round(value * weight, 6) if value is not None else None,
                "observed": value is not None,
            }
        )

    coverage_fraction = round(observed_weight / total_weight, 6) if total_weight else 0.0
    observed_score = round(weighted_total / observed_weight, 6) if observed_weight else None
    minimum_coverage = _bounded_fraction(policy.get("minimum_coverage_fraction"), default=1.0)
    score_ready = observed_score is not None and coverage_fraction >= minimum_coverage
    return {
        "surface_id": surface_id,
        "score_label": policy.get("display_name"),
        "score_version": policy.get("score_version"),
        "score_method": policy.get("score_method"),
        "score_unit": "fraction_0_to_1",
        "score": observed_score if score_ready else None,
        "observed_weighted_score": observed_score,
        "score_ready": score_ready,
        "reason": "score_ready" if score_ready else ("insufficient_weighted_coverage" if observed_score is not None else "no_scored_components"),
        "coverage": {
            "observed_weight": round(observed_weight, 6),
            "total_weight": round(total_weight, 6),
            "coverage_fraction": coverage_fraction,
            "minimum_coverage_fraction": minimum_coverage,
            "complete": bool(total_weight and observed_weight >= total_weight),
            "missing_benchmark_ids": missing_benchmark_ids,
        },
        "components": components,
        "claim_boundary": policy.get("claim_boundary"),
    }


def score_for_use_case(
    use_case: Optional[str],
    component_scores: Dict[str, float],
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = catalog or load_capability_catalog()
    surface_id = primary_surface_for_use_case(use_case) or infer_surface_from_components(component_scores, payload)
    return score_capability_surface(surface_id, component_scores, payload)


def _score_value(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0 or parsed > 1:
        return None
    return parsed


def _positive_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _bounded_fraction(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return min(1.0, max(0.0, parsed))
