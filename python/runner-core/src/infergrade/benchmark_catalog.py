"""Runner-owned capability suite and benchmark selection helpers."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from infergrade.models import RunRequest

FALLBACK_METADATA_ORDERING = {
    "effort_level": ["short", "low", "balanced", "medium", "deep", "high"],
    "expected_duration_band": ["1-5 min", "5-15 min", "10-25 min", "10-30 min", "15-45 min", "25-60 min"],
    "token_volume_band": ["tiny", "small", "medium", "large"],
}


def repo_root() -> Path:
    """Return the repository root for the Runner workspace."""
    return Path(__file__).resolve().parents[4]


def capability_catalog_path(root: Optional[Path] = None) -> Path:
    """Return the path to the Runner capability catalog."""
    base = Path(root) if root is not None else repo_root()
    return base / "schemas" / "capability_catalog.json"


def load_capability_catalog(root: Optional[Path] = None) -> Dict[str, Any]:
    """Load the machine-readable capability catalog."""
    path = capability_catalog_path(root)
    return json.loads(path.read_text(encoding="utf-8"))


def suite_index(catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Return suites keyed by suite id."""
    payload = catalog or load_capability_catalog()
    return {str(item["suite_id"]): dict(item) for item in list(payload.get("suites") or [])}


def group_index(catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Return benchmark groups keyed by group id."""
    payload = catalog or load_capability_catalog()
    return {str(item["group_id"]): dict(item) for item in list(payload.get("benchmark_groups") or [])}


def check_index(catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Return checks keyed by check id."""
    payload = catalog or load_capability_catalog()
    return {str(item["check_id"]): dict(item) for item in list(payload.get("checks") or [])}


def shortcut_index(catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Return benchmark shortcuts keyed by shortcut id."""
    payload = catalog or load_capability_catalog()
    return {str(item["shortcut_id"]): dict(item) for item in list(payload.get("shortcuts") or [])}


def evidence_lane_index(catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Return evidence lanes keyed by lane id."""
    payload = catalog or load_capability_catalog()
    return {str(item["lane_id"]): dict(item) for item in list(payload.get("evidence_lanes") or [])}


def benchmark_maturity_index(catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Return benchmark maturity levels keyed by maturity id."""
    payload = catalog or load_capability_catalog()
    return {str(item["maturity"]): dict(item) for item in list(payload.get("benchmark_maturity_levels") or [])}


def benchmark_status_index(catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Return benchmark legitimacy status metadata keyed by check id."""
    payload = catalog or load_capability_catalog()
    return {str(item["check_id"]): dict(item) for item in list(payload.get("benchmark_status_matrix") or [])}


def capability_surface_index(catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Return capability surfaces keyed by surface id."""
    payload = catalog or load_capability_catalog()
    return {str(item["surface_id"]): dict(item) for item in list(payload.get("capability_surfaces") or [])}


def validate_benchmark_legitimacy_metadata(catalog: Optional[Dict[str, Any]] = None) -> List[str]:
    """Return catalog legitimacy metadata validation failures.

    This intentionally validates catalog shape without making planned checks runnable.
    """
    payload = catalog or load_capability_catalog()
    failures: List[str] = []
    lanes = evidence_lane_index(payload)
    surfaces = capability_surface_index(payload)
    maturity_levels = benchmark_maturity_index(payload)
    score_policy_ids = {
        str(item.get("score_policy_id"))
        for item in list(payload.get("score_policies") or [])
        if item.get("score_policy_id")
    }
    status_by_check = benchmark_status_index(payload)
    required_status_fields = {
        "check_id",
        "surface_id",
        "evidence_lane_id",
        "maturity",
        "runnable_status",
        "default_inclusion_status",
        "fixture_or_dataset_revision_status",
        "harness_status",
        "scoring_policy_id",
        "sample_policy",
        "expected_duration_token_volume_status",
        "sandbox_requirement",
        "claim_boundary",
        "promotion_blockers",
    }
    required_non_empty_fields = required_status_fields - {"promotion_blockers"}
    declared_check_ids = {str(item.get("check_id")) for item in list(payload.get("checks") or []) if item.get("check_id")}
    planned_check_ids = {
        str(item.get("check_id"))
        for item in list(payload.get("planned_benchmark_candidates") or [])
        if item.get("check_id")
    }
    for check_id in sorted(declared_check_ids | planned_check_ids):
        status = status_by_check.get(check_id)
        if not status:
            failures.append(f"{check_id}: missing benchmark_status_matrix entry")
            continue
        missing = sorted(field for field in required_status_fields if field not in status)
        if missing:
            failures.append(f"{check_id}: missing status field(s): {', '.join(missing)}")
        for field in sorted(required_non_empty_fields):
            if field in status and not str(status.get(field) or "").strip():
                failures.append(f"{check_id}: status field {field} must be non-empty")
        if str(status.get("evidence_lane_id") or "") not in lanes:
            failures.append(f"{check_id}: unknown evidence_lane_id {status.get('evidence_lane_id')!r}")
        if str(status.get("surface_id") or "") not in surfaces:
            failures.append(f"{check_id}: unknown surface_id {status.get('surface_id')!r}")
        if str(status.get("maturity") or "") not in maturity_levels:
            failures.append(f"{check_id}: unknown maturity {status.get('maturity')!r}")
        status_policy = str(status.get("scoring_policy_id") or "").strip()
        declared_check = next((item for item in list(payload.get("checks") or []) if item.get("check_id") == check_id), None)
        planned_candidate = next(
            (item for item in list(payload.get("planned_benchmark_candidates") or []) if item.get("check_id") == check_id),
            None,
        )
        if declared_check and status_policy != str(declared_check.get("score_policy_id") or "").strip():
            failures.append(f"{check_id}: status scoring_policy_id does not match check score_policy_id")
        if planned_candidate and status_policy != str(planned_candidate.get("planned_score_policy_id") or "").strip():
            failures.append(f"{check_id}: status scoring_policy_id does not match planned_score_policy_id")
        if not declared_check and not planned_candidate and status_policy not in score_policy_ids:
            failures.append(f"{check_id}: scoring_policy_id is not declared")
        if not isinstance(status.get("promotion_blockers"), list) or not status.get("promotion_blockers"):
            failures.append(f"{check_id}: promotion_blockers must be a non-empty list")
    extra_status_ids = sorted(set(status_by_check) - (declared_check_ids | planned_check_ids))
    for check_id in extra_status_ids:
        failures.append(f"{check_id}: status matrix entry has no matching check or planned candidate")
    for check in list(payload.get("checks") or []):
        check_id = str(check.get("check_id") or "")
        status = status_by_check.get(check_id, {})
        if status and check.get("evidence_lane_id") != status.get("evidence_lane_id"):
            failures.append(f"{check_id}: check lane and status matrix lane disagree")
        if status and check.get("surface_id") != status.get("surface_id"):
            failures.append(f"{check_id}: check surface and status matrix surface disagree")
    return failures


def shortcut_selection(shortcut_id: Optional[str], catalog: Optional[Dict[str, Any]] = None) -> Dict[str, List[str]]:
    """Return the suite/group/check selection declared by a benchmark shortcut."""
    payload = catalog or load_capability_catalog()
    shortcut_id = str(shortcut_id or "").strip()
    shortcut = shortcut_index(payload).get(shortcut_id) if shortcut_id else None
    if not shortcut:
        return {"suite_ids": [], "group_ids": [], "check_ids": []}
    return {
        "suite_ids": _dedupe_strings(shortcut.get("suite_ids")),
        "group_ids": _dedupe_strings(shortcut.get("group_ids")),
        "check_ids": _dedupe_strings(shortcut.get("check_ids")),
    }


def legacy_selection(use_case: Optional[str], tier: str, catalog: Optional[Dict[str, Any]] = None) -> Dict[str, List[str]]:
    """Return the legacy tier-based selection for backward compatibility."""
    payload = catalog or load_capability_catalog()
    defaults = dict(payload.get("legacy_tier_defaults") or {})
    use_case_key = use_case if use_case in defaults else "default"
    lane = dict((defaults.get(use_case_key) or {}).get(tier) or {})
    return {
        "suite_ids": _dedupe_strings(lane.get("suite_ids")),
        "group_ids": _dedupe_strings(lane.get("group_ids")),
        "check_ids": _dedupe_strings(lane.get("check_ids")),
    }


def derive_tier_from_selection(
    check_ids: List[str],
    group_ids: Optional[List[str]] = None,
    suite_ids: Optional[List[str]] = None,
    catalog: Optional[Dict[str, Any]] = None,
) -> str:
    """Infer a legacy benchmark tier from explicit evidence breadth."""
    payload = catalog or load_capability_catalog()
    checks = check_index(payload)
    normalized_checks = [item for item in _dedupe_strings(check_ids) if item in checks]
    if not normalized_checks:
        return "canary"

    deployment_count = len([item for item in normalized_checks if checks[item].get("evidence_kind") == "deployment"])
    capability_count = len([item for item in normalized_checks if checks[item].get("evidence_kind") == "capability"])
    fidelity_count = len([item for item in normalized_checks if checks[item].get("evidence_kind") == "fidelity"])
    breadth_score = len(normalized_checks) + max(0, capability_count - 1) + fidelity_count

    if capability_count <= 1 and deployment_count <= 1 and fidelity_count == 0 and breadth_score <= 2:
        return "canary"
    if breadth_score >= 5 or capability_count >= 2 or (deployment_count >= 2 and fidelity_count >= 1):
        return "gold"
    return "standard"


def resolve_request_selection(request: RunRequest, catalog: Optional[Dict[str, Any]] = None) -> Dict[str, List[str]]:
    """Resolve explicit suite/group/check selections for a request."""
    payload = catalog or load_capability_catalog()
    suites = suite_index(payload)
    groups = group_index(payload)
    checks = check_index(payload)

    suite_ids = [item for item in _dedupe_strings(request.capability_suite_ids) if item in suites]
    group_ids = [item for item in _dedupe_strings(request.benchmark_group_ids) if item in groups]
    check_ids = [item for item in _dedupe_strings(request.benchmark_check_ids) if item in checks]

    if not suite_ids and not group_ids and not check_ids:
        shortcut = shortcut_selection(request.benchmark_shortcut_id, payload)
        if shortcut["suite_ids"] or shortcut["group_ids"] or shortcut["check_ids"]:
            suite_ids = [item for item in shortcut["suite_ids"] if item in suites]
            group_ids = [item for item in shortcut["group_ids"] if item in groups]
            check_ids = [item for item in shortcut["check_ids"] if item in checks]
        else:
            legacy = legacy_selection(request.use_case, request.tier, payload)
            suite_ids = list(legacy["suite_ids"])
            group_ids = list(legacy["group_ids"])
            check_ids = list(legacy["check_ids"])

    if request.deployment_profiles and not request.benchmark_check_ids:
        selected_deployment_checks = [
            check_id
            for check_id, check_payload in checks.items()
            if check_payload.get("evidence_kind") == "deployment"
            and check_payload.get("runner_target") in list(request.deployment_profiles or [])
        ]
        if selected_deployment_checks:
            check_ids = [
                item for item in check_ids if checks.get(item, {}).get("evidence_kind") != "deployment"
            ] + selected_deployment_checks
            check_ids = _dedupe_strings(check_ids)

    if suite_ids and not group_ids:
        for suite_id in suite_ids:
            group_ids.extend(list((suites[suite_id].get("default_group_ids") or [])))
        group_ids = [item for item in _dedupe_strings(group_ids) if item in groups]

    if group_ids and not check_ids:
        for group_id in group_ids:
            check_ids.extend(list((groups[group_id].get("default_check_ids") or [])))
        check_ids = [item for item in _dedupe_strings(check_ids) if item in checks]

    if check_ids and not group_ids:
        derived_groups: List[str] = []
        for check_id in check_ids:
            group_id = checks[check_id].get("group_id")
            if group_id:
                derived_groups.append(str(group_id))
        group_ids = [item for item in _dedupe_strings(derived_groups) if item in groups]

    return {
        "suite_ids": suite_ids,
        "group_ids": group_ids,
        "check_ids": check_ids,
    }


def normalize_request_selection(request: RunRequest, catalog: Optional[Dict[str, Any]] = None) -> RunRequest:
    """Apply selection defaults and compatibility-derived fields directly onto a request."""
    payload = catalog or load_capability_catalog()
    suites = suite_index(payload)
    checks = check_index(payload)
    selection = resolve_request_selection(request, payload)

    suite_ids = list(selection["suite_ids"])
    group_ids = list(selection["group_ids"])
    check_ids = list(selection["check_ids"])

    request.capability_suite_ids = suite_ids
    request.benchmark_group_ids = group_ids
    request.benchmark_check_ids = check_ids

    if check_ids:
        request.tier = derive_tier_from_selection(check_ids, group_ids=group_ids, suite_ids=suite_ids, catalog=payload)

    if not request.use_case:
        for suite_id in suite_ids:
            primary_use_case = suites.get(suite_id, {}).get("primary_use_case")
            if primary_use_case:
                request.use_case = str(primary_use_case)
                break
    if not request.use_case:
        inferred_use_case = _infer_use_case_from_groups(group_ids, suites)
        if inferred_use_case:
            request.use_case = inferred_use_case

    selected_profiles = deployment_profile_ids_for_request(request, payload)
    if selected_profiles:
        request.deployment_profiles = list(selected_profiles)

    if request.capability != "none":
        request.capability = "auto" if capability_benchmark_ids_for_request(request, payload) else "none"

    if not request.benchmark_shortcut_id and request.capability_suite_ids:
        request.benchmark_shortcut_id = None

    return request


def capability_benchmark_ids_for_request(
    request: RunRequest,
    catalog: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Return selected capability benchmark ids."""
    payload = catalog or load_capability_catalog()
    checks = check_index(payload)
    selection = resolve_request_selection(request, payload)
    return [
        item
        for item in _dedupe_strings(selection.get("check_ids"))
        if checks.get(item, {}).get("evidence_kind") == "capability"
    ]


def deployment_profile_ids_for_request(
    request: RunRequest,
    catalog: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Return selected deployment profile ids."""
    payload = catalog or load_capability_catalog()
    checks = check_index(payload)
    selection = resolve_request_selection(request, payload)
    return [
        str(checks[item]["runner_target"])
        for item in _dedupe_strings(selection.get("check_ids"))
        if checks.get(item, {}).get("evidence_kind") == "deployment"
    ]


def fidelity_enabled_for_request(
    request: RunRequest,
    catalog: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return whether the request explicitly includes fidelity evidence."""
    payload = catalog or load_capability_catalog()
    checks = check_index(payload)
    selection = resolve_request_selection(request, payload)
    return any(checks.get(item, {}).get("evidence_kind") == "fidelity" for item in _dedupe_strings(selection.get("check_ids")))


def benchmark_scope_summary_for_selection(
    check_ids: List[str],
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Summarize whether a selected benchmark set is decision-sized or reference-sized."""
    payload = catalog or load_capability_catalog()
    checks = check_index(payload)
    selected = [checks[item] for item in _dedupe_strings(check_ids) if item in checks]
    if not selected:
        decision_lane = _evidence_lane_payload(payload, "decision")
        return {
            "scope": "decision",
            "scope_label": "Decision suite",
            "evidence_lane_id": "decision",
            "evidence_lane": decision_lane,
            "claim_strength": decision_lane.get("claim_strength"),
            "claim_boundary": decision_lane.get("claim_boundary"),
            "selection_guidance": "Decision checks are selected. This is the recommended short local path for choosing a quantized setup.",
            "effort_level": "short",
            "expected_duration_band": "1-5 min",
            "token_volume_band": "tiny",
            "metadata_sources": _metadata_sources(payload, []),
            "metadata_confidence": _metadata_confidence(_metadata_sources(payload, [])),
            "execution_patterns": [],
            "resumability_boundaries": [],
            "reference_checks_included": False,
        }

    scopes = _dedupe_strings([item.get("suite_scope") for item in selected])
    scope = "reference" if "reference" in scopes else "decision"
    evidence_lane_id = _strongest_evidence_lane_id(payload, selected)
    evidence_lane = _evidence_lane_payload(payload, evidence_lane_id)
    ordering = _metadata_ordering(payload)
    return {
        "scope": scope,
        "scope_label": "Reference suite" if scope == "reference" else "Decision suite",
        "evidence_lane_id": evidence_lane_id,
        "evidence_lane": evidence_lane,
        "claim_strength": evidence_lane.get("claim_strength"),
        "claim_boundary": evidence_lane.get("claim_boundary"),
        "selection_guidance": (
            "Reference checks are included. Expect deeper evidence, longer runs, and stronger quant-ladder confidence."
            if scope == "reference"
            else "Decision checks are selected. This is the recommended short local path for choosing a quantized setup."
        ),
        "effort_level": _max_by_order([item.get("effort_level") or item.get("effort_hint") for item in selected], ordering["effort_level"], "short"),
        "expected_duration_band": _max_by_order([item.get("expected_duration_band") for item in selected], ordering["expected_duration_band"], "1-5 min"),
        "token_volume_band": _max_by_order([item.get("token_volume_band") for item in selected], ordering["token_volume_band"], "tiny"),
        "metadata_sources": _metadata_sources(payload, selected),
        "metadata_confidence": _metadata_confidence(_metadata_sources(payload, selected)),
        "execution_patterns": _dedupe_strings([item.get("execution_pattern") for item in selected]),
        "resumability_boundaries": _dedupe_strings([item.get("resumability_boundary") for item in selected]),
        "reference_checks_included": scope == "reference",
    }


def capability_coverage_guidance_for_selection(
    check_ids: List[str],
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return user-facing coverage guidance without treating unknown as failure."""
    payload = catalog or load_capability_catalog()
    checks = check_index(payload)
    selected_ids = [item for item in _dedupe_strings(check_ids) if item in checks]
    selected_checks = [checks[item] for item in selected_ids]
    selected_kinds = set(_dedupe_strings([item.get("evidence_kind") for item in selected_checks]))
    selected_decision = [item["check_id"] for item in selected_checks if item.get("suite_scope") == "decision"]
    selected_reference = [item["check_id"] for item in selected_checks if item.get("suite_scope") == "reference"]
    selected_lane_ids = _dedupe_strings([_evidence_lane_id_for_item(payload, item) for item in selected_checks])
    available_reference = [
        check_id
        for check_id, check in checks.items()
        if check.get("suite_scope") == "reference" and check_id not in selected_ids and check.get("status", "available") != "planned"
    ]
    planned = [
        _planned_benchmark_candidate_payload(payload, item)
        for item in list(payload.get("planned_benchmark_candidates") or [])
    ] + [
        _planned_benchmark_candidate_payload(
            payload,
            {
                "check_id": check_id,
                "display_name": check.get("display_name"),
                "value": check.get("planned_value"),
                "implementation_risk": check.get("implementation_risk"),
                "suite_placement": check.get("suite_placement") or check.get("group_id"),
                "evidence_lane_id": _evidence_lane_id_for_item(payload, check),
            },
        )
        for check_id, check in checks.items()
        if check.get("status") == "planned"
    ]
    missing_core = []
    for kind, label in (
        ("deployment", "deployment telemetry"),
        ("capability", "task capability"),
        ("fidelity", "quant fidelity"),
    ):
        if kind not in selected_kinds:
            missing_core.append(
                {
                    "evidence_kind": kind,
                    "label": label,
                    "state": "not_selected",
                    "message": "%s is not selected for this run. That is a coverage gap, not a failed benchmark." % label.capitalize(),
                }
            )
    return {
        "evidence_lanes": _sorted_evidence_lanes(payload),
        "selected_evidence_lane_ids": selected_lane_ids,
        "selected_decision_check_ids": selected_decision,
        "selected_reference_check_ids": selected_reference,
        "available_reference_check_ids": available_reference,
        "missing_core_evidence": missing_core,
        "planned_benchmark_candidates": planned,
        "next_actions": _coverage_next_actions(missing_core, available_reference),
    }


def selection_metadata_for_request(
    request: RunRequest,
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return normalized selection metadata for result records and summaries."""
    payload = catalog or load_capability_catalog()
    suites = suite_index(payload)
    groups = group_index(payload)
    checks = check_index(payload)
    normalized = resolve_request_selection(request, payload)
    benchmark_scope = benchmark_scope_summary_for_selection(normalized["check_ids"], payload)
    coverage_guidance = capability_coverage_guidance_for_selection(normalized["check_ids"], payload)
    return {
        "catalog_version": payload.get("catalog_version"),
        "shortcut_id": request.benchmark_shortcut_id,
        "benchmark_scope": benchmark_scope,
        "capability_coverage_guidance": coverage_guidance,
        "capability_suite_ids": list(normalized["suite_ids"]),
        "benchmark_group_ids": list(normalized["group_ids"]),
        "benchmark_check_ids": list(normalized["check_ids"]),
        "capability_suites": [
            {
                "suite_id": suite_id,
                "display_name": suites[suite_id].get("display_name"),
                "description": suites[suite_id].get("description"),
                "surface_id": suites[suite_id].get("surface_id"),
                "default_scope": suites[suite_id].get("default_scope"),
                "effort_level": suites[suite_id].get("effort_level"),
            }
            for suite_id in normalized["suite_ids"]
            if suite_id in suites
        ],
        "benchmark_groups": [
            {
                "group_id": group_id,
                "display_name": groups[group_id].get("display_name"),
                "description": groups[group_id].get("description"),
                "evidence_kind": groups[group_id].get("evidence_kind"),
                "surface_id": groups[group_id].get("surface_id"),
                "suite_scope": groups[group_id].get("suite_scope"),
                "effort_hint": groups[group_id].get("effort_hint"),
                "expected_duration_band": groups[group_id].get("expected_duration_band"),
                "token_volume_band": groups[group_id].get("token_volume_band"),
                "resumability_boundary": groups[group_id].get("resumability_boundary"),
                "execution_pattern": groups[group_id].get("execution_pattern"),
            }
            for group_id in normalized["group_ids"]
            if group_id in groups
        ],
        "benchmark_checks": [
            _benchmark_check_metadata(payload, check_id, checks[check_id])
            for check_id in normalized["check_ids"]
            if check_id in checks
        ],
        "score_policies": _selected_score_policies(normalized["check_ids"], payload),
    }


def _selected_score_policies(check_ids: List[str], catalog: Dict[str, Any]) -> List[Dict[str, Any]]:
    checks = check_index(catalog)
    policies = {
        str(item.get("score_policy_id")): dict(item)
        for item in list(catalog.get("score_policies") or [])
        if item.get("score_policy_id")
    }
    selected_policy_ids = _dedupe_strings(
        [checks[item].get("score_policy_id") for item in _dedupe_strings(check_ids) if item in checks]
    )
    return [policies[policy_id] for policy_id in selected_policy_ids if policy_id in policies]


def _benchmark_check_metadata(catalog: Dict[str, Any], check_id: str, check: Dict[str, Any]) -> Dict[str, Any]:
    lane_id = _evidence_lane_id_for_item(catalog, check)
    lane = _evidence_lane_payload(catalog, lane_id)
    legitimacy_status = benchmark_status_index(catalog).get(check_id, {})
    return {
        "check_id": check_id,
        "display_name": check.get("display_name"),
        "description": check.get("description"),
        "evidence_kind": check.get("evidence_kind"),
        "surface_id": check.get("surface_id"),
        "evidence_lane_id": lane_id,
        "evidence_lane_label": lane.get("display_name"),
        "claim_strength": lane.get("claim_strength"),
        "claim_boundary": lane.get("claim_boundary"),
        "group_id": check.get("group_id"),
        "suite_scope": check.get("suite_scope"),
        "effort_level": check.get("effort_level"),
        "expected_duration_band": check.get("expected_duration_band"),
        "token_volume_band": check.get("token_volume_band"),
        "resumability_boundary": check.get("resumability_boundary"),
        "execution_pattern": check.get("execution_pattern"),
        "selection_guidance": check.get("selection_guidance"),
        "status": check.get("status", "available"),
        "score_dimension": check.get("score_dimension"),
        "primary_score_metric": check.get("primary_score_metric"),
        "score_floor": check.get("score_floor"),
        "primary_score_weight": check.get("primary_score_weight"),
        "higher_is_better": check.get("higher_is_better"),
        "score_policy_id": check.get("score_policy_id"),
        "score_breakdown_fields": list(check.get("score_breakdown_fields") or []),
        "benchmark_maturity": legitimacy_status.get("maturity"),
        "runnable_status": legitimacy_status.get("runnable_status"),
        "default_inclusion_status": legitimacy_status.get("default_inclusion_status"),
        "fixture_or_dataset_revision_status": legitimacy_status.get("fixture_or_dataset_revision_status"),
        "harness_status": legitimacy_status.get("harness_status"),
        "sample_policy": legitimacy_status.get("sample_policy"),
        "benchmark_claim_boundary": legitimacy_status.get("claim_boundary"),
        "expected_duration_token_volume_status": legitimacy_status.get("expected_duration_token_volume_status"),
        "sandbox_requirement": legitimacy_status.get("sandbox_requirement"),
        "promotion_blockers": list(legitimacy_status.get("promotion_blockers") or []),
    }


def _coverage_next_actions(missing_core: List[Dict[str, Any]], available_reference: List[str]) -> List[Dict[str, str]]:
    actions: List[Dict[str, str]] = []
    missing_kinds = {item.get("evidence_kind") for item in missing_core}
    if "deployment" in missing_kinds:
        actions.append({"action": "add_deployment_check", "label": "Add deployment telemetry", "detail": "Include interactive_chat_v1 before comparing speed or TTFT."})
    if "capability" in missing_kinds:
        actions.append({"action": "add_capability_check", "label": "Add task capability", "detail": "Include a use-case capability check before trusting quality claims."})
    if "fidelity" in missing_kinds and available_reference:
        actions.append({"action": "add_reference_fidelity", "label": "Add quant fidelity", "detail": "Use reference checks when nearby quant variants need a tie-breaker."})
    return actions


def _sorted_evidence_lanes(catalog: Dict[str, Any]) -> List[Dict[str, Any]]:
    lanes = [dict(item) for item in list((catalog or {}).get("evidence_lanes") or []) if item.get("lane_id")]
    return sorted(lanes, key=lambda item: int(item.get("sort_order") or 0))


def _evidence_lane_payload(catalog: Dict[str, Any], lane_id: str) -> Dict[str, Any]:
    lanes = evidence_lane_index(catalog)
    if lane_id in lanes:
        return dict(lanes[lane_id])
    if "decision" in lanes:
        return dict(lanes["decision"])
    return {
        "lane_id": "decision",
        "display_name": "Decision evidence",
        "short_label": "Decision",
        "claim_strength": "first_pass_local_decision",
        "claim_boundary": "Good for choosing a practical next setup. Not enough by itself for leaderboard-style model quality claims.",
        "sort_order": 10,
    }


def _evidence_lane_id_for_item(catalog: Dict[str, Any], item: Dict[str, Any]) -> str:
    lanes = evidence_lane_index(catalog)
    for key in ("evidence_lane_id", "benchmark_tier", "suite_scope"):
        candidate = str((item or {}).get(key) or "").strip()
        if candidate in lanes:
            return candidate
    return "decision"


def _strongest_evidence_lane_id(catalog: Dict[str, Any], selected: List[Dict[str, Any]]) -> str:
    if not selected:
        return "decision"
    lanes = evidence_lane_index(catalog)
    lane_ids = _dedupe_strings([_evidence_lane_id_for_item(catalog, item) for item in selected])
    if not lane_ids:
        return "decision"
    return max(lane_ids, key=lambda lane_id: int(lanes.get(lane_id, {}).get("sort_order") or 0))


def _planned_benchmark_candidate_payload(catalog: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
    candidate = dict(item)
    lane_id = _evidence_lane_id_for_item(catalog, candidate)
    lane = _evidence_lane_payload(catalog, lane_id)
    legitimacy_status = benchmark_status_index(catalog).get(str(candidate.get("check_id") or ""), {})
    candidate["evidence_lane_id"] = lane_id
    candidate["evidence_lane_label"] = lane.get("display_name")
    candidate["claim_strength"] = lane.get("claim_strength")
    candidate["claim_boundary"] = lane.get("claim_boundary")
    candidate["benchmark_maturity"] = legitimacy_status.get("maturity")
    candidate["runnable_status"] = legitimacy_status.get("runnable_status")
    candidate["default_inclusion_status"] = legitimacy_status.get("default_inclusion_status")
    candidate["fixture_or_dataset_revision_status"] = legitimacy_status.get("fixture_or_dataset_revision_status")
    candidate["harness_status"] = legitimacy_status.get("harness_status")
    candidate["sample_policy"] = legitimacy_status.get("sample_policy")
    candidate["benchmark_claim_boundary"] = legitimacy_status.get("claim_boundary")
    candidate["expected_duration_token_volume_status"] = legitimacy_status.get("expected_duration_token_volume_status")
    candidate["sandbox_requirement"] = legitimacy_status.get("sandbox_requirement")
    candidate["promotion_blockers"] = list(legitimacy_status.get("promotion_blockers") or [])
    return candidate


def _max_by_order(values: List[Any], order: Dict[str, int], fallback: str) -> str:
    cleaned = _dedupe_strings(values)
    if not cleaned:
        return fallback
    return max(cleaned, key=lambda item: order.get(item, -1))


def _metadata_ordering(catalog: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """Return ordering maps declared by the Runner-owned capability catalog."""
    declared = catalog.get("metadata_ordering") if isinstance(catalog, dict) else {}
    return {
        key: {str(value): index for index, value in enumerate(list((declared or {}).get(key) or fallback))}
        for key, fallback in FALLBACK_METADATA_ORDERING.items()
    }


def _metadata_sources(catalog: Dict[str, Any], selected: List[Dict[str, Any]]) -> Dict[str, str]:
    defaults = dict((catalog or {}).get("metadata_source_defaults") or {})
    return {
        "duration": _combined_source([item.get("duration_metadata_source") for item in selected], defaults.get("duration") or "estimated"),
        "token_volume": _combined_source([item.get("token_volume_metadata_source") for item in selected], defaults.get("token_volume") or "estimated"),
        "failure_rate": _combined_source([item.get("failure_rate_metadata_source") for item in selected], defaults.get("failure_rate") or "unknown"),
        "calibration_status": defaults.get("calibration_status") or "unknown",
    }


def _combined_source(values: List[Any], fallback: str) -> str:
    normalized = [str(value or "").strip() or fallback for value in list(values or [])]
    cleaned = _dedupe_strings(normalized) or [fallback]
    return cleaned[0] if len(set(cleaned)) == 1 else "mixed"


def _metadata_confidence(sources: Dict[str, str]) -> str:
    values = {
        str((sources or {}).get(field) or "").strip()
        for field in ("duration", "token_volume", "failure_rate")
        if str((sources or {}).get(field) or "").strip()
    }
    if "unknown" in values:
        return "unknown"
    if "mixed" in values:
        return "mixed"
    if values == {"observed"}:
        return "observed"
    return "estimated"


def _dedupe_strings(values: Optional[List[Any]]) -> List[str]:
    """Return de-duplicated, non-empty string values while preserving order."""
    cleaned: List[str] = []
    for value in list(values or []):
        normalized = str(value or "").strip()
        if normalized and normalized not in cleaned:
            cleaned.append(normalized)
    return cleaned


def _infer_use_case_from_groups(group_ids: List[str], suites: Dict[str, Dict[str, Any]]) -> Optional[str]:
    selected_groups = set(_dedupe_strings(group_ids))
    if not selected_groups:
        return None
    inferred_use_cases = []
    for suite in suites.values():
        suite_groups = set(_dedupe_strings(suite.get("default_group_ids")))
        if not (selected_groups & suite_groups):
            continue
        use_case = str(suite.get("primary_use_case") or "").strip()
        if use_case and use_case not in inferred_use_cases:
            inferred_use_cases.append(use_case)
    if len(inferred_use_cases) == 1:
        return inferred_use_cases[0]
    return None
