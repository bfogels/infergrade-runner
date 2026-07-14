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
    benchmark_tier: Optional[str] = None,
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
    diagnostic_checks = []
    for benchmark_id, check in checks.items():
        if check.get("surface_id") != surface_id or check.get("evidence_kind") != "capability":
            continue
        weight = _positive_float(check.get("primary_score_weight"))
        if weight is None:
            if check.get("score_role") == "diagnostic_only":
                diagnostic_checks.append((benchmark_id, check))
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
                "score_role": check.get("score_role") or "headline_component",
                "discrimination_status": check.get("discrimination_status"),
                "score": value,
                "weight": round(weight, 6),
                "weighted_contribution": round(value * weight, 6) if value is not None else None,
                "observed": value is not None,
            }
        )

    coverage_fraction = round(observed_weight / total_weight, 6) if total_weight else 0.0
    observed_score = round(weighted_total / observed_weight, 6) if observed_weight else None
    minimum_coverage = _bounded_fraction(policy.get("minimum_coverage_fraction"), default=1.0)
    observed_components = [item for item in components if item["observed"]]
    observed_dimensions = sorted({str(item.get("score_dimension") or "") for item in observed_components if item.get("score_dimension")})
    minimum_components = _positive_int(policy.get("minimum_scored_components"), default=2)
    minimum_dimensions = _positive_int(policy.get("minimum_score_dimensions"), default=2)
    coverage_ready = observed_score is not None and coverage_fraction >= minimum_coverage
    diversity_ready = len(observed_components) >= minimum_components and len(observed_dimensions) >= minimum_dimensions
    robustness = _robustness_payload(observed_components, observed_score, policy)
    maximum_influence = _bounded_fraction(policy.get("maximum_component_weight_fraction"), default=0.8)
    influence_ready = robustness.get("maximum_observed_weight_fraction") is None or robustness["maximum_observed_weight_fraction"] <= maximum_influence
    minimum_benchmark_tier = str(policy.get("minimum_benchmark_tier") or "").strip() or None
    tier_ranks = {"canary": 1, "standard": 2, "gold": 3}
    benchmark_depth_ready = (
        minimum_benchmark_tier is None
        or tier_ranks.get(str(benchmark_tier or ""), 0) >= tier_ranks.get(minimum_benchmark_tier, 0)
    )
    failed_gates = []
    if observed_score is None:
        failed_gates.append("no_scored_components")
    if observed_score is not None and not coverage_ready:
        failed_gates.append("insufficient_weighted_coverage")
    if len(observed_components) < minimum_components:
        failed_gates.append("insufficient_scored_components")
    if len(observed_dimensions) < minimum_dimensions:
        failed_gates.append("insufficient_score_dimensions")
    if not influence_ready:
        failed_gates.append("component_influence_above_limit")
    if not benchmark_depth_ready:
        failed_gates.append("insufficient_benchmark_depth")
    score_ready = not failed_gates
    reason = "score_ready" if score_ready else failed_gates[0]
    diagnostic_components = []
    for benchmark_id, check in diagnostic_checks:
        value = _score_value(component_scores.get(benchmark_id))
        diagnostic_components.append(
            {
                "benchmark_id": benchmark_id,
                "display_name": check.get("display_name"),
                "score_dimension": check.get("score_dimension"),
                "score": value,
                "observed": value is not None,
                "score_role": "diagnostic_only",
                "discrimination_status": check.get("discrimination_status"),
                "saturation_evidence": dict(check.get("saturation_evidence") or {}),
                "claim_boundary": (
                    "This diagnostic may prove the fixture was cleared, but it contributes no headline score weight and cannot establish perfect capability."
                ),
            }
        )
    ceiling_reached = observed_score is not None and observed_score >= 1.0
    return {
        "surface_id": surface_id,
        "score_label": policy.get("display_name"),
        "score_version": policy.get("score_version"),
        "score_method": policy.get("score_method"),
        "score_unit": "fraction_0_to_1",
        "scale_interpretation": policy.get("scale_interpretation") or "benchmark_attainment_index",
        "ceiling_display_policy": policy.get("ceiling_display_policy") or "label_suite_ceiling_not_perfection",
        "score": observed_score if score_ready else None,
        "observed_weighted_score": observed_score,
        "score_ready": score_ready,
        "reason": reason,
        "failed_gates": failed_gates,
        "coverage": {
            "observed_weight": round(observed_weight, 6),
            "total_weight": round(total_weight, 6),
            "coverage_fraction": coverage_fraction,
            "minimum_coverage_fraction": minimum_coverage,
            "complete": bool(total_weight and observed_weight >= total_weight),
            "missing_benchmark_ids": missing_benchmark_ids,
        },
        "eligibility": {
            "minimum_scored_components": minimum_components,
            "observed_scored_components": len(observed_components),
            "minimum_score_dimensions": minimum_dimensions,
            "observed_score_dimensions": observed_dimensions,
            "coverage_ready": coverage_ready,
            "diversity_ready": diversity_ready,
            "maximum_component_weight_fraction": maximum_influence,
            "influence_ready": influence_ready,
            "minimum_benchmark_tier": minimum_benchmark_tier,
            "observed_benchmark_tier": benchmark_tier,
            "benchmark_depth_ready": benchmark_depth_ready,
        },
        "components": components,
        "diagnostic_components": diagnostic_components,
        "ceiling": {
            "reached": ceiling_reached,
            "status": "suite_ceiling_reached" if ceiling_reached else "below_suite_ceiling",
            "label": "Suite ceiling reached" if ceiling_reached else "Below suite ceiling",
            "interpretation": (
                "Every observed headline component reached its benchmark maximum; this is a lower-bound ceiling signal, not proof of perfect model capability."
                if ceiling_reached
                else "The benchmark mix retained numeric headroom for this result."
            ),
        },
        "robustness": robustness,
        "confidence_basis": {
            "kind": "inspectable_evidence_basis_v1",
            "calibration_status": str(policy.get("calibration_status") or "not_psychometrically_calibrated"),
            "label": _confidence_basis_label(score_ready, coverage_fraction, robustness),
            "score_ready": score_ready,
            "coverage_fraction": coverage_fraction,
            "observed_component_count": len(observed_components),
            "observed_dimension_count": len(observed_dimensions),
            "repeat_measurements_included": False,
            "explanation": (
                "This basis describes benchmark coverage and component sensitivity; it is not a calibrated probability that the score is correct."
            ),
        },
        "claim_boundary": policy.get("claim_boundary"),
    }


