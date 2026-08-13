"""Corpus-level capability headroom audits.

The audit never remaps or caps a model score. It tests whether a raw benchmark
attainment distribution is broad enough to support a calibrated headline.
"""

import json
import math
import os
import re
from collections import Counter
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Optional

from infergrade.benchmark_catalog import check_index, load_capability_catalog, surface_score_policy_index


DEFAULT_POLICY = {
    "policy_id": "capability_headroom_gate_v1",
    "minimum_observations": 20,
    "minimum_model_families": 5,
    "minimum_parameter_bands": 3,
    "minimum_distinct_scores": 6,
    "maximum_suite_ceiling_fraction": 0.2,
    "maximum_largest_family_fraction": 0.4,
}
TRUSTED_EVIDENCE_GROUP_PROVENANCE = "trusted_corpus_operator_v1"


def load_json_documents(paths: Iterable[str]) -> List[Dict[str, Any]]:
    documents: List[Dict[str, Any]] = []
    for path in paths:
        expanded = os.path.abspath(os.path.expanduser(path))
        candidates = []
        if os.path.isdir(expanded):
            for root, _, filenames in os.walk(expanded):
                candidates.extend(os.path.join(root, name) for name in filenames if name.endswith(".json"))
        else:
            candidates.append(expanded)
        for candidate in sorted(candidates):
            try:
                with open(candidate, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, ValueError, TypeError):
                continue
            documents.extend(_document_items(payload, candidate))
    return documents


def _document_items(payload: Any, source: str) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item, _source=source) for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("results", "items"):
        if isinstance(payload.get(key), list):
            return [dict(item, _source=source) for item in payload[key] if isinstance(item, dict)]
    return [dict(payload, _source=source)]


