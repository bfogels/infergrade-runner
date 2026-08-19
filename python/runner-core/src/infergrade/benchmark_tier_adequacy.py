"""Mechanical audit for capability benchmark tier sampling contracts."""

import hashlib
import json
from collections import Counter
from importlib import resources
from pathlib import Path
from typing import Any, Dict, Optional

from infergrade.benchmark_catalog import check_index, load_capability_catalog
from infergrade.capabilities import CAPABILITY_BENCHMARKS, _native_benchmark_cases
from infergrade.longbench_selection import load_longbench_selection_manifest
from infergrade.selection_identity import (
    SELECTION_DIGEST_ALGORITHMS,
    selection_digest,
    selection_digest_algorithm_for_execution_mode,
)


TIER_NAMES = ("canary", "standard", "gold")
SAMPLING_STRATEGIES = {
    "balanced_tier_blocks",
    "coverage_balanced_hash_rank",
    "global_hash_rank",
    "pinned_semantic_order",
    "stratum_round_robin_hash_rank",
}
EXACT_SELECTION_IDENTITY_POLICY = "exact_selected_case_ids_sha256_v1"
STATIC_FIXTURE_MANIFESTS = {
    "repository_edit_smoke_v1": (
        "infergrade.audit_manifests",
        "repository_edit_fixture_manifest.json",
    ),
}
PROMPT_FREE_SELECTION_MANIFESTS = {"longbench_v2_local_reference_v1"}


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
        expected_digest_algorithm = selection_digest_algorithm_for_execution_mode(
            spec.execution_mode
        )
        declared_digest_algorithm = policy.get("selection_digest_algorithm")
        if declared_digest_algorithm not in SELECTION_DIGEST_ALGORITHMS:
            benchmark_errors.append("selection_digest_algorithm_invalid")
            digest_algorithm = expected_digest_algorithm
        else:
            digest_algorithm = str(declared_digest_algorithm)
            if digest_algorithm != expected_digest_algorithm:
                benchmark_errors.append("selection_digest_algorithm_mismatch")
        declared_limits = policy.get("case_limits")
        if declared_limits != case_limits:
            benchmark_errors.append("case_limits_mismatch")
        if spec.execution_mode == "native":
            fixture_verification = _audit_native_fixture(
                spec,
                policy,
                case_limits,
                digest_algorithm,
            )
            benchmark_errors.extend(fixture_verification["errors"])
        elif benchmark_id in PROMPT_FREE_SELECTION_MANIFESTS:
            fixture_verification = _audit_prompt_free_selection_manifest(
                spec,
                policy,
                case_limits,
                digest_algorithm,
            )
            benchmark_errors.extend(fixture_verification["errors"])
        elif benchmark_id in STATIC_FIXTURE_MANIFESTS:
            fixture_verification = _audit_static_fixture_manifest(
                spec,
                policy,
                case_limits,
                digest_algorithm,
            )
            benchmark_errors.extend(fixture_verification["errors"])
        else:
            fixture_verification = {
                "status": "external_runtime_not_materialized",
                "ready": None,
                "source_fixture_case_count": None,
                "unique_case_id_count": None,
                "tier_coverage_contract": False,
                "source_fixture_revision": None,
                "source_fixture_sha256": None,
                "source_fixture_status": "external_runtime_only",
                "selection_digest_algorithm": digest_algorithm,
                "selection_digest_verified": False,
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
                "selection_digest_algorithm": declared_digest_algorithm,
                "fixture_verification": fixture_verification,
                "errors": benchmark_errors,
            }
        )
    extra_ids = sorted(set(policies) - expected_ids)
    errors.extend("%s:unexpected_tier_sampling_policy" % item for item in extra_ids)
    return {
        "artifact_kind": "benchmark_tier_adequacy_audit",
        "artifact_spec_version": "0.4.0",
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
            and item["fixture_verification"]["status"] == "materialized_verified"
        ),
        "verified_static_fixture_manifest_count": sum(
            1
            for item in benchmark_reports
            if item["fixture_verification"]["status"]
            in {"source_fixture_verified", "source_manifest_verified"}
        ),
        "verified_prompt_free_selection_manifest_count": sum(
            1
            for item in benchmark_reports
            if item["fixture_verification"]["status"] == "selection_manifest_verified"
        ),
        "verified_tier_coverage_contract_count": sum(
            1
            for item in benchmark_reports
            if item["fixture_verification"]["tier_coverage_contract"]
            and item["fixture_verification"]["ready"]
        ),
        "declared_selection_digest_algorithm_count": sum(
            1
            for item in benchmark_reports
            if item["selection_digest_algorithm"] in SELECTION_DIGEST_ALGORITHMS
        ),
        "materialized_selection_digest_verified_count": sum(
            1
            for item in benchmark_reports
            if item["fixture_verification"]["selection_digest_verified"]
        ),
        "runtime_only_selection_digest_contract_count": sum(
            1
            for item in benchmark_reports
            if item["fixture_verification"]["status"]
            == "external_runtime_not_materialized"
            and item["selection_digest_algorithm"] in SELECTION_DIGEST_ALGORITHMS
        ),
        "benchmarks": benchmark_reports,
        "errors": errors,
        "claim_boundary": (
            "This audit validates declared tier-selection and exact-selection identity contracts, including "
            "a versioned selected-case digest serialization. Native "
            "fixtures are also materialized to verify case counts, unique identities, and declared per-tier "
            "category coverage. The first-party repository-edit fixture is verified from its bundled exact-source "
            "manifest and, in source checkouts, against the container fixture itself. The prompt-free LongBench "
            "manifest verifies raw upstream IDs, tier prefixes, and the public domain/difficulty/length projection; "
            "its image remains responsible for source bytes and prompts. Structural coverage does not prove empirical difficulty, "
            "score reliability, source representativeness, or absence of benchmark leakage."
        ),
    }


