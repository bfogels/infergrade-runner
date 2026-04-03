"""Runner-owned capability suite and benchmark selection helpers."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from infergrade.models import RunRequest


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
    return {
        "catalog_version": payload.get("catalog_version"),
        "shortcut_id": request.benchmark_shortcut_id,
        "capability_suite_ids": list(normalized["suite_ids"]),
        "benchmark_group_ids": list(normalized["group_ids"]),
        "benchmark_check_ids": list(normalized["check_ids"]),
        "capability_suites": [
            {
                "suite_id": suite_id,
                "display_name": suites[suite_id].get("display_name"),
                "description": suites[suite_id].get("description"),
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
            }
            for check_id in normalized["check_ids"]
            if check_id in checks
        ],
    }


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
