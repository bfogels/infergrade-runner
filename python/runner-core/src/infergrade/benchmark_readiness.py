"""Fail-closed benchmark readiness across catalog and corpus evidence."""

import math
from typing import Any, Dict, Iterable, List, Optional

from infergrade.benchmark_adequacy import (
    audit_benchmark_adequacy,
    validate_benchmark_adequacy_metadata,
)
from infergrade.benchmark_catalog import check_index, load_capability_catalog
from infergrade.capability_calibration import (
    audit_capability_observations,
    extract_calibration_observations,
    policy_for_score_version,
)


def audit_benchmark_readiness(
    documents: Iterable[Dict[str, Any]],
    catalog: Optional[Dict[str, Any]] = None,
    surface_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Require structural coverage and empirical discrimination together."""
    payload = catalog or load_capability_catalog()
    document_list = list(documents)
    metadata_errors = validate_benchmark_adequacy_metadata(payload)
    metadata_valid = not metadata_errors
    adequacy = audit_benchmark_adequacy(payload, surface_id=surface_id)
    observations = extract_calibration_observations(document_list)
    surfaces = []
    for structural in adequacy["surfaces"]:
        score_version = str(structural.get("score_version") or "")
        empirical = audit_capability_observations(
            observations,
            score_version,
            policy=policy_for_score_version(score_version, catalog=payload),
            catalog=payload,
        )
        empirical_ready = bool(empirical.get("headline_ready"))
        priority_facet_evidence = _audit_priority_facet_evidence(
            observations,
            structural,
            payload,
        )
        priority_facets_ready = bool(priority_facet_evidence.get("ready"))
        scoped_ready = (
            metadata_valid
            and bool(structural.get("scoped_claim_coverage_ready"))
            and empirical_ready
        )
        broad_ready = (
            metadata_valid
            and bool(structural.get("broad_surface_coverage_ready"))
            and empirical_ready
            and priority_facets_ready
        )
        scoped_blockers = _scoped_claim_blockers(structural, empirical, metadata_errors)
        broad_blockers = _broad_surface_blockers(
            structural,
            scoped_blockers,
            priority_facet_evidence,
        )
        surfaces.append(
            {
                "surface_id": structural.get("surface_id"),
                "score_version": score_version,
                "status": (
                    "broad_surface_ready"
                    if broad_ready
                    else "scoped_claim_ready"
                    if scoped_ready
                    else "not_ready"
                ),
                "scoped_claim_ready": scoped_ready,
                "broad_surface_ready": broad_ready,
                "structural_scoped_claim_coverage_ready": bool(
                    structural.get("scoped_claim_coverage_ready")
                ),
                "structural_broad_surface_coverage_ready": bool(
                    structural.get("broad_surface_coverage_ready")
                ),
                "empirical_distribution_ready": empirical_ready,
                "empirical_priority_facet_coverage_ready": priority_facets_ready,
                "scoped_claim_blockers": scoped_blockers,
                "broad_surface_blockers": broad_blockers,
                "catalog_adequacy": structural,
                "empirical_calibration": empirical,
                "empirical_priority_facet_evidence": priority_facet_evidence,
            }
        )
    scoped_ready = bool(surfaces) and all(item["scoped_claim_ready"] for item in surfaces)
    broad_ready = bool(surfaces) and all(item["broad_surface_ready"] for item in surfaces)
    return {
        "artifact_kind": "benchmark_readiness_audit",
        "artifact_spec_version": "0.2.0",
        "catalog_version": payload.get("catalog_version"),
        "catalog_metadata_valid": metadata_valid,
        "catalog_metadata_errors": metadata_errors,
        "surface_filter": surface_id,
        "input_document_count": len(document_list),
        "calibration_observation_count": len(observations),
        "scoped_claim_ready": scoped_ready,
        "broad_surface_ready": broad_ready,
        "status": (
            "broad_surface_ready"
            if broad_ready
            else "scoped_claim_ready"
            if scoped_ready
            else "not_ready"
        ),
        "surfaces": surfaces,
        "interpretation": (
            "Readiness requires Runner catalog coverage, an empirical score distribution with the required "
            "diversity and headroom, and representative observations for every priority capability facet. "
            "A facet counts only when at least one supporting check independently clears its observation, "
            "model-family, parameter-band, repeat, and headroom gates. Missing result evidence fails closed. "
            "Raw benchmark attainment is never curved, capped, or rescaled by this audit."
        ),
    }


def _scoped_claim_blockers(
    structural: Dict[str, Any],
    empirical: Dict[str, Any],
    metadata_errors: List[str],
) -> List[str]:
    blockers = ["catalog_metadata:%s" % error for error in metadata_errors]
    blockers.extend(
        "catalog:missing_scoped_claim_facet:%s" % facet
        for facet in list(structural.get("missing_scoped_claim_facets") or [])
    )
    blockers.extend(
        "calibration:%s" % blocker
        for blocker in list(empirical.get("blockers") or [])
    )
    return blockers


def _broad_surface_blockers(
    structural: Dict[str, Any],
    scoped_blockers: List[str],
    priority_facet_evidence: Dict[str, Any],
) -> List[str]:
    blockers = list(scoped_blockers)
    blockers.extend(
        "catalog:missing_priority_facet:%s" % facet
        for facet in list(structural.get("missing_priority_facets") or [])
    )
    if not (structural.get("freshness") or {}).get("ready"):
        blockers.append("catalog:refreshable_priority_facet_requirement_unmet")
    blockers.extend(
        "catalog:known_headline_saturation_risk:%s" % check_id
        for check_id in list(structural.get("known_headline_saturation_risks") or [])
    )
    blockers.extend(
        "catalog:known_diagnostic_saturation_risk:%s" % check_id
        for check_id in list(structural.get("known_diagnostic_saturation_risks") or [])
    )
    blockers.extend(
        "corpus:%s" % blocker
        for blocker in list(priority_facet_evidence.get("blockers") or [])
    )
    return blockers


def _audit_priority_facet_evidence(
    observations: List[Dict[str, Any]],
    structural: Dict[str, Any],
    catalog: Dict[str, Any],
) -> Dict[str, Any]:
    """Require one empirically adequate supporting check for every priority facet."""
    score_version = str(structural.get("score_version") or "")
    eligible = [
        observation
        for observation in observations
        if observation.get("score_version") == score_version
        and not observation.get("integrity_conflicts")
    ]
    checks = check_index(catalog)
    supporting_ids = set(structural.get("headline_check_ids") or []) | set(
        structural.get("diagnostic_check_ids") or []
    )
    policy = dict(structural.get("empirical_priority_facet_policy") or {})
    facets = []
    blockers = []
    for facet in list(structural.get("priority_facets") or []):
        facet_check_ids = sorted(
            check_id
            for check_id in supporting_ids
            if facet in set((checks.get(check_id) or {}).get("capability_facets") or [])
        )
        check_metrics = [
            _priority_check_metrics(check_id, eligible, policy)
            for check_id in facet_check_ids
        ]
        ready = any(item["ready"] for item in check_metrics)
        observation_count = sum(item["observation_count"] for item in check_metrics)
        if ready:
            status = "ready"
        elif observation_count == 0:
            status = "unobserved"
            blockers.append("priority_facet_unobserved:%s" % facet)
        elif any(
            item["status"] == "saturation_risk"
            for item in check_metrics
        ):
            status = "saturation_risk"
            blockers.append("priority_facet_saturation_risk:%s" % facet)
        else:
            status = "insufficient_evidence"
            blockers.append("priority_facet_evidence_insufficient:%s" % facet)
        facets.append(
            {
                "facet": facet,
                "status": status,
                "ready": ready,
                "supporting_check_ids": facet_check_ids,
                "checks": check_metrics,
            }
        )
    return {
        "policy": policy,
        "ready": bool(facets) and all(item["ready"] for item in facets),
        "facets": facets,
        "blockers": blockers,
        "claim_boundary": (
            "Facet evidence is counted only from completed component reports in score-ready result "
            "observations without integrity conflicts. Catalog support or a healthy composite score "
            "distribution alone does not establish empirical facet coverage."
        ),
    }


def _priority_check_metrics(
    check_id: str,
    observations: List[Dict[str, Any]],
    policy: Dict[str, Any],
) -> Dict[str, Any]:
    rows = [
        (observation, float(component["score"]))
        for observation in observations
        for component in list(observation.get("components") or [])
        if component.get("benchmark_id") == check_id
        and _number(component.get("score")) is not None
    ]
    scores = [score for _, score in rows]
    families = {
        str(observation.get("model_family") or "unknown")
        for observation, _ in rows
    } - {"unknown"}
    bands = {
        str(observation.get("parameter_band") or "unknown")
        for observation, _ in rows
    } - {"unknown"}
    setup_groups: Dict[Any, set] = {}
    for observation, _ in rows:
        group_id = (
            str(observation.get("evidence_group_id") or "").strip()
            if observation.get("evidence_group_verified") is True
            else ""
        )
        if group_id:
            setup_groups.setdefault(_observation_setup_key(observation), set()).add(group_id)
    independent_setups = sum(1 for groups in setup_groups.values() if len(groups) >= 2)
    ceiling_count = sum(1 for score in scores if math.isclose(score, 1.0, abs_tol=1e-9))
    ceiling_fraction = round(ceiling_count / float(len(scores)), 6) if scores else None
    maximum = max(scores) if scores else None
    headroom = round(1.0 - maximum, 6) if maximum is not None else None
    blockers = []
    for metric, value, threshold in (
        ("observations", len(scores), "minimum_observations"),
        ("model_families", len(families), "minimum_model_families"),
        ("parameter_bands", len(bands), "minimum_parameter_bands"),
        (
            "independently_replicated_setups",
            independent_setups,
            "minimum_independently_replicated_setups",
        ),
    ):
        if value < int(policy.get(threshold) or 0):
            blockers.append("insufficient_%s" % metric)
    saturation_blocked = (
        ceiling_fraction is not None
        and ceiling_fraction > float(policy.get("maximum_suite_ceiling_fraction") or 0.0)
    )
    if saturation_blocked:
        blockers.append("suite_ceiling_fraction_above_limit")
    elif (
        headroom is not None
        and headroom < float(policy.get("minimum_suite_headroom") or 0.0)
    ):
        blockers.append("insufficient_suite_headroom")
    insufficient = any(
        item.startswith("insufficient_") and item != "insufficient_suite_headroom"
        for item in blockers
    )
    status = (
        "unobserved"
        if not scores
        else "insufficient_evidence"
        if insufficient
        else "saturation_risk"
        if blockers
        else "ready"
    )
    return {
        "check_id": check_id,
        "status": status,
        "ready": not blockers,
        "observation_count": len(scores),
        "model_family_count": len(families),
        "parameter_band_count": len(bands),
        "independently_replicated_setup_count": independent_setups,
        "suite_ceiling_fraction": ceiling_fraction,
        "headroom_to_suite_ceiling": headroom,
        "blockers": blockers,
    }


def _observation_setup_key(observation: Dict[str, Any]) -> tuple:
    identities = tuple(sorted(set(observation.get("model_identities") or [])))
    if not identities:
        identities = (str(observation.get("model_family") or "unknown"),)
    return identities + (str(observation.get("quantization_scheme") or "unknown"),)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None