def _audit_prompt_free_selection_manifest(
    spec: Any,
    policy: Dict[str, Any],
    case_limits: Dict[str, int],
    digest_algorithm: str,
) -> Dict[str, Any]:
    """Audit LongBench identity/strata without vendoring prompt-bearing rows."""
    errors = []
    try:
        manifest = load_longbench_selection_manifest()
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {
            "status": "selection_manifest_invalid",
            "ready": False,
            "source_fixture_case_count": None,
            "unique_case_id_count": None,
            "tier_coverage_contract": False,
            "source_fixture_revision": None,
            "source_fixture_sha256": None,
            "source_fixture_status": "selection_manifest_unreadable",
            "selection_digest_algorithm": digest_algorithm,
            "selection_digest_verified": False,
            "tiers": [],
            "errors": ["selection_manifest_unreadable:%s" % type(exc).__name__],
        }
    if manifest.get("benchmark_id") != spec.benchmark_id:
        errors.append("selection_manifest_benchmark_mismatch")
    if manifest.get("selection_digest_algorithm") != digest_algorithm:
        errors.append("selection_manifest_digest_algorithm_mismatch")
    if policy.get("selection_policy") is not None and manifest.get("selection_policy") != policy.get("selection_policy"):
        errors.append("selection_manifest_policy_mismatch")
    if manifest.get("tier_prefix_counts") != case_limits:
        errors.append("selection_manifest_tier_prefixes_mismatch")
    selected_ids = list(manifest.get("selected_ids") or [])
    projection = list(manifest.get("selection_projection") or [])
    if len(selected_ids) != manifest.get("case_count") or len(projection) != len(selected_ids):
        errors.append("selection_manifest_case_count_mismatch")
    allowed_projection_keys = {"_id", "domain", "sub_domain", "difficulty", "length"}
    projection_valid = all(
        isinstance(item, dict)
        and set(item) == allowed_projection_keys
        and all(isinstance(item[field], str) and item[field] for field in allowed_projection_keys)
        for item in projection
    )
    if not projection_valid:
        errors.append("selection_manifest_projection_invalid")
    projection_ids = [item.get("_id") for item in projection if isinstance(item, dict)]
    if projection_ids != selected_ids:
        errors.append("selection_manifest_projection_order_mismatch")
    digest_ids = [str(item) for item in selected_ids]
    if (
        not all(isinstance(item, str) and item for item in selected_ids)
        or manifest.get("selection_sha256") != selection_digest(digest_ids, digest_algorithm)
    ):
        errors.append("selection_manifest_raw_digest_mismatch")
    cases = [
        {
            "task_id": "longbench_v2/%s" % item["_id"],
            "domain": item["domain"],
            "difficulty": item["difficulty"],
            "length": item["length"],
        }
        for item in projection
        if projection_valid and item.get("_id")
    ]
    verification = _audit_fixture_cases(
        cases=cases,
        policy=policy,
        case_limits=case_limits,
        digest_algorithm=digest_algorithm,
        identity_error_prefix="selection_manifest",
        success_status="selection_manifest_verified",
        invalid_status="selection_manifest_invalid",
        source_fixture_revision=manifest.get("dataset_revision"),
        source_fixture_sha256=manifest.get("dataset_sha256"),
        source_fixture_status="prompt_free_selection_manifest",
    )
    verification["errors"] = errors + verification["errors"]
    verification["ready"] = not verification["errors"]
    verification["status"] = (
        "selection_manifest_verified" if verification["ready"] else "selection_manifest_invalid"
    )
    verification["snapshot_sha256"] = manifest.get("snapshot_sha256")
    verification["raw_selection_sha256"] = manifest.get("selection_sha256")
    verification["prompt_free"] = True
    return verification


