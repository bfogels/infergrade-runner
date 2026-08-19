"""Fail-closed benchmark readiness across catalog and corpus evidence."""

import math
from typing import Any, Dict, Iterable, List, Optional

from infergrade.benchmark_adequacy import (
    audit_benchmark_adequacy,
    validate_benchmark_adequacy_metadata,
)
from infergrade.benchmark_catalog import check_index, load_capability_catalog
from infergrade.benchmark_tier_adequacy import audit_benchmark_tier_adequacy
from infergrade.capability_calibration import (
    audit_capability_observations,
    extract_calibration_observations,
    policy_for_score_version,
)
from infergrade.statistical_bounds import wilson_score_upper_bound


def audit_benchmark_readiness(
    documents: Iterable[Dict[str, Any]],
    catalog: Optional[Dict[str, Any]] = None,
    surface_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Require structural coverage and empirical discrimination together."""
    payload = catalog or load_capability_catalog()
    document_list = list(documents)
    adequacy_metadata_errors = validate_benchmark_adequacy_metadata(payload)
    tier_adequacy = audit_benchmark_tier_adequacy(payload)
    tier_sampling_errors = list(tier_adequacy.get("errors") or [])
    metadata_errors = list(adequacy_metadata_errors) + [
        "tier_sampling:%s" % error for error in tier_sampling_errors
    ]
    metadata_valid = not metadata_errors
    adequacy = audit_benchmark_adequacy(payload, surface_id=surface_id)
    observations = extract_calibration_observations(document_list, catalog=payload)
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
        "artifact_spec_version": "0.8.0",
        "catalog_version": payload.get("catalog_version"),
        "catalog_metadata_valid": metadata_valid,
        "catalog_metadata_errors": metadata_errors,
        "catalog_tier_sampling_valid": not tier_sampling_errors,
        "catalog_tier_sampling_errors": tier_sampling_errors,
        "materialized_native_fixture_count": tier_adequacy.get(
            "materialized_native_fixture_count"
        ),
        "native_tier_coverage_contract_count": tier_adequacy.get(
            "native_tier_coverage_contract_count"
        ),
        "verified_static_fixture_manifest_count": tier_adequacy.get(
            "verified_static_fixture_manifest_count"
        ),
        "verified_tier_coverage_contract_count": tier_adequacy.get(
            "verified_tier_coverage_contract_count"
        ),
        "declared_selection_digest_algorithm_count": tier_adequacy.get(
            "declared_selection_digest_algorithm_count"
        ),
        "materialized_selection_digest_verified_count": tier_adequacy.get(
            "materialized_selection_digest_verified_count"
        ),
        "runtime_only_selection_digest_contract_count": tier_adequacy.get(
            "runtime_only_selection_digest_contract_count"
        ),
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
            "Readiness requires Runner catalog coverage, executable native and source-manifest tier-coverage "
            "contracts, reproducible selected-case digest algorithms, an "
            "empirical score distribution with the required diversity and headroom, and representative "
            "observations for every priority capability facet. "
            "A facet counts only when one protocol-identity cohort for a supporting check independently "
            "clears its observation, model-family, parameter-band, repeat, and headroom gates; standalone "
            "evidence must also meet the check's declared minimum task count. A Wilson upper bound keeps "
            "small samples from prematurely clearing the ceiling-rate gate. Missing "
            "result evidence fails closed. "
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
    composite_observations = [
        observation
        for observation in observations
        if observation.get("score_version") == score_version
        and not observation.get("integrity_conflicts")
    ]
    standalone_observations = [
        observation
        for observation in observations
        if observation.get("benchmark_id")
        and not observation.get("integrity_conflicts")
    ]
    surface_id = str(structural.get("surface_id") or "")
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
            _priority_check_metrics(
                check_id,
                surface_id,
                composite_observations,
                standalone_observations,
                policy,
                checks.get(check_id) or {},
            )
            for check_id in facet_check_ids
        ]
        ready = any(item["ready"] for item in check_metrics)
        observed_evidence_count = sum(
            item["observed_evidence_count"] for item in check_metrics
        )
        if ready:
            status = "ready"
        elif observed_evidence_count == 0:
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
            "Facet evidence is counted from completed component reports in score-ready results and "
            "scored standalone capability-run artifacts on the same declared surface. Undersized "
            "standalone runs remain reported but cannot satisfy a facet's evidence gate. Duplicate views "
            "are conservatively collapsed. Standalone evidence never enters composite-score calibration. "
            "Catalog support or a healthy composite distribution alone does not establish empirical "
            "facet coverage."
        ),
    }


def _priority_check_metrics(
    check_id: str,
    surface_id: str,
    composite_observations: List[Dict[str, Any]],
    standalone_observations: List[Dict[str, Any]],
    policy: Dict[str, Any],
    check: Dict[str, Any],
) -> Dict[str, Any]:
    declared_slice_policy = check.get("empirical_saturation_slice_policy")
    slice_policy = (
        dict(declared_slice_policy)
        if isinstance(declared_slice_policy, dict)
        else {}
    )
    calibration_policy = check.get("calibration_policy")
    minimum_task_count = (
        int((calibration_policy or {}).get("minimum_task_count") or 0)
        if isinstance(calibration_policy, dict)
        else 0
    )
    cohort_rows: Dict[str, List[tuple]] = {}
    for observation in composite_observations:
        for component in list(observation.get("components") or []):
            if (
                component.get("benchmark_id") != check_id
                or _attainment_score(component.get("score")) is None
            ):
                continue
            cohort_id = "composite:%s" % observation.get("score_version")
            cohort_rows.setdefault(cohort_id, []).append(
                (observation, float(component["score"]), "score_ready_composite")
            )
    matching_standalone = []
    undersized_standalone = []
    undersized_cohort_task_counts: Dict[str, List[int]] = {}
    for observation in standalone_observations:
        if (
            observation.get("benchmark_id") != check_id
            or observation.get("surface_id") != surface_id
            or _attainment_score(observation.get("score")) is None
        ):
            continue
        matching_standalone.append(observation)
        cohort_id = "standalone:%s" % observation.get("score_version")
        task_count = int(observation.get("task_count") or 0)
        if task_count < minimum_task_count:
            undersized_standalone.append(observation)
            undersized_cohort_task_counts.setdefault(cohort_id, []).append(
                task_count
            )
            continue
        cohort_rows.setdefault(cohort_id, []).append(
            (observation, float(observation["score"]), "standalone_capability_run")
        )
    cohorts = [
        _priority_cohort_metrics(
            cohort_id,
            rows,
            policy,
            slice_policy,
        )
        for cohort_id, rows in sorted(cohort_rows.items())
    ]
    selected = max(cohorts, key=_priority_cohort_rank) if cohorts else _priority_cohort_metrics(
        "none",
        [],
        policy,
        slice_policy,
    )
    selected_metrics = {
        key: value for key, value in selected.items() if key != "cohort_id"
    }
    composite_observation_count = sum(
        1
        for rows in cohort_rows.values()
        for _, _, source_kind in rows
        if source_kind == "score_ready_composite"
    )
    if (
        not selected_metrics["observation_count"]
        and undersized_standalone
        and not composite_observation_count
    ):
        selected_metrics["status"] = "insufficient_evidence"
        selected_metrics["ready"] = False
        selected_metrics["blockers"] = ["standalone_task_count_below_minimum"]
    return {
        "check_id": check_id,
        **selected_metrics,
        "minimum_task_count": minimum_task_count,
        "observed_evidence_count": (
            composite_observation_count + len(matching_standalone)
        ),
        "observed_standalone_capability_run_count": len(matching_standalone),
        "excluded_standalone_below_minimum_task_count": len(
            undersized_standalone
        ),
        "maximum_observed_standalone_task_count": (
            max(
                int(observation.get("task_count") or 0)
                for observation in matching_standalone
            )
            if matching_standalone
            else None
        ),
        "undersized_standalone_evidence_cohorts": [
            {
                "evidence_cohort": cohort_id,
                "observation_count": len(task_counts),
                "minimum_observed_task_count": min(task_counts),
                "maximum_observed_task_count": max(task_counts),
            }
            for cohort_id, task_counts in sorted(
                undersized_cohort_task_counts.items()
            )
        ],
        "selected_evidence_cohort": (
            selected["cohort_id"] if selected["cohort_id"] != "none" else None
        ),
        "evidence_cohorts": cohorts,
        "unpooled_alternate_observation_count": sum(
            int(item.get("observation_count") or 0)
            for item in cohorts
            if item["cohort_id"] != selected["cohort_id"]
        ),
    }


def _priority_cohort_metrics(
    cohort_id: str,
    raw_rows: List[tuple],
    policy: Dict[str, Any],
    slice_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    rows = _deduplicate_priority_check_rows(raw_rows)
    scores = [score for _, score, _ in rows]
    families = {
        str(observation.get("model_family") or "unknown")
        for observation, _, _ in rows
    } - {"unknown"}
    bands = {
        str(observation.get("parameter_band") or "unknown")
        for observation, _, _ in rows
    } - {"unknown"}
    setup_groups: Dict[Any, set] = {}
    for observation, _, _ in rows:
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
    ceiling_confidence_level = float(
        policy.get("ceiling_fraction_confidence_level") or 0.95
    )
    ceiling_fraction_upper_bound = wilson_score_upper_bound(
        ceiling_count,
        len(scores),
        ceiling_confidence_level,
    )
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
    elif (
        ceiling_fraction_upper_bound is not None
        and ceiling_fraction_upper_bound
        > float(policy.get("maximum_suite_ceiling_fraction") or 0.0)
    ):
        blockers.append("insufficient_suite_ceiling_fraction_confidence")
    required_slice_metrics = {}
    for slice_id in list((slice_policy or {}).get("required_slices") or []):
        slice_rows = []
        for observation, _, source_kind in rows:
            saturation_slices = observation.get("saturation_slices")
            if not isinstance(saturation_slices, dict):
                continue
            slice_item = saturation_slices.get(slice_id)
            if not isinstance(slice_item, dict):
                continue
            slice_score = _attainment_score(slice_item.get("score"))
            if slice_score is not None:
                slice_rows.append((observation, slice_score, source_kind))
        metrics = _priority_cohort_metrics(
            "%s:slice:%s" % (cohort_id, slice_id),
            slice_rows,
            policy,
        )
        required_slice_metrics[str(slice_id)] = {
            key: value for key, value in metrics.items() if key != "cohort_id"
        }
        if metrics["status"] == "unobserved":
            blockers.append("required_slice_unobserved:%s" % slice_id)
        elif metrics["status"] == "insufficient_evidence":
            blockers.append("required_slice_evidence_insufficient:%s" % slice_id)
        elif metrics["status"] == "saturation_risk":
            blockers.append("required_slice_saturation_risk:%s" % slice_id)
    insufficient = any(
        item.startswith("insufficient_") and item != "insufficient_suite_headroom"
        for item in blockers
    ) or any(
        item.startswith("required_slice_unobserved:")
        or item.startswith("required_slice_evidence_insufficient:")
        for item in blockers
    )
    required_slice_evidence_complete = all(
        item["status"] in {"ready", "saturation_risk"}
        for item in required_slice_metrics.values()
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
        "cohort_id": cohort_id,
        "status": status,
        "ready": not blockers,
        "observation_count": len(scores),
        "score_ready_composite_observation_count": sum(
            1 for _, _, source_kind in rows if source_kind == "score_ready_composite"
        ),
        "standalone_capability_run_observation_count": sum(
            1 for _, _, source_kind in rows if source_kind == "standalone_capability_run"
        ),
        "duplicate_view_count": len(raw_rows) - len(rows),
        "model_family_count": len(families),
        "parameter_band_count": len(bands),
        "independently_replicated_setup_count": independent_setups,
        "suite_ceiling_fraction": ceiling_fraction,
        "suite_ceiling_fraction_confidence_level": ceiling_confidence_level,
        "suite_ceiling_fraction_wilson_upper_bound": (
            round(ceiling_fraction_upper_bound, 6)
            if ceiling_fraction_upper_bound is not None
            else None
        ),
        "headroom_to_suite_ceiling": headroom,
        "required_slice_metrics": required_slice_metrics,
        "required_slice_evidence_complete": required_slice_evidence_complete,
        "blockers": blockers,
    }


def _priority_cohort_rank(cohort: Dict[str, Any]) -> tuple:
    return (
        int(cohort.get("ready") is True),
        int(cohort.get("required_slice_evidence_complete") is True),
        int(cohort.get("observation_count") or 0),
        int(cohort.get("model_family_count") or 0),
        int(cohort.get("parameter_band_count") or 0),
        int(cohort.get("independently_replicated_setup_count") or 0),
        float(cohort.get("headroom_to_suite_ceiling") or 0.0),
        int(str(cohort.get("cohort_id") or "").startswith("composite:")),
    )


def _deduplicate_priority_check_rows(rows: List[tuple]) -> List[tuple]:
    """Collapse duplicate artifact views without inventing independent repeats."""
    grouped: Dict[Any, List[tuple]] = {}
    order = []
    for row in rows:
        observation, score, _ = row
        identities = tuple(sorted(set(observation.get("model_identities") or [])))
        if not identities:
            identities = (str(observation.get("model_family") or "unknown"),)
        key = (identities, round(float(score), 9))
        if key not in grouped:
            order.append(key)
            grouped[key] = []
        grouped[key].append(row)
    deduplicated = []
    for key in order:
        candidates = grouped[key]
        verified_by_group = {}
        unverified = []
        for row in candidates:
            observation = row[0]
            group_id = (
                str(observation.get("evidence_group_id") or "").strip()
                if observation.get("evidence_group_verified") is True
                else ""
            )
            if group_id:
                current = verified_by_group.get(group_id)
                if current is None or _priority_row_rank(row) > _priority_row_rank(current):
                    verified_by_group[group_id] = row
            else:
                unverified.append(row)
        if verified_by_group:
            deduplicated.extend(verified_by_group.values())
        elif unverified:
            deduplicated.append(max(unverified, key=_priority_row_rank))
    return deduplicated


def _priority_row_rank(row: tuple) -> tuple:
    observation, _, source_kind = row
    return (
        int(source_kind == "score_ready_composite"),
        len(dict(observation.get("saturation_slices") or {})),
        int(bool(observation.get("quantization_scheme"))),
        int(str(observation.get("parameter_band") or "unknown") != "unknown"),
        int(str(observation.get("model_family") or "unknown") != "unknown"),
    )


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


def _attainment_score(value: Any) -> Optional[float]:
    number = _number(value)
    if number is None or not 0.0 <= number <= 1.0:
        return None
    return number
