"""Catalog-level benchmark representativeness and headroom-risk audits."""

from typing import Any, Dict, List, Optional, Set

from infergrade.benchmark_catalog import (
    check_index,
    load_capability_catalog,
    surface_score_policy_index,
)


REFRESHABLE_TEMPORAL_SCOPES = {"rolling_window", "periodically_refreshed_snapshot"}


def audit_benchmark_adequacy(
    catalog: Optional[Dict[str, Any]] = None,
    surface_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Report what the catalog covers without treating metadata as run evidence."""
    payload = catalog or load_capability_catalog()
    checks = check_index(payload)
    planned = {
        str(item.get("check_id")): dict(item)
        for item in list(payload.get("planned_benchmark_candidates") or [])
        if item.get("check_id")
    }
    surfaces = []
    for candidate_surface_id, score_policy in sorted(surface_score_policy_index(payload).items()):
        if surface_id and candidate_surface_id != surface_id:
            continue
        surfaces.append(
            _surface_adequacy(
                candidate_surface_id,
                score_policy,
                checks,
                planned,
            )
        )
    scoped_ready = bool(surfaces) and all(item["scoped_claim_coverage_ready"] for item in surfaces)
    broad_ready = bool(surfaces) and all(item["broad_surface_coverage_ready"] for item in surfaces)
    return {
        "artifact_kind": "benchmark_adequacy_audit",
        "artifact_spec_version": "0.1.0",
        "catalog_version": payload.get("catalog_version"),
        "surface_filter": surface_id,
        "scoped_claim_coverage_ready": scoped_ready,
        "broad_surface_coverage_ready": broad_ready,
        "surfaces": surfaces,
        "interpretation": (
            "This catalog audit distinguishes narrow claim coverage, broader capability-facet coverage, "
            "freshness, and known saturation risk. It does not replace result-corpus calibration and does "
            "not prove that any benchmark is empirically discriminative."
        ),
    }


def validate_benchmark_adequacy_metadata(catalog: Optional[Dict[str, Any]] = None) -> List[str]:
    """Validate representativeness metadata used by the adequacy audit."""
    payload = catalog or load_capability_catalog()
    failures: List[str] = []
    checks = check_index(payload)
    planned_ids = {
        str(item.get("check_id"))
        for item in list(payload.get("planned_benchmark_candidates") or [])
        if item.get("check_id")
    }
    for surface_id, score_policy in surface_score_policy_index(payload).items():
        policy = score_policy.get("representativeness_policy")
        if not isinstance(policy, dict):
            failures.append(f"{surface_id}: missing representativeness_policy")
            continue
        if not str(policy.get("policy_id") or "").strip():
            failures.append(f"{surface_id}: representativeness policy_id must be non-empty")
        scoped = _string_set(policy.get("scoped_claim_facets"))
        priority = _string_set(policy.get("priority_facets"))
        if not _non_empty_string_list(policy.get("scoped_claim_facets")):
            failures.append(f"{surface_id}: scoped_claim_facets must be a non-empty string array")
        if not _non_empty_string_list(policy.get("priority_facets")):
            failures.append(f"{surface_id}: priority_facets must be a non-empty string array")
        if not scoped.issubset(priority):
            failures.append(f"{surface_id}: scoped_claim_facets must be included in priority_facets")
        minimum_refreshable = policy.get("minimum_refreshable_priority_facets")
        if isinstance(minimum_refreshable, bool) or not isinstance(minimum_refreshable, int) or minimum_refreshable < 0:
            failures.append(f"{surface_id}: minimum_refreshable_priority_facets must be a non-negative integer")
        for field in ("supporting_check_ids", "planned_check_ids"):
            ids = policy.get(field)
            if not isinstance(ids, list) or not all(isinstance(item, str) and item.strip() for item in ids):
                failures.append(f"{surface_id}: {field} must be a string array")
                continue
            known = set(checks) if field == "supporting_check_ids" else planned_ids
            for check_id in ids:
                if check_id not in known:
                    failures.append(f"{surface_id}: unknown {field[:-1]} {check_id!r}")
        supporting_ids = set(policy.get("supporting_check_ids") or [])
        weighted_ids = {
            check_id
            for check_id, check in checks.items()
            if check.get("surface_id") == surface_id
            and check.get("evidence_kind") == "capability"
            and float(check.get("primary_score_weight") or 0.0) > 0.0
            and check.get("score_role") != "diagnostic_only"
        }
        omitted_weighted = sorted(weighted_ids - supporting_ids)
        if omitted_weighted:
            failures.append(
                f"{surface_id}: supporting_check_ids omits weighted checks: {', '.join(omitted_weighted)}"
            )
        declared_ids = list(policy.get("supporting_check_ids") or []) + list(policy.get("planned_check_ids") or [])
        declared_facets: Set[str] = set()
        for check_id in declared_ids:
            item = checks.get(check_id) or next(
                (
                    candidate
                    for candidate in list(payload.get("planned_benchmark_candidates") or [])
                    if candidate.get("check_id") == check_id
                ),
                {},
            )
            facets = _string_set(item.get("capability_facets"))
            if not facets:
                failures.append(f"{check_id}: capability_facets must be a non-empty string array")
            declared_facets.update(facets)
            if item.get("surface_id") not in (None, surface_id):
                failures.append(f"{surface_id}: {check_id} belongs to a different surface")
            temporal_scope = str(item.get("temporal_scope") or "")
            if temporal_scope not in {"static_pinned", *REFRESHABLE_TEMPORAL_SCOPES}:
                failures.append(f"{check_id}: temporal_scope must be declared")
        unknown_facets = sorted(declared_facets - priority)
        if unknown_facets:
            failures.append(f"{surface_id}: declared checks use unrecognized priority facets: {', '.join(unknown_facets)}")
    return failures


def _surface_adequacy(
    surface_id: str,
    score_policy: Dict[str, Any],
    checks: Dict[str, Dict[str, Any]],
    planned: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    policy = dict(score_policy.get("representativeness_policy") or {})
    supporting = [checks[check_id] for check_id in policy.get("supporting_check_ids") or [] if check_id in checks]
    planned_checks = [planned[check_id] for check_id in policy.get("planned_check_ids") or [] if check_id in planned]
    headline = [
        item
        for item in supporting
        if float(item.get("primary_score_weight") or 0.0) > 0.0 and item.get("score_role") != "diagnostic_only"
    ]
    diagnostics = [item for item in supporting if item not in headline]
    scoped_facets = _string_set(policy.get("scoped_claim_facets"))
    priority_facets = _string_set(policy.get("priority_facets"))
    headline_facets = _facets(headline)
    runnable_facets = _facets(supporting)
    planned_facets = _facets(planned_checks)
    missing_scoped = sorted(scoped_facets - headline_facets)
    missing_priority = sorted(priority_facets - runnable_facets)
    planned_only = sorted((priority_facets & planned_facets) - runnable_facets)
    unplanned = sorted(priority_facets - runnable_facets - planned_facets)
    refreshable_runnable = sorted(
        _facets(item for item in supporting if item.get("temporal_scope") in REFRESHABLE_TEMPORAL_SCOPES)
    )
    refreshable_planned = sorted(
        _facets(item for item in planned_checks if item.get("temporal_scope") in REFRESHABLE_TEMPORAL_SCOPES)
    )
    minimum_refreshable = int(policy.get("minimum_refreshable_priority_facets") or 0)
    freshness_ready = len(set(refreshable_runnable) & priority_facets) >= minimum_refreshable
    headline_saturation_risks = sorted(
        str(item.get("check_id"))
        for item in headline
        if _known_saturation_risk(item)
    )
    diagnostic_saturation_risks = sorted(
        str(item.get("check_id"))
        for item in diagnostics
        if _known_saturation_risk(item)
    )
    scoped_ready = not missing_scoped
    broad_ready = (
        scoped_ready
        and not missing_priority
        and freshness_ready
        and not headline_saturation_risks
        and not diagnostic_saturation_risks
    )
    if not scoped_ready:
        status = "scoped_claim_coverage_gap"
    elif broad_ready:
        status = "broad_surface_catalog_ready"
    else:
        status = "scoped_claim_only"
    return {
        "surface_id": surface_id,
        "score_version": score_policy.get("score_version"),
        "policy_id": policy.get("policy_id"),
        "status": status,
        "scoped_claim_coverage_ready": scoped_ready,
        "broad_surface_coverage_ready": broad_ready,
        "scoped_claim_facets": sorted(scoped_facets),
        "priority_facets": sorted(priority_facets),
        "headline_facets_covered": sorted(headline_facets),
        "diagnostic_facets_covered": sorted(_facets(diagnostics)),
        "missing_scoped_claim_facets": missing_scoped,
        "missing_priority_facets": missing_priority,
        "planned_only_priority_facets": planned_only,
        "unplanned_priority_facets": unplanned,
        "headline_check_ids": sorted(str(item.get("check_id")) for item in headline),
        "diagnostic_check_ids": sorted(str(item.get("check_id")) for item in diagnostics),
        "planned_check_ids": sorted(str(item.get("check_id")) for item in planned_checks),
        "known_headline_saturation_risks": headline_saturation_risks,
        "known_diagnostic_saturation_risks": diagnostic_saturation_risks,
        "distribution_calibration_status": score_policy.get("distribution_calibration_status"),
        "freshness": {
            "minimum_refreshable_priority_facets": minimum_refreshable,
            "runnable_refreshable_facets": refreshable_runnable,
            "planned_refreshable_facets": refreshable_planned,
            "ready": freshness_ready,
        },
        "claim_boundary": score_policy.get("claim_boundary"),
    }


def _known_saturation_risk(check: Dict[str, Any]) -> bool:
    status = str(check.get("discrimination_status") or "").lower()
    if "saturat" in status or "ceiling" in status:
        return True
    decision = str((check.get("saturation_evidence") or {}).get("decision") or "").lower()
    return "saturat" in decision or "replacement" in decision or "demotion" in decision


def _facets(items: Any) -> Set[str]:
    facets: Set[str] = set()
    for item in items:
        facets.update(_string_set(item.get("capability_facets")))
    return facets


def _string_set(value: Any) -> Set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if isinstance(item, str) and item.strip()}


def _non_empty_string_list(value: Any) -> bool:
    return bool(value) and isinstance(value, list) and all(
        isinstance(item, str) and item.strip() for item in value
    )