def score_for_use_case(
    use_case: Optional[str],
    component_scores: Dict[str, float],
    catalog: Optional[Dict[str, Any]] = None,
    benchmark_tier: Optional[str] = None,
) -> Dict[str, Any]:
    payload = catalog or load_capability_catalog()
    surface_id = primary_surface_for_use_case(use_case) or infer_surface_from_components(component_scores, payload)
    return score_capability_surface(surface_id, component_scores, payload, benchmark_tier=benchmark_tier)


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


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return default
    return value


def _robustness_payload(components: List[Dict[str, Any]], observed_score: Optional[float], policy: Dict[str, Any]) -> Dict[str, Any]:
    leave_one_out = []
    if observed_score is not None and len(components) > 1:
        for omitted in components:
            remaining = [item for item in components if item["benchmark_id"] != omitted["benchmark_id"]]
            remaining_weight = sum(float(item["weight"]) for item in remaining)
            alternate = None
            if remaining_weight:
                alternate = round(
                    sum(float(item["score"]) * float(item["weight"]) for item in remaining) / remaining_weight,
                    6,
                )
            leave_one_out.append(
                {
                    "omitted_benchmark_id": omitted["benchmark_id"],
                    "score_without_component": alternate,
                    "absolute_delta": round(abs(observed_score - alternate), 6) if alternate is not None else None,
                }
            )
    deltas = [item["absolute_delta"] for item in leave_one_out if item["absolute_delta"] is not None]
    observed_weight = sum(float(item["weight"]) for item in components)
    shares = [
        (item["benchmark_id"], float(item["weight"]) / observed_weight)
        for item in components
        if observed_weight
    ]
    threshold = _bounded_fraction(policy.get("dominant_component_weight_fraction"), default=0.67)
    dominant = [benchmark_id for benchmark_id, share in shares if share > threshold]
    return {
        "method": "leave_one_component_out_v1",
        "leave_one_component_out": leave_one_out,
        "max_absolute_delta": round(max(deltas), 6) if deltas else None,
        "dominant_component_threshold": threshold,
        "dominant_component": bool(dominant),
        "dominant_benchmark_ids": dominant,
        "maximum_observed_weight_fraction": round(max((share for _, share in shares), default=0.0), 6) if shares else None,
        "claim_boundary": "Sensitivity describes this benchmark mix only and is not statistical uncertainty or psychometric calibration.",
    }


def _confidence_basis_label(score_ready: bool, coverage_fraction: float, robustness: Dict[str, Any]) -> str:
    if not score_ready:
        return "not_score_ready"
    if robustness.get("dominant_component"):
        return "multi_component_dominant"
    if coverage_fraction < 1.0:
        return "multi_component_partial_coverage"
    return "multi_component_complete_coverage"