def _audit_native_fixture(
    spec: Any,
    policy: Dict[str, Any],
    case_limits: Dict[str, int],
    digest_algorithm: str,
) -> Dict[str, Any]:
    return _audit_fixture_cases(
        cases=_native_benchmark_cases(spec),
        policy=policy,
        case_limits=case_limits,
        digest_algorithm=digest_algorithm,
        identity_error_prefix="native_fixture",
        success_status="materialized_verified",
        invalid_status="materialized_invalid",
        source_fixture_revision=None,
        source_fixture_sha256=None,
        source_fixture_status="materialized_native_fixture",
    )


def load_static_fixture_manifest(benchmark_id: str) -> Dict[str, Any]:
    """Load a bundled first-party fixture manifest by benchmark id."""
    package, filename = STATIC_FIXTURE_MANIFESTS[benchmark_id]
    with resources.open_text(package, filename, encoding="utf-8") as handle:
        return json.load(handle)


def _audit_static_fixture_manifest(
    spec: Any,
    policy: Dict[str, Any],
    case_limits: Dict[str, int],
    digest_algorithm: str,
) -> Dict[str, Any]:
    manifest = load_static_fixture_manifest(spec.benchmark_id)
    errors = []
    if manifest.get("artifact_kind") != "repository_edit_fixture_manifest":
        errors.append("static_fixture_manifest_kind_mismatch")
    if manifest.get("benchmark_id") != spec.benchmark_id:
        errors.append("static_fixture_manifest_benchmark_mismatch")
    if not str(manifest.get("fixture_revision") or "").strip():
        errors.append("static_fixture_manifest_revision_missing")
    source_sha256 = str(manifest.get("source_fixture_sha256") or "")
    if len(source_sha256) != 64 or any(character not in "0123456789abcdef" for character in source_sha256):
        errors.append("static_fixture_manifest_source_sha256_invalid")
    if manifest.get("selection_policy") != "pinned_fixture_order_v1":
        errors.append("static_fixture_manifest_selection_policy_mismatch")
    raw_cases = manifest.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases or not all(
        isinstance(item, dict) for item in raw_cases
    ):
        errors.append("static_fixture_manifest_cases_invalid")
        cases = []
    else:
        cases = [dict(item) for item in raw_cases]

    source_status, source_errors = _verify_static_source_fixture(manifest)
    errors.extend(source_errors)
    verification = _audit_fixture_cases(
        cases=cases,
        policy=policy,
        case_limits=case_limits,
        digest_algorithm=digest_algorithm,
        identity_error_prefix="static_fixture_manifest",
        success_status=(
            "source_fixture_verified"
            if source_status == "source_fixture_verified"
            else "source_manifest_verified"
        ),
        invalid_status="source_manifest_invalid",
        source_fixture_revision=manifest.get("fixture_revision"),
        source_fixture_sha256=source_sha256 or None,
        source_fixture_status=source_status,
    )
    verification["errors"] = errors + verification["errors"]
    verification["ready"] = not verification["errors"]
    if verification["errors"]:
        verification["status"] = "source_manifest_invalid"
    return verification


def _verify_static_source_fixture(manifest: Dict[str, Any]) -> tuple:
    source_path = _static_source_fixture_path()
    if source_path is None:
        return "not_available_in_installed_package", []
    errors = []
    source_bytes = source_path.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != manifest.get("source_fixture_sha256"):
        errors.append("static_source_fixture_sha256_mismatch")
    try:
        payload = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return "source_fixture_invalid", errors + ["static_source_fixture_json_invalid"]
    if payload.get("fixture_revision") != manifest.get("fixture_revision"):
        errors.append("static_source_fixture_revision_mismatch")
    source_cases = [
        {
            "task_id": str(item.get("task_id") or ""),
            "category": str(item.get("category") or ""),
        }
        for item in list(payload.get("fixtures") or [])
        if isinstance(item, dict)
    ]
    if source_cases != list(manifest.get("cases") or []):
        errors.append("static_source_fixture_case_manifest_mismatch")
    return (
        "source_fixture_verified" if not errors else "source_fixture_invalid",
        errors,
    )


def _static_source_fixture_path() -> Optional[Path]:
    relative = Path("containers/capability-repo-edit/fixtures.json")
    for parent in Path(__file__).resolve().parents:
        candidate = parent / relative
        if candidate.is_file():
            return candidate
    return None


