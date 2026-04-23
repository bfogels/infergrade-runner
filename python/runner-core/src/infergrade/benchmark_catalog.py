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
        return {
            "scope": "decision",
            "scope_label": "Decision suite",
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
    ordering = _metadata_ordering(payload)
    return {
        "scope": scope,
        "scope_label": "Reference suite" if scope == "reference" else "Decision suite",
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
    available_reference = [
        check_id
        for check_id, check in checks.items()
        if check.get("suite_scope") == "reference" and check_id not in selected_ids and check.get("status", "available") != "planned"
    ]
    planned = list(payload.get("planned_benchmark_candidates") or []) + [
        {
            "check_id": check_id,
            "display_name": check.get("display_name"),
            "value": check.get("planned_value"),
            "implementation_risk": check.get("implementation_risk"),
            "suite_placement": check.get("suite_placement") or check.get("group_id"),
        }
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
            {
                "check_id": check_id,
                "display_name": checks[check_id].get("display_name"),
                "description": checks[check_id].get("description"),
                "evidence_kind": checks[check_id].get("evidence_kind"),
                "group_id": checks[check_id].get("group_id"),
                "suite_scope": checks[check_id].get("suite_scope"),
                "effort_level": checks[check_id].get("effort_level"),
                "expected_duration_band": checks[check_id].get("expected_duration_band"),
                "token_volume_band": checks[check_id].get("token_volume_band"),
                "resumability_boundary": checks[check_id].get("resumability_boundary"),
                "execution_pattern": checks[check_id].get("execution_pattern"),
                "selection_guidance": checks[check_id].get("selection_guidance"),
                "status": checks[check_id].get("status", "available"),
            }
            for check_id in normalized["check_ids"]
            if check_id in checks
        ],
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
