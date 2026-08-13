"""Fail-closed benchmark readiness across catalog and corpus evidence."""

from typing import Any, Dict, Iterable, List, Optional

from infergrade.benchmark_adequacy import (
    audit_benchmark_adequacy,
    validate_benchmark_adequacy_metadata,
)
from infergrade.benchmark_catalog import load_capability_catalog
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
        scoped_ready = (
            metadata_valid
            and bool(structural.get("scoped_claim_coverage_ready"))
            and empirical_ready
        )
        broad_ready = (
            metadata_valid
            and bool(structural.get("broad_surface_coverage_ready"))
            and empirical_ready
        )
        scoped_blockers = _scoped_claim_blockers(structural, empirical, metadata_errors)
        broad_blockers = _broad_surface_blockers(structural, scoped_blockers)
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
                "scoped_claim_blockers": scoped_blockers,
                "broad_surface_blockers": broad_blockers,
                "catalog_adequacy": structural,
                "empirical_calibration": empirical,
            }
        )
    scoped_ready = bool(surfaces) and all(item["scoped_claim_ready"] for item in surfaces)
    broad_ready = bool(surfaces) and all(item["broad_surface_ready"] for item in surfaces)
    return {
        "artifact_kind": "benchmark_readiness_audit",
        "artifact_spec_version": "0.1.0",
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
            "Readiness requires both Runner catalog coverage and an empirical score distribution with "
            "the required diversity and headroom. Missing result evidence fails closed. Raw benchmark "
            "attainment is never curved, capped, or rescaled by this audit."
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
    return blockers
