"""Mechanical audit for capability benchmark tier sampling contracts."""

import hashlib
import json
from collections import Counter
from typing import Any, Dict, Optional

from infergrade.benchmark_catalog import check_index, load_capability_catalog
from infergrade.capabilities import CAPABILITY_BENCHMARKS, _native_benchmark_cases


TIER_NAMES = ("canary", "standard", "gold")
SAMPLING_STRATEGIES = {
    "balanced_tier_blocks",
    "coverage_balanced_hash_rank",
    "global_hash_rank",
    "pinned_semantic_order",
    "stratum_round_robin_hash_rank",
}
EXACT_SELECTION_IDENTITY_POLICY = "exact_selected_case_ids_sha256_v1"


def audit_benchmark_tier_adequacy(
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Require every varying-size capability benchmark to declare exact tier identity."""
    payload = catalog or load_capability_catalog()
    checks = check_index(payload)
    policies = payload.get("tier_sampling_policies")
    errors = []
    if not isinstance(policies, dict):
        policies = {}
        errors.append("tier_sampling_policies must be an object")
    benchmark_reports = []
    expected_ids = set()
    for benchmark_id, spec in sorted(CAPABILITY_BENCHMARKS.items()):
        case_limits = {
            tier: int(spec.case_limits[tier])
            for tier in TIER_NAMES
            if tier in spec.case_limits
        }
        if len(set(case_limits.values())) <= 1:
            continue
        expected_ids.add(benchmark_id)
        policy = policies.get(benchmark_id)
        benchmark_errors = []
        if benchmark_id not in checks:
            benchmark_errors.append("missing_catalog_check")
        if not isinstance(policy, dict):
            benchmark_errors.append("missing_tier_sampling_policy")
            policy = {}
        strategy = str(policy.get("strategy") or "")
        if strategy not in SAMPLING_STRATEGIES:
            benchmark_errors.append("invalid_sampling_strategy")
        fields = policy.get("stratification_fields")
        if not isinstance(fields, list) or not all(
            isinstance(item, str) and item.strip() for item in fields
        ):
            benchmark_errors.append("invalid_stratification_fields")
        elif strategy in {
            "balanced_tier_blocks",
            "coverage_balanced_hash_rank",
            "stratum_round_robin_hash_rank",
        } and not fields:
            benchmark_errors.append("missing_stratification_fields")
        if policy.get("selection_identity_policy") != EXACT_SELECTION_IDENTITY_POLICY:
            benchmark_errors.append("selection_identity_not_exact")
        declared_limits = policy.get("case_limits")
        if declared_limits != case_limits:
            benchmark_errors.append("case_limits_mismatch")
        if spec.execution_mode == "native":
            fixture_verification = _audit_native_fixture(
                spec,
                policy,
                case_limits,
            )
            benchmark_errors.extend(fixture_verification["errors"])
        else:
            fixture_verification = {
                "status": "external_runtime_not_materialized",
                "ready": None,
                "source_fixture_case_count": None,
                "unique_case_id_count": None,
                "tier_coverage_contract": False,
                "tiers": [],
                "errors": [],
            }
        errors.extend(
            "%s:%s" % (benchmark_id, error)
            for error in benchmark_errors
        )
        benchmark_reports.append(
            {
                "benchmark_id": benchmark_id,
                "status": "ready" if not benchmark_errors else "invalid",
                "ready": not benchmark_errors,
                "case_limits": case_limits,
                "strategy": strategy or None,
                "stratification_fields": list(fields) if isinstance(fields, list) else [],
                "selection_identity_policy": policy.get("selection_identity_policy"),
                "fixture_verification": fixture_verification,
                "errors": benchmark_errors,
            }
        )
    extra_ids = sorted(set(policies) - expected_ids)
    errors.extend("%s:unexpected_tier_sampling_policy" % item for item in extra_ids)
    return {
        "artifact_kind": "benchmark_tier_adequacy_audit",
        "artifact_spec_version": "0.2.0",
        "catalog_version": payload.get("catalog_version"),
        "status": "ready" if not errors else "invalid",
        "ready": not errors,
        "varying_tier_benchmark_count": len(benchmark_reports),
        "materialized_native_fixture_count": sum(
            1
            for item in benchmark_reports
            if item["fixture_verification"]["status"] == "materialized_verified"
        ),
        "native_tier_coverage_contract_count": sum(
            1
            for item in benchmark_reports
            if item["fixture_verification"]["tier_coverage_contract"]
        ),
        "benchmarks": benchmark_reports,
        "errors": errors,
        "claim_boundary": (
            "This audit validates declared tier-selection and exact-selection identity contracts. Native "
            "fixtures are also materialized to verify case counts, unique identities, and declared per-tier "
            "category coverage. Container-owned datasets remain runtime-verified only. Structural coverage "
            "does not prove empirical difficulty, score reliability, source representativeness, or absence "
            "of benchmark leakage."
        ),
    }


def _audit_native_fixture(
    spec: Any,
    policy: Dict[str, Any],
    case_limits: Dict[str, int],
) -> Dict[str, Any]:
    errors = []
    cases = _native_benchmark_cases(spec)
    case_ids = [
        str(item.get("task_id") or item.get("case_id") or "").strip()
        for item in cases
    ]
    if any(not case_id for case_id in case_ids):
        errors.append("native_fixture_missing_case_identity")
    if len(case_ids) != len(set(case_ids)):
        errors.append("native_fixture_duplicate_case_identity")
    maximum_limit = max(case_limits.values()) if case_limits else 0
    if len(cases) < maximum_limit:
        errors.append("native_fixture_below_maximum_tier_limit")

    fields = policy.get("stratification_fields")
    stratification_fields = list(fields) if isinstance(fields, list) else []
    requirements = policy.get("tier_coverage_requirements")
    has_coverage_contract = bool(stratification_fields)
    if has_coverage_contract and not isinstance(requirements, dict):
        errors.append("missing_tier_coverage_requirements")
        requirements = {}
    elif not has_coverage_contract and requirements is not None:
        errors.append("unexpected_tier_coverage_requirements")
        requirements = requirements if isinstance(requirements, dict) else {}
    else:
        requirements = requirements if isinstance(requirements, dict) else {}

    if has_coverage_contract:
        for tier in sorted(set(case_limits) - set(requirements)):
            errors.append("tier_coverage_missing_tier:%s" % tier)
        for tier in sorted(set(requirements) - set(case_limits)):
            errors.append("tier_coverage_unknown_tier:%s" % tier)

    tier_reports = []
    for tier in TIER_NAMES:
        if tier not in case_limits:
            continue
        limit = case_limits[tier]
        selected = cases[:limit]
        if len(selected) != limit:
            errors.append("native_fixture_tier_case_count_mismatch:%s" % tier)
        field_counts = {
            field: Counter(item.get(field) for item in selected if field in item)
            for field in stratification_fields
        }
        for field in stratification_fields:
            if any(field not in item for item in selected):
                errors.append("native_fixture_missing_stratification_field:%s:%s" % (tier, field))

        tier_requirement = requirements.get(tier)
        if has_coverage_contract and not isinstance(tier_requirement, dict):
            errors.append("tier_coverage_invalid_tier:%s" % tier)
            tier_requirement = {}
        elif not isinstance(tier_requirement, dict):
            tier_requirement = {}
        if has_coverage_contract:
            for field in sorted(set(stratification_fields) - set(tier_requirement)):
                errors.append("tier_coverage_missing_field:%s:%s" % (tier, field))
            for field in sorted(set(tier_requirement) - set(stratification_fields)):
                errors.append("tier_coverage_unknown_field:%s:%s" % (tier, field))

        requirement_reports = []
        for field in stratification_fields:
            rule = tier_requirement.get(field)
            if not isinstance(rule, dict):
                continue
            required_values = rule.get("required_values")
            if (
                not isinstance(required_values, list)
                or not required_values
                or any(not isinstance(value, (str, int, float, bool)) for value in required_values)
                or len({_json_scalar_identity(value) for value in required_values}) != len(required_values)
            ):
                errors.append("tier_coverage_invalid_required_values:%s:%s" % (tier, field))
                required_values = []
            minimum_cases = rule.get("minimum_cases_per_required_value")
            if (
                isinstance(minimum_cases, bool)
                or not isinstance(minimum_cases, int)
                or minimum_cases <= 0
            ):
                errors.append("tier_coverage_invalid_minimum_cases:%s:%s" % (tier, field))
                minimum_cases = None
            counts = field_counts.get(field, Counter())
            missing_values = [value for value in required_values if counts[value] == 0]
            undercovered_values = [
                value
                for value in required_values
                if minimum_cases is not None and 0 < counts[value] < minimum_cases
            ]
            if missing_values:
                errors.append("tier_coverage_missing_required_values:%s:%s" % (tier, field))
            if undercovered_values:
                errors.append("tier_coverage_under_minimum_cases:%s:%s" % (tier, field))
            requirement_reports.append(
                {
                    "field": field,
                    "required_values": required_values,
                    "minimum_cases_per_required_value": minimum_cases,
                    "observed_required_value_counts": [
                        {"value": value, "case_count": counts[value]}
                        for value in required_values
                    ],
                    "ready": bool(required_values)
                    and minimum_cases is not None
                    and not missing_values
                    and not undercovered_values,
                }
            )
        tier_reports.append(
            {
                "tier": tier,
                "selected_case_count": len(selected),
                "selection_sha256": _case_id_digest(case_ids[:limit]),
                "coverage_requirements": requirement_reports,
            }
        )

    return {
        "status": "materialized_verified" if not errors else "materialized_invalid",
        "ready": not errors,
        "source_fixture_case_count": len(cases),
        "unique_case_id_count": len(set(case_ids) - {""}),
        "tier_coverage_contract": has_coverage_contract,
        "tiers": tier_reports,
        "errors": errors,
    }


def _case_id_digest(case_ids: list) -> str:
    encoded = json.dumps(sorted(case_ids), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_scalar_identity(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
