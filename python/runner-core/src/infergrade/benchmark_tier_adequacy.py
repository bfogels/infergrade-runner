"""Mechanical audit for capability benchmark tier sampling contracts."""

from typing import Any, Dict, Optional

from infergrade.benchmark_catalog import check_index, load_capability_catalog
from infergrade.capabilities import CAPABILITY_BENCHMARKS


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
                "errors": benchmark_errors,
            }
        )
    extra_ids = sorted(set(policies) - expected_ids)
    errors.extend("%s:unexpected_tier_sampling_policy" % item for item in extra_ids)
    return {
        "artifact_kind": "benchmark_tier_adequacy_audit",
        "artifact_spec_version": "0.1.0",
        "catalog_version": payload.get("catalog_version"),
        "status": "ready" if not errors else "invalid",
        "ready": not errors,
        "varying_tier_benchmark_count": len(benchmark_reports),
        "benchmarks": benchmark_reports,
        "errors": errors,
        "claim_boundary": (
            "This audit validates declared tier-selection and exact-selection identity contracts. "
            "It does not prove empirical difficulty, score reliability, or absence of benchmark leakage."
        ),
    }