def extract_calibration_observations(
    documents: Iterable[Dict[str, Any]],
    score_version: Optional[str] = None,
    benchmark_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    observations: List[Dict[str, Any]] = []
    for document in documents:
        source = str(document.get("_source") or "")
        if document.get("artifact_kind") == "capability_run":
            observation = _component_observation(document, source)
            if observation:
                observations.append(observation)
            continue
        if document.get("artifact_kind") == "capability_summary":
            for surface in list(document.get("surfaces") or []):
                observation = _surface_observation(surface, document, source)
                if observation:
                    observations.append(observation)
            continue
        capability = document.get("capability") if isinstance(document.get("capability"), dict) else {}
        details = capability.get("capability_score_details") if isinstance(capability.get("capability_score_details"), dict) else {}
        version = str(details.get("score_version") or document.get("capability_score_version") or "")
        score = _number(details.get("raw_attainment"))
        if score is None:
            score = _number(details.get("observed_weighted_score"))
        if score is None:
            score = _number(details.get("score"))
        if score is None:
            score = _number(capability.get("capability_score"))
        if score is None:
            score = _number(document.get("capability_score"))
        score_ready = details.get("score_ready") if "score_ready" in details else document.get("capability_score_ready")
        if not version or score is None or score_ready is not True:
            continue
        observation_id = str(document.get("result_id") or document.get("bundle_id") or source)
        family = _nested(document, "ontology", "model_family", "family_name") or document.get("model_family")
        scale = _nested(document, "ontology", "model_family", "parameter_scale") or document.get("parameter_scale")
        checkpoint_name = _nested(document, "ontology", "checkpoint", "checkpoint_name") or document.get("checkpoint_name")
        observations.append(
            {
                "observation_id": observation_id,
                "score_version": version,
                "surface_id": details.get("surface_id") or document.get("capability_score_surface_id"),
                "score": score,
                "model_family": str(family or "unknown"),
                "parameter_band": _parameter_band(scale or checkpoint_name),
                "model_identities": sorted(_model_identities(document.get("model_id"), document.get("model"), checkpoint_name)),
                "quantization_scheme": str(
                    _nested(document, "ontology", "quantization", "quantization_scheme")
                    or document.get("quantization_scheme")
                    or ""
                ).lower(),
                **_evidence_group_observation(document),
                "components": _component_score_observations(document, capability),
                "source": source,
            }
        )
    deduplicated_by_key: Dict[Any, Dict[str, Any]] = {}
    key_order = []
    for item in observations:
        key = (item.get("score_version"), _observation_scope(str(item.get("source") or "")) or item.get("observation_id"))
        existing = deduplicated_by_key.get(key)
        if existing is None:
            key_order.append(key)
            deduplicated_by_key[key] = item
            continue
        conflicts = sorted(set(
            list(existing.get("integrity_conflicts") or [])
            + list(item.get("integrity_conflicts") or [])
            + _duplicate_integrity_conflicts(existing, item)
        ))
        if _observation_detail_rank(item) > _observation_detail_rank(existing):
            # A bundle can contain a compact capability_summary and a richer
            # normalized Result for the same score version. Keep one corpus
            # observation while preserving component and exact setup detail.
            existing = item
        if conflicts:
            existing = dict(existing, integrity_conflicts=conflicts)
        deduplicated_by_key[key] = existing
    deduplicated = [deduplicated_by_key[key] for key in key_order]
    if score_version:
        return [item for item in deduplicated if item.get("score_version") == score_version]
    if benchmark_id:
        return [item for item in deduplicated if item.get("benchmark_id") == benchmark_id]
    return deduplicated


def _observation_detail_rank(observation: Dict[str, Any]) -> tuple:
    """Prefer richer duplicate views without changing corpus cardinality."""
    return (
        len(list(observation.get("components") or [])),
        len(list(observation.get("model_identities") or [])),
        int(observation.get("evidence_group_verified") is True),
        int(bool(observation.get("quantization_scheme"))),
        int(str(observation.get("model_family") or "unknown") != "unknown"),
        int(str(observation.get("parameter_band") or "unknown") != "unknown"),
    )


def _duplicate_integrity_conflicts(left: Dict[str, Any], right: Dict[str, Any]) -> List[str]:
    """Identify contradictory claims from two views of one bundle score."""
    conflicts = []
    left_score = _number(left.get("score"))
    right_score = _number(right.get("score"))
    if left_score is not None and right_score is not None and not math.isclose(
        left_score, right_score, rel_tol=0.0, abs_tol=1e-9
    ):
        conflicts.append("composite_score_mismatch")
    left_group = str(left.get("evidence_group_id") or "") if left.get("evidence_group_verified") is True else ""
    right_group = str(right.get("evidence_group_id") or "") if right.get("evidence_group_verified") is True else ""
    if left_group and right_group and left_group != right_group:
        conflicts.append("evidence_group_mismatch")
    left_components = {
        str(item.get("benchmark_id")): float(item["score"])
        for item in list(left.get("components") or [])
        if item.get("benchmark_id") and _number(item.get("score")) is not None
    }
    right_components = {
        str(item.get("benchmark_id")): float(item["score"])
        for item in list(right.get("components") or [])
        if item.get("benchmark_id") and _number(item.get("score")) is not None
    }
    for component_id in sorted(set(left_components).intersection(right_components)):
        if not math.isclose(
            left_components[component_id], right_components[component_id], rel_tol=0.0, abs_tol=1e-9
        ):
            conflicts.append("component_score_mismatch:%s" % component_id)
    return conflicts


def _surface_observation(surface: Dict[str, Any], document: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
    version = str(surface.get("score_version") or "")
    score = _number(surface.get("score_raw_attainment"))
    if score is None:
        score = _number(surface.get("score_observed"))
    if not version or score is None or surface.get("score_ready") is not True:
        return None
    artifacts = list(surface.get("capability_artifacts") or document.get("capability_artifacts") or [])
    subject_model = ""
    for artifact in artifacts:
        subject_model = str(_nested(artifact, "subject", "model", "model") or "")
        if subject_model:
            break
    return {
        "observation_id": str(document.get("bundle_id") or source),
        "score_version": version,
        "surface_id": surface.get("surface"),
        "score": score,
        "model_family": _family_name(subject_model),
        "parameter_band": _parameter_band(subject_model),
        "model_identities": sorted(_model_identities(subject_model)),
        "quantization_scheme": "",
        **_evidence_group_observation(document),
        "source": source,
    }


def _component_observation(document: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
    protocol = dict(document.get("protocol") or {})
    benchmark_id = str(protocol.get("task_version") or "")
    summary = dict(document.get("summary") or {})
    score = _number(summary.get("score"))
    if not benchmark_id or score is None or summary.get("state") != "scored":
        return None
    subject_model = str(_nested(document, "subject", "model", "model") or "")
    family = (
        _nested(document, "subject", "model", "model_family")
        or document.get("model_family")
        or _family_name(subject_model)
    )
    parameter_scale = (
        _nested(document, "subject", "model", "parameter_scale")
        or document.get("parameter_scale")
        or subject_model
    )
    return {
        "observation_id": str(document.get("capability_run_id") or source),
        "score_version": "benchmark:%s:%s" % (benchmark_id, protocol.get("fixture_revision") or "unknown"),
        "benchmark_id": benchmark_id,
        "surface_id": _nested(document, "evidence", "surface"),
        "score": score,
        "task_count": len(list(document.get("tasks") or [])),
        "model_family": str(family or "unknown"),
        "parameter_band": _parameter_band(parameter_scale),
        "model_identities": sorted(_model_identities(subject_model)),
        "quantization_scheme": str(
            _nested(document, "subject", "model", "quantization_scheme")
            or document.get("quantization_scheme")
            or ""
        ).lower(),
        **_evidence_group_observation(document),
        "source": source,
    }


def audit_capability_observations(
    observations: Iterable[Dict[str, Any]],
    score_version: str,
    policy: Optional[Dict[str, Any]] = None,
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    matching = [item for item in observations if item.get("score_version") == score_version and _number(item.get("score")) is not None]
    integrity_conflicts = [item for item in matching if item.get("integrity_conflicts")]
    eligible = [item for item in matching if not item.get("integrity_conflicts")]
    minimum_task_count = int((policy or {}).get("minimum_task_count") or 0)
    selected = [item for item in eligible if int(item.get("task_count") or 0) >= minimum_task_count]
    current_targets = [
        item
        for item in list((catalog or {}).get("coverage_expansion_priorities") or [])
        if item.get("calibration_campaign_eligible") is True
        and item.get("model_freshness") in {"current_generation", "recent_generation"}
    ]
    headroom_challenge_targets = [
        item for item in current_targets
        if item.get("headroom_challenge_eligible") is True
        and _priority_matches_score_surface(item, selected, score_version, catalog)
    ]
    selected = [dict(item) for item in selected]
    for observation in selected:
        observation["current_generation"] = any(
            _observation_matches_priority_target(observation, priority)
            for priority in current_targets
        )
        observation["headroom_challenge"] = any(
            _observation_matches_priority_target(observation, priority)
            for priority in headroom_challenge_targets
        )
    scores = [float(item["score"]) for item in selected]
    families = Counter(str(item.get("model_family") or "unknown") for item in selected)
    bands = Counter(str(item.get("parameter_band") or "unknown") for item in selected)
    effective_policy = dict(DEFAULT_POLICY)
    effective_policy.update(policy or {})
    count = len(scores)
    ceiling_count = sum(1 for value in scores if math.isclose(value, 1.0, abs_tol=1e-9))
    largest_family_count = max(families.values()) if families else 0
    setup_counts = Counter(_observation_setup_key(item) for item in selected)
    replicated_setup_count = sum(1 for setup_count in setup_counts.values() if setup_count >= 2)
    setup_evidence_groups: Dict[Any, set] = {}
    for item in selected:
        evidence_group_id = (
            str(item.get("evidence_group_id") or "").strip()
            if item.get("evidence_group_verified") is True
            else ""
        )
        if evidence_group_id:
            setup_evidence_groups.setdefault(_observation_setup_key(item), set()).add(evidence_group_id)
    independently_replicated_setup_count = sum(
        1 for groups in setup_evidence_groups.values() if len(groups) >= 2
    )
    evidence_group_count = len({
        group_id
        for groups in setup_evidence_groups.values()
        for group_id in groups
    })
    largest_setup_count = max(setup_counts.values()) if setup_counts else 0
    current_generation_count = sum(1 for item in selected if item.get("current_generation"))
    headroom_challenge_candidates = [
        item for item in selected if item.get("headroom_challenge")
    ]
    required_headline_component_ids = set(
        _headline_component_ids(selected, score_version, catalog)
    )
    headroom_challenge_observations = [
        item for item in headroom_challenge_candidates
        if not required_headline_component_ids
        or required_headline_component_ids.issubset({
            str(component.get("benchmark_id") or "")
            for component in list(item.get("components") or [])
        })
    ]
    headroom_challenge_families = {
        str(item.get("model_family") or "unknown")
        for item in headroom_challenge_observations
    } - {"unknown"}
    headroom_challenge_setup_groups: Dict[Any, set] = {}
    for item in headroom_challenge_observations:
        evidence_group_id = (
            str(item.get("evidence_group_id") or "").strip()
            if item.get("evidence_group_verified") is True
            else ""
        )
        if evidence_group_id:
            headroom_challenge_setup_groups.setdefault(
                _observation_setup_key(item), set()
            ).add(evidence_group_id)
    headroom_challenge_independently_replicated_setup_count = sum(
        1 for groups in headroom_challenge_setup_groups.values() if len(groups) >= 2
    )
    distinct_scores = len(set(round(value, 6) for value in scores))
    metrics = {
        "observation_count": count,
        "integrity_conflict_count": len(integrity_conflicts),
        "excluded_below_minimum_task_count": len(eligible) - len(selected),
        "model_family_count": len([name for name in families if name != "unknown"]),
        "parameter_band_count": len([name for name in bands if name != "unknown"]),
        "distinct_score_count": distinct_scores,
        "unique_setup_count": len(setup_counts),
        "replicated_setup_count": replicated_setup_count,
        "independently_replicated_setup_count": independently_replicated_setup_count,
        "evidence_group_count": evidence_group_count,
        "ungrouped_observation_count": sum(
            1 for item in selected if item.get("evidence_group_verified") is not True
        ),
        "rejected_evidence_group_claim_count": sum(
            1 for item in selected if item.get("evidence_group_claim_rejected") is True
        ),
        "current_generation_count": current_generation_count,
        "current_generation_fraction": round(current_generation_count / float(count), 6) if count else None,
        "headroom_challenge_observation_count": len(headroom_challenge_observations),
        "headroom_challenge_candidate_observation_count": len(headroom_challenge_candidates),
        "headroom_challenge_incomplete_observation_count": (
            len(headroom_challenge_candidates) - len(headroom_challenge_observations)
        ),
        "headroom_challenge_model_family_count": len(headroom_challenge_families),
        "headroom_challenge_independently_replicated_setup_count": (
            headroom_challenge_independently_replicated_setup_count
        ),
        "minimum": min(scores) if scores else None,
        "median": median(scores) if scores else None,
        "mean": mean(scores) if scores else None,
        "p90": _percentile(scores, 0.9),
        "maximum": max(scores) if scores else None,
        "headroom_to_suite_ceiling": round(1.0 - max(scores), 6) if scores else None,
        "suite_ceiling_count": ceiling_count,
        "suite_ceiling_fraction": round(ceiling_count / float(count), 6) if count else None,
        "largest_family_fraction": round(largest_family_count / float(count), 6) if count else None,
        "largest_setup_fraction": round(largest_setup_count / float(count), 6) if count else None,
        "family_counts": dict(sorted(families.items())),
        "parameter_band_counts": dict(sorted(bands.items())),
    }
    component_metrics = _headline_component_metrics(selected, score_version, catalog, effective_policy)
    if component_metrics:
        metrics["headline_components"] = component_metrics
    blockers = []
    if integrity_conflicts:
        blockers.append("duplicate_observation_integrity_conflict")
    _minimum_gate(blockers, metrics, effective_policy, "observation_count", "minimum_observations")
    _minimum_gate(blockers, metrics, effective_policy, "model_family_count", "minimum_model_families")
    _minimum_gate(blockers, metrics, effective_policy, "parameter_band_count", "minimum_parameter_bands")
    _minimum_gate(blockers, metrics, effective_policy, "distinct_score_count", "minimum_distinct_scores")
    if "minimum_unique_setups" in effective_policy:
        _minimum_gate(blockers, metrics, effective_policy, "unique_setup_count", "minimum_unique_setups")
    if "minimum_replicated_setups" in effective_policy:
        _minimum_gate(blockers, metrics, effective_policy, "replicated_setup_count", "minimum_replicated_setups")
    if "minimum_independently_replicated_setups" in effective_policy:
        _minimum_gate(
            blockers,
            metrics,
            effective_policy,
            "independently_replicated_setup_count",
            "minimum_independently_replicated_setups",
        )
    if (
        "minimum_current_generation_fraction" in effective_policy
        and metrics["current_generation_fraction"] is not None
        and metrics["current_generation_fraction"] < float(effective_policy["minimum_current_generation_fraction"])
    ):
        blockers.append("insufficient_current_generation_fraction")
    for metric, threshold in (
        ("headroom_challenge_observation_count", "minimum_headroom_challenge_observations"),
        ("headroom_challenge_model_family_count", "minimum_headroom_challenge_model_families"),
        (
            "headroom_challenge_independently_replicated_setup_count",
            "minimum_headroom_challenge_independently_replicated_setups",
        ),
    ):
        if threshold in effective_policy:
            _minimum_gate(blockers, metrics, effective_policy, metric, threshold)
    suite_ceiling_blocked = (
        metrics["suite_ceiling_fraction"] is not None
        and metrics["suite_ceiling_fraction"] > float(effective_policy["maximum_suite_ceiling_fraction"])
    )
    if suite_ceiling_blocked:
        blockers.append("suite_ceiling_fraction_above_limit")
    elif (
        "minimum_suite_headroom" in effective_policy
        and metrics["headroom_to_suite_ceiling"] is not None
        and metrics["headroom_to_suite_ceiling"] < float(effective_policy["minimum_suite_headroom"])
    ):
        blockers.append("insufficient_suite_headroom")
    if metrics["largest_family_fraction"] is not None and metrics["largest_family_fraction"] > float(effective_policy["maximum_largest_family_fraction"]):
        blockers.append("largest_family_fraction_above_limit")
    if (
        "maximum_single_setup_fraction" in effective_policy
        and metrics["largest_setup_fraction"] is not None
        and metrics["largest_setup_fraction"] > float(effective_policy["maximum_single_setup_fraction"])
    ):
        blockers.append("single_setup_fraction_above_limit")
    minimum_component_observations = effective_policy.get("minimum_headline_component_observations")
    minimum_component_families = effective_policy.get("minimum_headline_component_model_families")
    minimum_component_bands = effective_policy.get("minimum_headline_component_parameter_bands")
    minimum_component_independent_setups = effective_policy.get(
        "minimum_headline_component_independently_replicated_setups"
    )
    maximum_component_ceiling_fraction = effective_policy.get("maximum_headline_component_ceiling_fraction")
    for component_id, component in component_metrics.items():
        component_insufficient = False
        if (
            minimum_component_observations is not None
            and component["observation_count"] < int(minimum_component_observations)
        ):
            blockers.append("insufficient_headline_component_observations:%s" % component_id)
            component_insufficient = True
        if (
            minimum_component_families is not None
            and component["model_family_count"] < int(minimum_component_families)
        ):
            blockers.append("insufficient_headline_component_model_families:%s" % component_id)
            component_insufficient = True
        if (
            minimum_component_bands is not None
            and component["parameter_band_count"] < int(minimum_component_bands)
        ):
            blockers.append("insufficient_headline_component_parameter_bands:%s" % component_id)
            component_insufficient = True
        if (
            minimum_component_independent_setups is not None
            and component["independently_replicated_setup_count"]
            < int(minimum_component_independent_setups)
        ):
            blockers.append(
                "insufficient_headline_component_independently_replicated_setups:%s"
                % component_id
            )
            component_insufficient = True
        if component_insufficient:
            continue
        component_ceiling_blocked = (
            maximum_component_ceiling_fraction is not None
            and component["suite_ceiling_fraction"] is not None
            and component["suite_ceiling_fraction"] > float(maximum_component_ceiling_fraction)
        )
        if component_ceiling_blocked:
            blockers.append("headline_component_ceiling_fraction_above_limit:%s" % component_id)
        elif (
            "minimum_headline_component_headroom" in effective_policy
            and component["headroom_to_suite_ceiling"] is not None
            and component["headroom_to_suite_ceiling"]
            < float(effective_policy["minimum_headline_component_headroom"])
        ):
            blockers.append("insufficient_headline_component_headroom:%s" % component_id)
    insufficient = any(item.startswith("insufficient_") for item in blockers)
    status = (
        "evidence_integrity_risk"
        if integrity_conflicts
        else ("insufficient_calibration" if insufficient else ("saturation_or_concentration_risk" if blockers else "calibrated_headroom"))
    )
    return {
        "artifact_kind": "capability_calibration_audit",
        "artifact_spec_version": "0.1.0",
        "score_version": score_version,
        "status": status,
        "headline_ready": not blockers,
        "policy": effective_policy,
        "metrics": metrics,
        "blockers": blockers,
        "interpretation": (
            "This audit evaluates corpus diversity and headroom. Independent repeats require distinct, "
            "evidence_group_id values bearing trusted_corpus_operator_v1 provenance; missing or untrusted "
            "provenance never counts as independence. Headroom-challenge membership comes only from an "
            "explicit current or recent Runner campaign target; it is a suite stress role, not a general "
            "capability or frontier claim. The audit never rescales, curves, or caps raw benchmark attainment."
        ),
    }


def policy_for_score_version(score_version: str, catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    for policy in surface_score_policy_index(catalog or load_capability_catalog()).values():
        if policy.get("score_version") == score_version:
            return dict(policy.get("calibration_policy") or {})
    return {}


def policy_for_benchmark_id(benchmark_id: str, catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    check = check_index(catalog or load_capability_catalog()).get(benchmark_id) or {}
    return dict(check.get("calibration_policy") or {})


def _component_score_observations(document: Dict[str, Any], capability: Dict[str, Any]) -> List[Dict[str, Any]]:
    reports = document.get("capability_component_reports")
    if not isinstance(reports, list):
        reports = capability.get("capability_component_reports")
    if not isinstance(reports, list):
        return []
    observations = {}
    duplicate_ids = set()
    for report in reports:
        if not isinstance(report, dict):
            continue
        benchmark_id = str(report.get("benchmark_id") or "")
        score = _number(report.get("component_score"))
        if score is None:
            score = _number(report.get("primary_metric_value"))
        if not benchmark_id or score is None or report.get("status") != "completed":
            continue
        if benchmark_id in observations:
            duplicate_ids.add(benchmark_id)
            continue
        observations[benchmark_id] = {"benchmark_id": benchmark_id, "score": score}
    return [
        observations[benchmark_id]
        for benchmark_id in sorted(observations)
        if benchmark_id not in duplicate_ids
    ]


def _headline_component_metrics(
    observations: List[Dict[str, Any]],
    score_version: str,
    catalog: Optional[Dict[str, Any]],
    policy: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    if not catalog or not observations:
        return {}
    headline_ids = _headline_component_ids(observations, score_version, catalog)
    near_ceiling_threshold = float(policy.get("near_ceiling_threshold") or 0.9)
    metrics = {}
    for component_id in headline_ids:
        component_rows = [
            (observation, float(component["score"]))
            for observation in observations
            for component in list(observation.get("components") or [])
            if component.get("benchmark_id") == component_id and _number(component.get("score")) is not None
        ]
        scores = [score for _, score in component_rows]
        families = {
            str(observation.get("model_family") or "unknown")
            for observation, _ in component_rows
        } - {"unknown"}
        bands = {
            str(observation.get("parameter_band") or "unknown")
            for observation, _ in component_rows
        } - {"unknown"}
        setup_evidence_groups: Dict[Any, set] = {}
        for observation, _ in component_rows:
            evidence_group_id = (
                str(observation.get("evidence_group_id") or "").strip()
                if observation.get("evidence_group_verified") is True
                else ""
            )
            if evidence_group_id:
                setup_evidence_groups.setdefault(
                    _observation_setup_key(observation), set()
                ).add(evidence_group_id)
        independently_replicated_setup_count = sum(
            1 for groups in setup_evidence_groups.values() if len(groups) >= 2
        )
        evidence_group_count = len({
            group_id
            for groups in setup_evidence_groups.values()
            for group_id in groups
        })
        ceiling_count = sum(1 for score in scores if math.isclose(score, 1.0, abs_tol=1e-9))
        near_ceiling_count = sum(1 for score in scores if score >= near_ceiling_threshold)
        maximum = max(scores) if scores else None
        metrics[component_id] = {
            "observation_count": len(scores),
            "model_family_count": len(families),
            "parameter_band_count": len(bands),
            "independently_replicated_setup_count": independently_replicated_setup_count,
            "evidence_group_count": evidence_group_count,
            "ungrouped_observation_count": sum(
                1
                for observation, _ in component_rows
                if observation.get("evidence_group_verified") is not True
            ),
            "distinct_score_count": len(set(round(score, 6) for score in scores)),
            "minimum": min(scores) if scores else None,
            "median": median(scores) if scores else None,
            "maximum": maximum,
            "headroom_to_suite_ceiling": round(1.0 - maximum, 6) if maximum is not None else None,
            "suite_ceiling_count": ceiling_count,
            "suite_ceiling_fraction": round(ceiling_count / float(len(scores)), 6) if scores else None,
            "near_ceiling_threshold": near_ceiling_threshold,
            "near_ceiling_count": near_ceiling_count,
            "near_ceiling_fraction": round(near_ceiling_count / float(len(scores)), 6) if scores else None,
        }
    return metrics


def _headline_component_ids(
    observations: List[Dict[str, Any]],
    score_version: str,
    catalog: Optional[Dict[str, Any]],
) -> List[str]:
    if not catalog:
        return []
    surface_ids = {
        str(item.get("surface_id") or "")
        for item in observations
        if item.get("surface_id")
    }
    surface_ids.update(
        str(surface_id)
        for surface_id, surface_policy in surface_score_policy_index(catalog).items()
        if surface_policy.get("score_version") == score_version
    )
    return sorted(
        check_id
        for check_id, check in check_index(catalog).items()
        if check.get("surface_id") in surface_ids
        and float(check.get("primary_score_weight") or 0.0) > 0.0
        and check.get("score_role") != "diagnostic_only"
    )


def _priority_matches_score_surface(
    priority: Dict[str, Any],
    observations: List[Dict[str, Any]],
    score_version: str,
    catalog: Optional[Dict[str, Any]],
) -> bool:
    surface_ids = {
        str(item.get("surface_id") or "")
        for item in observations
        if item.get("surface_id")
    }
    surface_ids.update(
        str(surface_id)
        for surface_id, policy in surface_score_policy_index(catalog).items()
        if policy.get("score_version") == score_version
    )
    if not surface_ids:
        return True
    from infergrade.capability_scoring import primary_surface_for_use_case

    return primary_surface_for_use_case(priority.get("use_case")) in surface_ids


def _minimum_gate(blockers: List[str], metrics: Dict[str, Any], policy: Dict[str, Any], metric: str, threshold: str) -> None:
    if int(metrics.get(metric) or 0) < int(policy[threshold]):
        blockers.append("insufficient_%s" % metric)


def _percentile(values: List[float], quantile: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(math.ceil(quantile * len(ordered))) - 1))
    return ordered[index]


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and 0.0 <= number <= 1.0 else None


def _evidence_group_observation(document: Dict[str, Any]) -> Dict[str, Any]:
    """Accept grouping only when a trusted corpus operator assigned it."""
    claimed = str(document.get("evidence_group_id") or "").strip()
    verified = bool(
        claimed
        and document.get("evidence_group_provenance") == TRUSTED_EVIDENCE_GROUP_PROVENANCE
    )
    return {
        "evidence_group_id": claimed if verified else "",
        "evidence_group_verified": verified,
        "evidence_group_claim_rejected": bool(claimed and not verified),
    }


def _nested(payload: Dict[str, Any], *path: str) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _parameter_band(value: Any) -> str:
    text = str(value or "").lower()
    match = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*b(?:\b|[-_])", text)
    if not match:
        return "unknown"
    billions = float(match.group(1))
    if billions < 3:
        return "under_3b"
    if billions < 8:
        return "3b_to_under_8b"
    if billions < 20:
        return "8b_to_under_20b"
    if billions < 40:
        return "20b_to_under_40b"
    return "40b_plus"


def _observation_scope(source: str) -> str:
    normalized = os.path.abspath(source) if source else ""
    for marker in (os.sep + "artifacts" + os.sep, os.sep + "results" + os.sep, os.sep + "provenance" + os.sep):
        if marker in normalized:
            return normalized.split(marker, 1)[0]
    return ""


def _family_name(value: Any) -> str:
    text = str(value or "").split("/")[-1]
    match = re.match(r"(.+?)-\d+(?:\.\d+)?B(?:-|$)", text, flags=re.IGNORECASE)
    return match.group(1) if match else (text or "unknown")


def _observation_matches_priority_target(observation: Dict[str, Any], priority: Dict[str, Any]) -> bool:
    target_identities = _model_identities(priority.get("model_id"), priority.get("checkpoint_name"))
    observed_identities = set(observation.get("model_identities") or [])
    if target_identities:
        if not target_identities.intersection(observed_identities):
            return False
    elif _normalize_family(priority.get("model_family")) != _normalize_family(observation.get("model_family")):
        return False
    target_band = _parameter_band(priority.get("parameter_scale") or priority.get("checkpoint_name"))
    if target_band != "unknown" and target_band != observation.get("parameter_band"):
        return False
    target_quant = str((priority.get("target_quants") or [""])[0]).lower()
    return not target_quant or target_quant == str(observation.get("quantization_scheme") or "").lower()


def _observation_setup_key(observation: Dict[str, Any]) -> tuple:
    identities = tuple(sorted(set(observation.get("model_identities") or [])))
    if not identities:
        identities = (_normalize_family(observation.get("model_family")) or "unknown",)
    return identities + (str(observation.get("quantization_scheme") or "unknown"),)


def _model_identities(*values: Any) -> set:
    return {
        normalized
        for value in values
        for normalized in (_normalize_model_identity(value),)
        if normalized
    }


def _normalize_model_identity(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").split("/")[-1].lower())


def _normalize_family(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