def _audit_fixture_cases(
    cases: list,
    policy: Dict[str, Any],
    case_limits: Dict[str, int],
    digest_algorithm: str,
    identity_error_prefix: str,
    success_status: str,
    invalid_status: str,
    source_fixture_revision: Any,
    source_fixture_sha256: Optional[str],
    source_fixture_status: str,
) -> Dict[str, Any]:
    errors = []
    case_ids = [
        str(item.get("task_id") or item.get("case_id") or "").strip()
        for item in cases
    ]
    if any(not case_id for case_id in case_ids):
        errors.append("%s_missing_case_identity" % identity_error_prefix)
    if len(case_ids) != len(set(case_ids)):
        errors.append("%s_duplicate_case_identity" % identity_error_prefix)
    maximum_limit = max(case_limits.values()) if case_limits else 0
    if len(cases) < maximum_limit:
        errors.append("%s_below_maximum_tier_limit" % identity_error_prefix)

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
            errors.append("%s_tier_case_count_mismatch:%s" % (identity_error_prefix, tier))
        field_counts = {
            field: Counter(item.get(field) for item in selected if field in item)
            for field in stratification_fields
        }
        for field in stratification_fields:
            if any(field not in item for item in selected):
                errors.append(
                    "%s_missing_stratification_field:%s:%s"
                    % (identity_error_prefix, tier, field)
                )

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
                "selection_digest_algorithm": digest_algorithm,
                "selection_sha256": selection_digest(
                    case_ids[:limit], digest_algorithm
                ),
                "coverage_requirements": requirement_reports,
            }
        )

    expected_tier_selections = policy.get("expected_tier_selections")
    expected_selection_errors = _audit_expected_tier_selections(
        tier_reports,
        expected_tier_selections,
        identity_error_prefix,
    )
    errors.extend(expected_selection_errors)

    return {
        "status": success_status if not errors else invalid_status,
        "ready": not errors,
        "source_fixture_case_count": len(cases),
        "unique_case_id_count": len(set(case_ids) - {""}),
        "tier_coverage_contract": has_coverage_contract,
        "source_fixture_revision": source_fixture_revision,
        "source_fixture_sha256": source_fixture_sha256,
        "source_fixture_status": source_fixture_status,
        "selection_digest_algorithm": digest_algorithm,
        "selection_digest_verified": (
            digest_algorithm in SELECTION_DIGEST_ALGORITHMS
            and not any(not case_id for case_id in case_ids)
            and len(case_ids) == len(set(case_ids))
            and len(cases) >= maximum_limit
        ),
        "expected_tier_selections": expected_tier_selections,
        "expected_tier_selections_verified": (
            isinstance(expected_tier_selections, dict)
            and not expected_selection_errors
        ),
        "tiers": tier_reports,
        "errors": errors,
    }


def _audit_expected_tier_selections(
    tier_reports: list,
    expected_tier_selections: Any,
    identity_error_prefix: str,
) -> list:
    """Compare materialized tier identities with the catalog's pinned values."""
    error_prefix = "%s_expected_tier_selection" % identity_error_prefix
    if not isinstance(expected_tier_selections, dict):
        return ["%s_missing" % error_prefix]

    errors = []
    actual_by_tier = {str(item.get("tier")): item for item in tier_reports}
    for tier in TIER_NAMES:
        if tier not in actual_by_tier:
            continue
        expected = expected_tier_selections.get(tier)
        if not isinstance(expected, dict):
            errors.append("%s_missing_tier:%s" % (error_prefix, tier))
            continue
        actual = actual_by_tier[tier]
        expected_count = expected.get("case_count")
        if (
            isinstance(expected_count, bool)
            or not isinstance(expected_count, int)
            or expected_count != actual.get("selected_case_count")
        ):
            errors.append("%s_case_count_mismatch:%s" % (error_prefix, tier))
        expected_algorithm = expected.get("selection_digest_algorithm")
        if expected_algorithm != actual.get("selection_digest_algorithm"):
            errors.append("%s_algorithm_mismatch:%s" % (error_prefix, tier))
        expected_digest = expected.get("selection_sha256")
        if expected_digest != actual.get("selection_sha256"):
            errors.append("%s_digest_mismatch:%s" % (error_prefix, tier))

    expected_unknown_tiers = sorted(set(expected_tier_selections) - set(actual_by_tier))
    errors.extend(
        "%s_unknown_tier:%s" % (error_prefix, tier)
        for tier in expected_unknown_tiers
    )
    return errors


def _json_scalar_identity(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
