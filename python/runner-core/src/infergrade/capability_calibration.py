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
    seen = set()
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
        version = str(details.get("score_version") or "")
        score = _number(details.get("raw_attainment"))
        if score is None:
            score = _number(details.get("observed_weighted_score"))
        if score is None:
            score = _number(details.get("score"))
        if score is None:
            score = _number(capability.get("capability_score"))
        if not version or score is None or details.get("score_ready") is not True:
            continue
        observation_id = str(document.get("result_id") or document.get("bundle_id") or source)
        key = (observation_id, version)
        if key in seen:
            continue
        seen.add(key)
        family = _nested(document, "ontology", "model_family", "family_name") or document.get("model_family")
        scale = _nested(document, "ontology", "model_family", "parameter_scale") or document.get("parameter_scale")
        observations.append(
            {
                "observation_id": observation_id,
                "score_version": version,
                "surface_id": details.get("surface_id"),
                "score": score,
                "model_family": str(family or "unknown"),
                "parameter_band": _parameter_band(scale or document.get("checkpoint_name")),
                "source": source,
            }
        )
    deduplicated: List[Dict[str, Any]] = []
    seen_observations = set()
    for item in observations:
        key = (item.get("score_version"), _observation_scope(str(item.get("source") or "")) or item.get("observation_id"))
        if key in seen_observations:
            continue
        seen_observations.add(key)
        deduplicated.append(item)
    if score_version:
        return [item for item in deduplicated if item.get("score_version") == score_version]
    if benchmark_id:
        return [item for item in deduplicated if item.get("benchmark_id") == benchmark_id]
    return deduplicated


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
    return {
        "observation_id": str(document.get("capability_run_id") or source),
        "score_version": "benchmark:%s:%s" % (benchmark_id, protocol.get("fixture_revision") or "unknown"),
        "benchmark_id": benchmark_id,
        "surface_id": _nested(document, "evidence", "surface"),
        "score": score,
        "task_count": len(list(document.get("tasks") or [])),
        "model_family": _family_name(subject_model),
        "parameter_band": _parameter_band(subject_model),
        "source": source,
    }


def audit_capability_observations(
    observations: Iterable[Dict[str, Any]],
    score_version: str,
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    matching = [item for item in observations if item.get("score_version") == score_version and _number(item.get("score")) is not None]
    minimum_task_count = int((policy or {}).get("minimum_task_count") or 0)
    selected = [item for item in matching if int(item.get("task_count") or 0) >= minimum_task_count]
    scores = [float(item["score"]) for item in selected]
    families = Counter(str(item.get("model_family") or "unknown") for item in selected)
    bands = Counter(str(item.get("parameter_band") or "unknown") for item in selected)
    effective_policy = dict(DEFAULT_POLICY)
    effective_policy.update(policy or {})
    count = len(scores)
    ceiling_count = sum(1 for value in scores if math.isclose(value, 1.0, abs_tol=1e-9))
    largest_family_count = max(families.values()) if families else 0
    distinct_scores = len(set(round(value, 6) for value in scores))
    metrics = {
        "observation_count": count,
        "excluded_below_minimum_task_count": len(matching) - len(selected),
        "model_family_count": len([name for name in families if name != "unknown"]),
        "parameter_band_count": len([name for name in bands if name != "unknown"]),
        "distinct_score_count": distinct_scores,
        "minimum": min(scores) if scores else None,
        "median": median(scores) if scores else None,
        "mean": mean(scores) if scores else None,
        "p90": _percentile(scores, 0.9),
        "maximum": max(scores) if scores else None,
        "suite_ceiling_count": ceiling_count,
        "suite_ceiling_fraction": round(ceiling_count / float(count), 6) if count else None,
        "largest_family_fraction": round(largest_family_count / float(count), 6) if count else None,
        "family_counts": dict(sorted(families.items())),
        "parameter_band_counts": dict(sorted(bands.items())),
    }
    blockers = []
    _minimum_gate(blockers, metrics, effective_policy, "observation_count", "minimum_observations")
    _minimum_gate(blockers, metrics, effective_policy, "model_family_count", "minimum_model_families")
    _minimum_gate(blockers, metrics, effective_policy, "parameter_band_count", "minimum_parameter_bands")
    _minimum_gate(blockers, metrics, effective_policy, "distinct_score_count", "minimum_distinct_scores")
    if metrics["suite_ceiling_fraction"] is not None and metrics["suite_ceiling_fraction"] > float(effective_policy["maximum_suite_ceiling_fraction"]):
        blockers.append("suite_ceiling_fraction_above_limit")
    if metrics["largest_family_fraction"] is not None and metrics["largest_family_fraction"] > float(effective_policy["maximum_largest_family_fraction"]):
        blockers.append("largest_family_fraction_above_limit")
    insufficient = any(item.startswith("insufficient_") for item in blockers)
    status = "insufficient_calibration" if insufficient else ("saturation_or_concentration_risk" if blockers else "calibrated_headroom")
    return {
        "artifact_kind": "capability_calibration_audit",
        "artifact_spec_version": "0.1.0",
        "score_version": score_version,
        "status": status,
        "headline_ready": not blockers,
        "policy": effective_policy,
        "metrics": metrics,
        "blockers": blockers,
        "interpretation": "This audit evaluates corpus diversity and headroom. It never rescales, curves, or caps raw benchmark attainment.",
    }


def policy_for_score_version(score_version: str, catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    for policy in surface_score_policy_index(catalog or load_capability_catalog()).values():
        if policy.get("score_version") == score_version:
            return dict(policy.get("calibration_policy") or {})
    return {}


def policy_for_benchmark_id(benchmark_id: str, catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    check = check_index(catalog or load_capability_catalog()).get(benchmark_id) or {}
    return dict(check.get("calibration_policy") or {})


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
