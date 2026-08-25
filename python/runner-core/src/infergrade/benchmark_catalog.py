"""Runner-owned capability suite and benchmark selection helpers."""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from infergrade.constants import DEFAULT_GENERATION_PRESET
from infergrade.generation_policies import REASONING_CONSTRAINT_STRESS_THINKING_POLICY_ID
from infergrade.models import RunRequest
from infergrade.paths import runner_root
from infergrade.profiles import DIRECT_ANSWER_GENERATION_PRESET
from infergrade.reasoning_constraint_stress_v2 import (
    EXPECTED_ANSWER_VECTOR,
    FINAL_ANSWER_PARSER_ID,
    FIXTURE_REVISION,
    FIXTURE_SHA256,
    SCORING_POLICY,
    SELECTION_DIGEST_ALGORITHM,
    SELECTION_DIGEST_SHA256,
)
from infergrade.reasoning_constraint_stress_v2_content import (
    BENCHMARK_ID as CONTENT_PACK_BENCHMARK_ID,
    FAMILY_ORDER as CONTENT_PACK_FAMILY_ORDER,
    FIXTURE_REVISION as CONTENT_PACK_FIXTURE_REVISION,
    FULL_FIXTURE_SHA256 as CONTENT_PACK_FULL_FIXTURE_SHA256,
    FULL_SELECTION_SHA256 as CONTENT_PACK_FULL_SELECTION_SHA256,
    GENERATOR_ALGORITHM as CONTENT_PACK_GENERATOR_ALGORITHM,
    GENERATOR_ID as CONTENT_PACK_GENERATOR_ID,
    GENERATOR_REVISION as CONTENT_PACK_GENERATOR_REVISION,
    GENERATOR_SEED_SHA256 as CONTENT_PACK_GENERATOR_SEED_SHA256,
    LOCKED_FIXTURE_SHA256 as CONTENT_PACK_LOCKED_FIXTURE_SHA256,
    LOCKED_FULL_SELECTION_SHA256 as CONTENT_PACK_LOCKED_FULL_SELECTION_SHA256,
    LOCKED_GENERATOR_SEED_SHA256 as CONTENT_PACK_LOCKED_GENERATOR_SEED_SHA256,
    LOCKED_TIER_COVERAGE as CONTENT_PACK_LOCKED_TIER_COVERAGE,
    LOCKED_TIER_SELECTION_DIGESTS as CONTENT_PACK_LOCKED_TIER_SELECTION_DIGESTS,
    SELECTION_DIGEST_ALGORITHM as CONTENT_PACK_SELECTION_DIGEST_ALGORITHM,
    STRUCTURAL_LEVEL_ORDER as CONTENT_PACK_STRUCTURAL_LEVEL_ORDER,
    TIER_COVERAGE as CONTENT_PACK_TIER_COVERAGE,
    TIER_PREFIX_COUNTS as CONTENT_PACK_TIER_PREFIX_COUNTS,
    TIER_SELECTION_DIGESTS as CONTENT_PACK_TIER_SELECTION_DIGESTS,
    VARIANT_ORDER as CONTENT_PACK_VARIANT_ORDER,
)
from infergrade.reasoning_constraint_stress_v2_qualification import (
    BENCHMARK_ID as REASONING_V2_QUALIFICATION_BENCHMARK_ID,
    CLAIM_BOUNDARY as REASONING_V2_QUALIFICATION_CLAIM_BOUNDARY,
    CONTENT_PACK_BENCHMARK_ID as REASONING_V2_QUALIFICATION_CONTENT_PACK_ID,
    FAILURE_DENOMINATOR_POLICY_ID as REASONING_V2_FAILURE_DENOMINATOR_POLICY_ID,
    GENERATION_POLICY_ID as REASONING_V2_QUALIFICATION_GENERATION_POLICY_ID,
    QUALIFICATION_REVISION as REASONING_V2_QUALIFICATION_REVISION,
    POLICY_ENFORCEMENT_REQUESTED_UNVERIFIED as REASONING_V2_POLICY_ENFORCEMENT_STATE,
    qualification_tier_metadata,
)

FALLBACK_METADATA_ORDERING = {
    "effort_level": ["short", "low", "balanced", "medium", "deep", "high"],
    "expected_duration_band": [
        "1-5 min",
        "5-15 min",
        "10-25 min",
        "10-30 min",
        "15-45 min",
        "25-60 min",
        "15-90 min",
        "45-120 min",
        "90-180 min",
    ],
    "token_volume_band": ["tiny", "small", "medium", "large"],
}
SUPPORTED_COVERAGE_GENERATION_PRESETS = {
    DEFAULT_GENERATION_PRESET,
    DIRECT_ANSWER_GENERATION_PRESET,
}
DIRECT_ANSWER_PROTOCOL_CHECK_IDS = {
    "mmlu_pro_reference_v1",
    "gpqa_diamond_reference_v1",
    "longbench_v2_local_reference_v1",
}

# Keep the legacy fixture and scorer available for forensic/unit-test use, but
# make the known direct-answer reasoning protocol impossible to select as a
# real benchmark until a reasoning-capable successor is qualified.
QUARANTINED_BENCHMARK_REASON_CODES = {
    "reasoning_constraint_stress_v1": "legacy_direct_no_think_v1_no_capability_validity_evidence",
}
BENCHMARK_SELECTION_QUARANTINE_PREFIX = "benchmark_quarantined"
BENCHMARK_CANARY_ONLY_PREFIX = "benchmark_canary_only"
FOUNDATION_CANARY_METADATA_ERROR = "metadata_invalid"
FOUNDATION_CANARY_DISPLAY_NAME = "Reasoning constraint stress v2 foundation"
FOUNDATION_CANARY_DESCRIPTION = (
    "Foundation identity only; no benchmark, capability, score, readiness, "
    "recommendation, or release-evidence claim."
)
FOUNDATION_CANARY_NO_CLAIM_BOUNDARY = FOUNDATION_CANARY_DESCRIPTION
FOUNDATION_CANARY_SELECTION_GUIDANCE = FOUNDATION_CANARY_DESCRIPTION
FOUNDATION_CANARY_BENCHMARKS = {
    "reasoning_constraint_stress_v2": {
        "display_name": FOUNDATION_CANARY_DISPLAY_NAME,
        "description": FOUNDATION_CANARY_DESCRIPTION,
        "selection_guidance": FOUNDATION_CANARY_SELECTION_GUIDANCE,
        "claim_boundary": FOUNDATION_CANARY_NO_CLAIM_BOUNDARY,
        "canary_only": True,
        "allowed_tiers": ["canary"],
        "attestation_state": "unreviewed",
        "status": "canary_only_unreviewed",
        "runnable_status": "canary_only_unreviewed",
        "maturity": "planned",
        "default_inclusion_status": "excluded_canary_only",
        "sample_policy": (
            "Six fresh, independent synthetic cases with new identities and a locked task-id digest; "
            "fixture and parser foundation only, with no adapter or runtime execution claim."
        ),
        "fixture_revision": FIXTURE_REVISION,
        "fixture_sha256": FIXTURE_SHA256,
        "expected_answer_vector": list(EXPECTED_ANSWER_VECTOR),
        "selection_digest_algorithm": SELECTION_DIGEST_ALGORITHM,
        "selection_sha256": SELECTION_DIGEST_SHA256,
        "evidence_kind": "capability",
        "runner_target": "reasoning_constraint_stress_v2",
        "score_policy_id": SCORING_POLICY,
        "scoring_policy_id": SCORING_POLICY,
        "generation_constraint_id": FINAL_ANSWER_PARSER_ID,
        "generation_policy_id": REASONING_CONSTRAINT_STRESS_THINKING_POLICY_ID,
        "primary_score_weight": 0.0,
        "score_role": "diagnostic_only",
        "excluded_from_default_groups": True,
        "excluded_from_suites": True,
        "excluded_from_weighted_score": True,
        "excluded_from_readiness": True,
        "excluded_from_recommendation": True,
        "excluded_from_release_evidence": True,
    }
}

BENCHMARK_IDENTITY_ONLY_PREFIX = "benchmark_identity_only"
CONTENT_PACK_METADATA_ERROR = "metadata_invalid"
CONTENT_PACK_DISPLAY_NAME = "Reasoning constraint stress v2 content pack"
CONTENT_PACK_DESCRIPTION = (
    "Planned identity-only content pack: 40 SHA-derived cases across five reasoning "
    "families and four structural levels; no adapter, runtime, score, or evidence claim."
)
CONTENT_PACK_CLAIM_BOUNDARY = CONTENT_PACK_DESCRIPTION
CONTENT_PACK_SELECTION_GUIDANCE = (
    "Future benchmark content is available for identity and coverage inspection only. "
    "It is not runnable and must not inform current capability, score, readiness, "
    "recommendation, or release claims."
)
CONTENT_PACK_SAMPLE_POLICY = (
    "Forty generated cases arranged as five families x four structural levels x two variants; "
    "canary, standard, and gold are exact prefixes of 5, 20, and 40 cases with locked digests "
    "and family/level coverage. Content identity only; no execution is implemented."
)
CONTENT_PACK_PROMOTION_BLOCKERS = [
    "Complete independent review of generated prompts, family oracles, and tier coverage.",
    "Add a separately reviewed adapter only after the strict terminal policy is bound to receipts.",
    "Run representative reasoning-capable canaries and inspect malformed-output and runtime-failure distributions before any evidence role.",
]
EXPECTED_CONTENT_PACK_BENCHMARK_IDS = frozenset(
    {"reasoning_constraint_stress_v2_content_v1"}
)
CONTENT_PACK_BENCHMARKS = {
    CONTENT_PACK_BENCHMARK_ID: {
        "check_id": CONTENT_PACK_BENCHMARK_ID,
        "identity_only": True,
        "display_name": CONTENT_PACK_DISPLAY_NAME,
        "description": CONTENT_PACK_DESCRIPTION,
        "capability_facets": ["constraint_reasoning_stress_v2"],
        "temporal_scope": "static_pinned",
        "selection_guidance": CONTENT_PACK_SELECTION_GUIDANCE,
        "claim_boundary": CONTENT_PACK_CLAIM_BOUNDARY,
        "status": "planned",
        "runnable_status": "not_runnable",
        "maturity": "planned",
        "default_inclusion_status": "not_default",
        "fixture_or_dataset_revision_status": "pinned_generator_identity_only",
        "harness_status": "fixture_generator_identity_only_not_implemented",
        "expected_duration_token_volume_status": "not_estimated_identity_only",
        "sandbox_requirement": "none_fixture_only",
        "sample_policy": CONTENT_PACK_SAMPLE_POLICY,
        "promotion_blockers": list(CONTENT_PACK_PROMOTION_BLOCKERS),
        "evidence_kind": "capability",
        "surface_id": "local_reasoning_capability",
        "evidence_lane_id": "reference",
        "suite_scope": "reference",
        "group_id": None,
        "runner_target": CONTENT_PACK_BENCHMARK_ID,
        "effort_level": "deep",
        "expected_duration_band": "not estimated",
        "token_volume_band": "not estimated",
        "resumability_boundary": "benchmark",
        "execution_pattern": "fixture_generator_identity_only",
        "score_dimension": "constraint_reasoning_stress_v2_content",
        "primary_score_metric": "exact_signed_integer_accuracy",
        "score_floor": 0.0,
        "primary_score_weight": 0.0,
        "score_role": "diagnostic_only",
        "discrimination_status": "unreviewed",
        "higher_is_better": True,
        "score_policy_id": SCORING_POLICY,
        "scoring_policy_id": SCORING_POLICY,
        "generation_constraint_id": FINAL_ANSWER_PARSER_ID,
        "generation_policy_id": REASONING_CONSTRAINT_STRESS_THINKING_POLICY_ID,
        "score_breakdown_fields": [
            "correct_count",
            "total_count",
            "case_accuracy",
            "family_metrics",
            "structural_level_metrics",
            "parser_code_counts",
        ],
        "fixture_revision": CONTENT_PACK_FIXTURE_REVISION,
        "fixture_sha256": CONTENT_PACK_LOCKED_FIXTURE_SHA256,
        "full_fixture_sha256": CONTENT_PACK_LOCKED_FIXTURE_SHA256,
        "generator_id": CONTENT_PACK_GENERATOR_ID,
        "generator_revision": CONTENT_PACK_GENERATOR_REVISION,
        "generator_algorithm": CONTENT_PACK_GENERATOR_ALGORITHM,
        "generator_seed_sha256": CONTENT_PACK_LOCKED_GENERATOR_SEED_SHA256,
        "selection_digest_algorithm": CONTENT_PACK_SELECTION_DIGEST_ALGORITHM,
        "selection_sha256": CONTENT_PACK_LOCKED_FULL_SELECTION_SHA256,
        "tier_prefix_counts": dict(CONTENT_PACK_TIER_PREFIX_COUNTS),
        "tier_selection_digests": dict(CONTENT_PACK_LOCKED_TIER_SELECTION_DIGESTS),
        "tier_coverage": CONTENT_PACK_LOCKED_TIER_COVERAGE,
        "family_order": list(CONTENT_PACK_FAMILY_ORDER),
        "structural_level_order": list(CONTENT_PACK_STRUCTURAL_LEVEL_ORDER),
        "variant_order": list(CONTENT_PACK_VARIANT_ORDER),
        "source": "infergrade_sha256_generated_fixture",
        "attestation_state": "unreviewed",
        "excluded_from_default_groups": True,
        "excluded_from_suites": True,
        "excluded_from_weighted_score": True,
        "excluded_from_readiness": True,
        "excluded_from_recommendation": True,
        "excluded_from_release_evidence": True,
    }
}
CONTENT_PACK_STATUS_BENCHMARKS = json.loads(json.dumps(CONTENT_PACK_BENCHMARKS))

REASONING_V2_QUALIFICATION_DISPLAY_NAME = "Reasoning constraint stress v2 qualification"
REASONING_V2_QUALIFICATION_DESCRIPTION = (
    "Runner-owned qualification-only execution over the immutable reasoning v2 content pack; "
    "it is excluded from headline score, readiness, recommendation, and release evidence."
)
REASONING_V2_QUALIFICATION_SELECTION_GUIDANCE = (
    "Explicit qualification-only Runner execution is available at exact canary, standard, "
    "or gold prefixes. The result is diagnostic and must not be treated as current capability evidence."
)
REASONING_V2_QUALIFICATION_PROMOTION_BLOCKERS = [
    "Verify backend enforcement of the enabled-thinking budget from runtime receipts; accepted request fields alone are insufficient.",
    "Run current-model repeats with malformed-output, token-exhaustion, and cross-family headroom reporting.",
    "Complete independent review of the content pack, selection identity, parser, and publication boundaries before any evidence role.",
]
REASONING_V2_QUALIFICATION_BENCHMARKS = {
    REASONING_V2_QUALIFICATION_BENCHMARK_ID: {
        "check_id": REASONING_V2_QUALIFICATION_BENCHMARK_ID,
        "qualification_only": True,
        "display_name": REASONING_V2_QUALIFICATION_DISPLAY_NAME,
        "description": REASONING_V2_QUALIFICATION_DESCRIPTION,
        "capability_facets": ["constraint_reasoning_stress_v2"],
        "temporal_scope": "static_pinned",
        "selection_guidance": REASONING_V2_QUALIFICATION_SELECTION_GUIDANCE,
        "claim_boundary": REASONING_V2_QUALIFICATION_CLAIM_BOUNDARY,
        "status": "qualification_only",
        "runnable_status": "runnable_qualification_only",
        "maturity": "thin_local_sample",
        "default_inclusion_status": "excluded_qualification_only",
        "fixture_or_dataset_revision_status": "pinned_runner_content_pack_qualification",
        "harness_status": "native_reasoning_v2_qualification_implemented",
        "expected_duration_token_volume_status": "estimated_qualification_5_to_40_cases",
        "sandbox_requirement": "none_native_generation_only",
        "sample_policy": (
            "Exact prefixes of the immutable 40-case content pack: canary 5, standard 20, and gold 40. "
            "Each prefix preserves locked selection identity and family/level/variant metrics."
        ),
        "promotion_blockers": list(REASONING_V2_QUALIFICATION_PROMOTION_BLOCKERS),
        "evidence_kind": "capability",
        "surface_id": "local_reasoning_capability",
        "evidence_lane_id": "reference",
        "suite_scope": "reference",
        "group_id": None,
        "runner_target": REASONING_V2_QUALIFICATION_BENCHMARK_ID,
        "effort_level": "deep",
        "expected_duration_band": "5-45 min",
        "token_volume_band": "medium",
        "resumability_boundary": "case",
        "execution_pattern": "native_reasoning_v2_qualification",
        "score_dimension": "constraint_reasoning_stress_v2_qualification",
        "primary_score_metric": "exact_signed_integer_accuracy",
        "score_floor": 0.0,
        "primary_score_weight": 0.0,
        "score_role": "qualification_only",
        "discrimination_status": "unreviewed",
        "higher_is_better": True,
        "score_policy_id": SCORING_POLICY,
        "scoring_policy_id": SCORING_POLICY,
        "generation_constraint_id": FINAL_ANSWER_PARSER_ID,
        "generation_policy_id": REASONING_V2_QUALIFICATION_GENERATION_POLICY_ID,
        "failure_denominator_policy_id": REASONING_V2_FAILURE_DENOMINATOR_POLICY_ID,
        "policy_enforcement_state": REASONING_V2_POLICY_ENFORCEMENT_STATE,
        "score_breakdown_fields": [
            "correct_count",
            "total_count",
            "case_accuracy",
            "generation_failure_count",
            "not_attempted_count",
            "generation_failure_count_includes_not_attempted",
            "family_metrics",
            "structural_level_metrics",
            "variant_metrics",
            "parser_code_counts",
        ],
        "content_pack_benchmark_id": REASONING_V2_QUALIFICATION_CONTENT_PACK_ID,
        "qualification_revision": REASONING_V2_QUALIFICATION_REVISION,
        "tier_prefix_counts": {"canary": 5, "standard": 20, "gold": 40},
        "fixture_revision": CONTENT_PACK_FIXTURE_REVISION,
        "fixture_sha256": CONTENT_PACK_LOCKED_FIXTURE_SHA256,
        "full_fixture_sha256": CONTENT_PACK_LOCKED_FIXTURE_SHA256,
        "full_selection_sha256": CONTENT_PACK_LOCKED_FULL_SELECTION_SHA256,
        "generator_seed_sha256": CONTENT_PACK_LOCKED_GENERATOR_SEED_SHA256,
        "selection_digest_algorithm": CONTENT_PACK_SELECTION_DIGEST_ALGORITHM,
        "tier_selection_digests": dict(CONTENT_PACK_LOCKED_TIER_SELECTION_DIGESTS),
        "tier_coverage": CONTENT_PACK_LOCKED_TIER_COVERAGE,
        "family_order": list(CONTENT_PACK_FAMILY_ORDER),
        "structural_level_order": list(CONTENT_PACK_STRUCTURAL_LEVEL_ORDER),
        "variant_order": list(CONTENT_PACK_VARIANT_ORDER),
        "allowed_tiers": ["canary", "standard", "gold"],
        "attestation_state": "unreviewed",
        "excluded_from_default_groups": True,
        "excluded_from_suites": True,
        "excluded_from_weighted_score": True,
        "excluded_from_readiness": True,
        "excluded_from_recommendation": True,
        "excluded_from_release_evidence": True,
    }
}
REASONING_V2_QUALIFICATION_STATUS_BENCHMARKS = json.loads(
    json.dumps(REASONING_V2_QUALIFICATION_BENCHMARKS)
)


def _foundation_field_matches(actual: Any, expected: Any) -> bool:
    """Require recursively exact JSON types and values for identity fields."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        if len(actual) != len(expected):
            return False
        for expected_key, expected_value in expected.items():
            matching_keys = [
                actual_key
                for actual_key in actual
                if type(actual_key) is type(expected_key) and actual_key == expected_key
            ]
            if len(matching_keys) != 1 or not _foundation_field_matches(
                actual[matching_keys[0]], expected_value
            ):
                return False
        return True
    if isinstance(expected, (list, tuple)):
        return len(actual) == len(expected) and all(
            _foundation_field_matches(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected)
        )
    return actual == expected


def repo_root() -> Path:
    """Return the repository root for the Runner workspace."""
    return runner_root()


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
    return {
        str(item.get("check_id")): dict(item)
        for item in list(payload.get("checks") or [])
        if isinstance(item, dict) and item.get("check_id")
    }


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
    return {
        str(item.get("check_id")): dict(item)
        for item in list(payload.get("benchmark_status_matrix") or [])
        if isinstance(item, dict) and item.get("check_id")
    }


def _foundation_canary_placement_error(
    check_id: str,
    catalog: Dict[str, Any],
) -> Optional[str]:
    """Reject foundation identities that become reachable through defaults."""
    def contains(values: Any) -> bool:
        return isinstance(values, list) and check_id in values

    groups = list(catalog.get("benchmark_groups") or [])
    group_ids = set()
    for item in groups:
        if not isinstance(item, dict):
            continue
        group_id = item.get("group_id")
        if contains(item.get("check_ids")) or contains(item.get("default_check_ids")):
            return FOUNDATION_CANARY_METADATA_ERROR
        if group_id:
            group_ids.add(str(group_id))

    suites = list(catalog.get("suites") or [])
    suite_ids = set()
    for item in suites:
        if not isinstance(item, dict):
            continue
        suite_id = item.get("suite_id")
        if contains(item.get("check_ids")) or contains(item.get("default_check_ids")):
            return FOUNDATION_CANARY_METADATA_ERROR
        referenced_groups = item.get("default_group_ids") or item.get("group_ids")
        if isinstance(referenced_groups, list):
            for group in groups:
                if not isinstance(group, dict) or group.get("group_id") not in referenced_groups:
                    continue
                if contains(group.get("check_ids")) or contains(group.get("default_check_ids")):
                    return FOUNDATION_CANARY_METADATA_ERROR
        if suite_id:
            suite_ids.add(str(suite_id))

    for item in list(catalog.get("shortcuts") or []):
        if not isinstance(item, dict):
            continue
        if contains(item.get("check_ids")) or contains(item.get("default_check_ids")):
            return FOUNDATION_CANARY_METADATA_ERROR
        if any(str(suite_id) in suite_ids for suite_id in list(item.get("suite_ids") or [])):
            for suite in suites:
                if not isinstance(suite, dict) or suite.get("suite_id") not in item.get("suite_ids", []):
                    continue
                if contains(suite.get("check_ids")) or contains(suite.get("default_check_ids")):
                    return FOUNDATION_CANARY_METADATA_ERROR

    defaults = catalog.get("legacy_tier_defaults")
    if isinstance(defaults, dict):
        for use_case_defaults in defaults.values():
            if not isinstance(use_case_defaults, dict):
                continue
            for tier_defaults in use_case_defaults.values():
                if not isinstance(tier_defaults, dict):
                    continue
                if contains(tier_defaults.get("check_ids")) or contains(tier_defaults.get("default_check_ids")):
                    return FOUNDATION_CANARY_METADATA_ERROR
                if any(str(group_id) in group_ids for group_id in list(tier_defaults.get("group_ids") or [])):
                    for group in groups:
                        if not isinstance(group, dict) or group.get("group_id") not in tier_defaults.get("group_ids", []):
                            continue
                        if contains(group.get("check_ids")) or contains(group.get("default_check_ids")):
                            return FOUNDATION_CANARY_METADATA_ERROR
                if any(str(suite_id) in suite_ids for suite_id in list(tier_defaults.get("suite_ids") or [])):
                    for suite in suites:
                        if not isinstance(suite, dict) or suite.get("suite_id") not in tier_defaults.get("suite_ids", []):
                            continue
                        if contains(suite.get("check_ids")) or contains(suite.get("default_check_ids")):
                            return FOUNDATION_CANARY_METADATA_ERROR
    return None


def _selection_normalized_scalar(value: Any) -> str:
    """Normalize one selection scalar exactly as request de-duplication does."""
    return str(value or "").strip()


def _normalized_string_occurrence_paths(
    value: Any,
    target: str,
    path: Tuple[Any, ...] = (),
) -> List[Tuple[Any, ...]]:
    """Return target paths using selection-compatible scalar stringification."""
    paths: List[Tuple[Any, ...]] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            key_path = path + (("dict_key", key),)
            if isinstance(key, (dict, list, tuple)):
                paths.extend(_normalized_string_occurrence_paths(key, target, key_path))
            elif _selection_normalized_scalar(key) == target:
                paths.append(key_path)
            paths.extend(_normalized_string_occurrence_paths(nested, target, path + (key,)))
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            paths.extend(_normalized_string_occurrence_paths(nested, target, path + (index,)))
    elif _selection_normalized_scalar(value) == target:
        paths.append(path)
    return paths


def _content_pack_placement_error(
    check_id: str,
    catalog: Dict[str, Any],
) -> Optional[str]:
    """Allow the identity string only in its two exact raw catalog rows."""
    raw_checks = catalog.get("checks")
    raw_statuses = catalog.get("benchmark_status_matrix")
    if not isinstance(raw_checks, list) or not isinstance(raw_statuses, list):
        return CONTENT_PACK_METADATA_ERROR
    check_rows = [
        index
        for index, item in enumerate(raw_checks)
        if isinstance(item, dict) and item.get("check_id") == check_id
    ]
    status_rows = [
        index
        for index, item in enumerate(raw_statuses)
        if isinstance(item, dict) and item.get("check_id") == check_id
    ]
    # Count on raw rows before constructing last-write-wins indexes.
    if len(check_rows) != 1 or len(status_rows) != 1:
        return CONTENT_PACK_METADATA_ERROR
    allowed_paths = {
        ("checks", check_rows[0], "check_id"),
        ("checks", check_rows[0], "runner_target"),
        ("benchmark_status_matrix", status_rows[0], "check_id"),
        ("benchmark_status_matrix", status_rows[0], "runner_target"),
    }
    # The qualification candidate is allowed to name the immutable content
    # pack explicitly.  This does not make the content pack itself runnable or
    # permit any other catalog placement of its identity.
    qualification_check_rows = [
        index
        for index, item in enumerate(raw_checks)
        if isinstance(item, dict)
        and item.get("check_id") == REASONING_V2_QUALIFICATION_BENCHMARK_ID
    ]
    qualification_status_rows = [
        index
        for index, item in enumerate(raw_statuses)
        if isinstance(item, dict)
        and item.get("check_id") == REASONING_V2_QUALIFICATION_BENCHMARK_ID
    ]
    if len(qualification_check_rows) == 1 and len(qualification_status_rows) == 1:
        allowed_paths.update(
            {
                (
                    "checks",
                    qualification_check_rows[0],
                    "content_pack_benchmark_id",
                ),
                (
                    "benchmark_status_matrix",
                    qualification_status_rows[0],
                    "content_pack_benchmark_id",
                ),
            }
        )
    try:
        occurrence_paths = _normalized_string_occurrence_paths(catalog, check_id)
        occurrence_path_set = set(occurrence_paths)
    except Exception:
        return CONTENT_PACK_METADATA_ERROR
    if len(occurrence_paths) != len(allowed_paths) or occurrence_path_set != allowed_paths:
        return CONTENT_PACK_METADATA_ERROR
    return None


def _content_pack_metadata_error(
    check_id: str,
    catalog: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Return a stable error when the code-registered content identity drifts."""
    check_key = str(check_id or "").strip()
    if check_key not in EXPECTED_CONTENT_PACK_BENCHMARK_IDS:
        return None
    if (
        set(CONTENT_PACK_BENCHMARKS) != EXPECTED_CONTENT_PACK_BENCHMARK_IDS
        or set(CONTENT_PACK_STATUS_BENCHMARKS) != EXPECTED_CONTENT_PACK_BENCHMARK_IDS
        or CONTENT_PACK_BENCHMARK_ID not in EXPECTED_CONTENT_PACK_BENCHMARK_IDS
    ):
        return CONTENT_PACK_METADATA_ERROR
    expected_check = CONTENT_PACK_BENCHMARKS.get(check_key)
    expected_status = CONTENT_PACK_STATUS_BENCHMARKS.get(check_key)
    if not isinstance(expected_check, dict) or not isinstance(expected_status, dict):
        return CONTENT_PACK_METADATA_ERROR
    payload = catalog or load_capability_catalog()
    if _content_pack_placement_error(check_key, payload):
        return CONTENT_PACK_METADATA_ERROR
    checks = check_index(payload)
    statuses = benchmark_status_index(payload)
    check = checks.get(check_key)
    status = statuses.get(check_key)
    if not isinstance(check, dict) or not isinstance(status, dict):
        return CONTENT_PACK_METADATA_ERROR
    marked_checks = {
        item_id for item_id, item in checks.items() if item.get("identity_only") is True
    }
    marked_statuses = {
        item_id for item_id, item in statuses.items() if item.get("identity_only") is True
    }
    if (
        marked_checks != EXPECTED_CONTENT_PACK_BENCHMARK_IDS
        or marked_statuses != EXPECTED_CONTENT_PACK_BENCHMARK_IDS
        or not _foundation_field_matches(check, expected_check)
        or not _foundation_field_matches(status, expected_status)
    ):
        return CONTENT_PACK_METADATA_ERROR
    # The generated module itself is part of the identity.  If a future code
    # edit changes bytes without updating the lock, catalog validation fails.
    if (
        CONTENT_PACK_GENERATOR_SEED_SHA256 != CONTENT_PACK_LOCKED_GENERATOR_SEED_SHA256
        or CONTENT_PACK_FULL_FIXTURE_SHA256 != CONTENT_PACK_LOCKED_FIXTURE_SHA256
        or CONTENT_PACK_FULL_SELECTION_SHA256 != CONTENT_PACK_LOCKED_FULL_SELECTION_SHA256
        or CONTENT_PACK_TIER_SELECTION_DIGESTS != CONTENT_PACK_LOCKED_TIER_SELECTION_DIGESTS
        or CONTENT_PACK_TIER_COVERAGE != CONTENT_PACK_LOCKED_TIER_COVERAGE
    ):
        return CONTENT_PACK_METADATA_ERROR
    if CONTENT_PACK_SELECTION_DIGEST_ALGORITHM != SELECTION_DIGEST_ALGORITHM:
        return CONTENT_PACK_METADATA_ERROR
    return None


def _raise_on_malformed_content_pack_metadata(
    catalog: Optional[Dict[str, Any]] = None,
) -> None:
    payload = catalog or load_capability_catalog()
    for check_id in EXPECTED_CONTENT_PACK_BENCHMARK_IDS:
        if _content_pack_metadata_error(check_id, payload):
            raise ValueError(
                "%s:%s:%s"
                % (BENCHMARK_IDENTITY_ONLY_PREFIX, check_id, CONTENT_PACK_METADATA_ERROR)
            )


def _qualification_placement_error(
    check_id: str,
    catalog: Dict[str, Any],
) -> Optional[str]:
    """Keep the runnable candidate identity in its paired check/status rows."""
    raw_checks = catalog.get("checks")
    raw_statuses = catalog.get("benchmark_status_matrix")
    if not isinstance(raw_checks, list) or not isinstance(raw_statuses, list):
        return "metadata_invalid"
    check_rows = [
        index
        for index, item in enumerate(raw_checks)
        if isinstance(item, dict) and item.get("check_id") == check_id
    ]
    status_rows = [
        index
        for index, item in enumerate(raw_statuses)
        if isinstance(item, dict) and item.get("check_id") == check_id
    ]
    if len(check_rows) != 1 or len(status_rows) != 1:
        return "metadata_invalid"
    allowed_paths = {
        ("checks", check_rows[0], "check_id"),
        ("checks", check_rows[0], "runner_target"),
        ("benchmark_status_matrix", status_rows[0], "check_id"),
        ("benchmark_status_matrix", status_rows[0], "runner_target"),
        ("checks", check_rows[0], "qualification_revision"),
        ("benchmark_status_matrix", status_rows[0], "qualification_revision"),
    }
    try:
        occurrence_paths = _normalized_string_occurrence_paths(catalog, check_id)
    except Exception:
        return "metadata_invalid"
    if set(occurrence_paths) != allowed_paths or len(occurrence_paths) != len(allowed_paths):
        return "metadata_invalid"
    return None


def _qualification_metadata_error(
    check_id: str,
    catalog: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Return a stable error when the qualification candidate drifts."""
    check_key = str(check_id or "").strip()
    if check_key not in REASONING_V2_QUALIFICATION_BENCHMARKS:
        return None
    payload = catalog or load_capability_catalog()
    if _qualification_placement_error(check_key, payload):
        return "metadata_invalid"
    # The candidate references the content pack; validate that identity first.
    if _content_pack_metadata_error(REASONING_V2_QUALIFICATION_CONTENT_PACK_ID, payload):
        return "content_pack_metadata_invalid"
    expected_check = REASONING_V2_QUALIFICATION_BENCHMARKS.get(check_key)
    expected_status = REASONING_V2_QUALIFICATION_STATUS_BENCHMARKS.get(check_key)
    check = check_index(payload).get(check_key)
    status = benchmark_status_index(payload).get(check_key)
    if (
        not isinstance(expected_check, dict)
        or not isinstance(expected_status, dict)
        or not isinstance(check, dict)
        or not isinstance(status, dict)
        or not _foundation_field_matches(check, expected_check)
        or not _foundation_field_matches(status, expected_status)
    ):
        return "metadata_invalid"
    try:
        qualification_tier_metadata("gold")
    except Exception:
        return "content_pack_metadata_invalid"
    return None


def _raise_on_malformed_qualification_metadata(
    catalog: Optional[Dict[str, Any]] = None,
) -> None:
    payload = catalog or load_capability_catalog()
    for check_id in REASONING_V2_QUALIFICATION_BENCHMARKS:
        error = _qualification_metadata_error(check_id, payload)
        if error:
            raise ValueError(
                "benchmark_qualification_only:%s:%s" % (check_id, error)
            )


def is_benchmark_qualification_only(
    check_id: str,
    catalog: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return whether the selected check is runnable only in qualification mode."""
    payload = catalog or load_capability_catalog()
    check_key = str(check_id or "").strip()
    if check_key not in REASONING_V2_QUALIFICATION_BENCHMARKS:
        return False
    return _qualification_metadata_error(check_key, payload) is None


def _foundation_canary_metadata_error(
    check_id: str,
    catalog: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Return a stable error when code-registered canary metadata is malformed."""
    expected = FOUNDATION_CANARY_BENCHMARKS.get(str(check_id or "").strip())
    if expected is None:
        return None
    payload = catalog or load_capability_catalog()
    check = check_index(payload).get(str(check_id).strip())
    status = benchmark_status_index(payload).get(str(check_id).strip())
    if not isinstance(check, dict) or not isinstance(status, dict):
        return FOUNDATION_CANARY_METADATA_ERROR
    check_fields = (
        "display_name",
        "description",
        "selection_guidance",
        "claim_boundary",
        "canary_only",
        "allowed_tiers",
        "attestation_state",
        "status",
        "evidence_kind",
        "runner_target",
        "fixture_revision",
        "selection_digest_algorithm",
        "selection_sha256",
        "score_policy_id",
        "generation_constraint_id",
        "generation_policy_id",
        "primary_score_weight",
        "score_role",
        "excluded_from_default_groups",
        "excluded_from_suites",
        "excluded_from_weighted_score",
        "excluded_from_readiness",
        "excluded_from_recommendation",
        "excluded_from_release_evidence",
    )
    for field in check_fields:
        if not _foundation_field_matches(check.get(field), expected[field]):
            return FOUNDATION_CANARY_METADATA_ERROR
    for field in ("fixture_sha256", "expected_answer_vector"):
        if not _foundation_field_matches(check.get(field), expected[field]):
            return FOUNDATION_CANARY_METADATA_ERROR
    status_fields = (
        "status",
        "evidence_kind",
        "runner_target",
        "canary_only",
        "allowed_tiers",
        "attestation_state",
        "runnable_status",
        "maturity",
        "default_inclusion_status",
        "claim_boundary",
        "sample_policy",
        "fixture_revision",
        "selection_digest_algorithm",
        "selection_sha256",
        "scoring_policy_id",
        "score_policy_id",
        "generation_constraint_id",
        "generation_policy_id",
        "excluded_from_default_groups",
        "excluded_from_suites",
        "excluded_from_weighted_score",
        "excluded_from_readiness",
        "excluded_from_recommendation",
        "excluded_from_release_evidence",
    )
    for field in status_fields:
        if not _foundation_field_matches(status.get(field), expected[field]):
            return FOUNDATION_CANARY_METADATA_ERROR
    for field in ("fixture_sha256", "expected_answer_vector"):
        if not _foundation_field_matches(status.get(field), expected[field]):
            return FOUNDATION_CANARY_METADATA_ERROR
    if _foundation_canary_placement_error(str(check_id).strip(), payload):
        return FOUNDATION_CANARY_METADATA_ERROR
    return None


def _raise_on_malformed_foundation_canary_metadata(
    catalog: Optional[Dict[str, Any]] = None,
) -> None:
    payload = catalog or load_capability_catalog()
    for check_id in FOUNDATION_CANARY_BENCHMARKS:
        if _foundation_canary_metadata_error(check_id, payload):
            raise ValueError(
                "%s:%s:%s"
                % (BENCHMARK_CANARY_ONLY_PREFIX, check_id, FOUNDATION_CANARY_METADATA_ERROR)
            )


def benchmark_quarantine_reason(
    check_id: str,
    catalog: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Return the stable quarantine reason for a benchmark, if any."""
    payload = catalog or load_capability_catalog()
    check_key = str(check_id or "").strip()
    declared = dict((payload.get("quarantined_benchmarks") or {}).get(check_key) or {})
    reason = str(declared.get("reason_code") or "").strip()
    if reason:
        return reason
    if check_key in QUARANTINED_BENCHMARK_REASON_CODES:
        status = benchmark_status_index(payload).get(check_key, {})
        if str(status.get("runnable_status") or "") == "quarantined":
            return QUARANTINED_BENCHMARK_REASON_CODES[check_key]
    return None


def is_benchmark_quarantined(
    check_id: str,
    catalog: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return whether a benchmark is excluded from runnable evidence."""
    return benchmark_quarantine_reason(check_id, catalog) is not None


def benchmark_canary_only_reason(
    check_id: str,
    catalog: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Return the stable exclusion reason for an unreviewed canary-only check."""
    payload = catalog or load_capability_catalog()
    check_key = str(check_id or "").strip()
    metadata_error = _foundation_canary_metadata_error(check_key, payload)
    if metadata_error:
        return metadata_error
    check = check_index(payload).get(check_key, {})
    if check.get("canary_only") is not True:
        return None
    if check.get("allowed_tiers") != ["canary"] or check.get("attestation_state") != "unreviewed":
        return FOUNDATION_CANARY_METADATA_ERROR
    return str(check.get("attestation_state") or "unreviewed").strip() or "unreviewed"


def benchmark_evidence_exclusion_reason(
    check_id: str,
    catalog: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Return why a check cannot enter score/readiness/recommendation evidence."""
    payload = catalog or load_capability_catalog()
    check_key = str(check_id or "").strip()
    if check_key in EXPECTED_CONTENT_PACK_BENCHMARK_IDS:
        content_pack_error = _content_pack_metadata_error(check_key, payload)
        if content_pack_error:
            return "%s:%s" % (BENCHMARK_IDENTITY_ONLY_PREFIX, content_pack_error)
        return "%s:planned" % BENCHMARK_IDENTITY_ONLY_PREFIX
    if check_key in REASONING_V2_QUALIFICATION_BENCHMARKS:
        qualification_error = _qualification_metadata_error(check_key, payload)
        if qualification_error:
            return "benchmark_qualification_only:%s" % qualification_error
        return "benchmark_qualification_only:unreviewed"
    quarantined = benchmark_quarantine_reason(check_id, payload)
    if quarantined:
        return quarantined
    canary_only = benchmark_canary_only_reason(check_id, payload)
    if canary_only:
        return "%s:%s" % (BENCHMARK_CANARY_ONLY_PREFIX, canary_only)
    return None


def is_benchmark_excluded_from_evidence(
    check_id: str,
    catalog: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return whether a check is excluded from score and public evidence paths."""
    return benchmark_evidence_exclusion_reason(check_id, catalog) is not None


def reject_quarantined_benchmarks(
    check_ids: List[str],
    catalog: Optional[Dict[str, Any]] = None,
) -> None:
    """Fail closed when a request explicitly resolves to quarantined checks."""
    payload = catalog or load_capability_catalog()
    blocked = []
    for check_id in _dedupe_strings(check_ids):
        reason = benchmark_quarantine_reason(check_id, payload)
        if reason:
            blocked.append((str(check_id), reason))
    if blocked:
        benchmark_id, reason = blocked[0]
        raise ValueError(
            "%s:%s:%s" % (BENCHMARK_SELECTION_QUARANTINE_PREFIX, benchmark_id, reason)
        )


def reject_tier_restricted_benchmarks(
    check_ids: List[str],
    requested_tier: str,
    *,
    tier_was_explicit: bool = False,
    group_ids: Optional[List[str]] = None,
    suite_ids: Optional[List[str]] = None,
    catalog: Optional[Dict[str, Any]] = None,
) -> None:
    """Reject canary-only checks after explicit and inferred tier derivation."""
    payload = catalog or load_capability_catalog()
    _raise_on_malformed_foundation_canary_metadata(payload)
    _raise_on_malformed_content_pack_metadata(payload)
    _raise_on_malformed_qualification_metadata(payload)
    checks = check_index(payload)
    derived_tier = derive_tier_from_selection(
        check_ids,
        group_ids=group_ids,
        suite_ids=suite_ids,
        catalog=payload,
    )
    tiers = {derived_tier}
    if tier_was_explicit:
        tiers.add(str(requested_tier or ""))
    for check_id in _dedupe_strings(check_ids):
        metadata_error = _foundation_canary_metadata_error(check_id, payload)
        if metadata_error:
            raise ValueError(
                "%s:%s:%s"
                % (BENCHMARK_CANARY_ONLY_PREFIX, check_id, metadata_error)
            )
        check = checks.get(check_id, {})
        if check.get("canary_only") is not True:
            continue
        allowed_tiers = check.get("allowed_tiers")
        if not isinstance(allowed_tiers, list) or not allowed_tiers:
            raise ValueError(
                "%s:%s:allowed_tiers_missing" % (BENCHMARK_CANARY_ONLY_PREFIX, check_id)
            )
        disallowed = sorted(tier for tier in tiers if tier not in set(map(str, allowed_tiers)))
        if disallowed:
            raise ValueError(
                "%s:%s:tier_not_allowed:%s"
                % (BENCHMARK_CANARY_ONLY_PREFIX, check_id, disallowed[0])
            )


def capability_surface_index(catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Return capability surfaces keyed by surface id."""
    payload = catalog or load_capability_catalog()
    return {str(item["surface_id"]): dict(item) for item in list(payload.get("capability_surfaces") or [])}


def surface_score_policy_index(catalog: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Return task-scoped surface score policies keyed by surface id."""
    payload = catalog or load_capability_catalog()
    return {str(item["surface_id"]): dict(item) for item in list(payload.get("surface_score_policies") or [])}


def coverage_expansion_priorities(catalog: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Return ordered coverage priorities that directly improve the answer loop."""
    payload = catalog or load_capability_catalog()
    priorities = []
    for item in list(payload.get("coverage_expansion_priorities") or []):
        priority = dict(item)
        check_ids = _dedupe_strings(priority.get("benchmark_check_ids"))
        excluded = [
            check_id
            for check_id in check_ids
            if benchmark_evidence_exclusion_reason(check_id, payload)
        ]
        priority["benchmark_check_ids"] = [
            check_id for check_id in check_ids if check_id not in excluded
        ]
        if excluded:
            priority["excluded_benchmark_check_ids"] = excluded
        quarantined = [
            check_id for check_id in excluded if benchmark_quarantine_reason(check_id, payload)
        ]
        if quarantined:
            priority["excluded_quarantined_benchmark_check_ids"] = quarantined
        priorities.append(priority)
    return sorted(priorities, key=lambda item: int(item.get("rank") or 0))


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
    surface_score_policies = surface_score_policy_index(payload)
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
    quarantine_payload = payload.get("quarantined_benchmarks")
    if not isinstance(quarantine_payload, dict):
        failures.append("quarantined_benchmarks must be an object")
        quarantine_payload = {}
    declared_checks = {
        str(item.get("check_id")): item
        for item in list(payload.get("checks") or [])
        if isinstance(item, dict) and item.get("check_id")
    }
    for check_id in FOUNDATION_CANARY_BENCHMARKS:
        if _foundation_canary_metadata_error(check_id, payload):
            failures.append(
                f"{check_id}: code-registered foundation canary metadata must match its paired check/status contract"
            )
    for check_id in EXPECTED_CONTENT_PACK_BENCHMARK_IDS:
        if _content_pack_metadata_error(check_id, payload):
            failures.append(
                f"{check_id}: code-registered content identity metadata must match its paired check/status contract"
            )
    for check_id, declaration in quarantine_payload.items():
        if check_id not in declared_checks:
            failures.append(f"{check_id}: quarantined benchmark must be a declared check")
            continue
        if not isinstance(declaration, dict):
            failures.append(f"{check_id}: quarantine declaration must be an object")
            continue
        if not str(declaration.get("reason_code") or "").strip():
            failures.append(f"{check_id}: quarantine reason_code must be non-empty")
        expected_flags = {
            "runnable": False,
            "excluded_from_readiness": True,
            "excluded_from_recommendation": True,
            "excluded_from_release_evidence": True,
        }
        for field, expected in expected_flags.items():
            if declaration.get(field) is not expected:
                failures.append(
                    f"{check_id}: quarantine {field} must be {str(expected).lower()}"
                )
        status = status_by_check.get(check_id, {})
        if status.get("runnable_status") != "quarantined":
            failures.append(f"{check_id}: quarantine status must be quarantined")
        if status.get("default_inclusion_status") != "excluded_quarantined":
            failures.append(
                f"{check_id}: quarantined benchmark must be excluded by default"
            )
        if declared_checks[check_id].get("status") != "quarantined":
            failures.append(f"{check_id}: declared check status must be quarantined")
    for check_id, status in status_by_check.items():
        if status.get("runnable_status") == "quarantined" and check_id not in quarantine_payload:
            failures.append(f"{check_id}: quarantined status requires a quarantine declaration")
    for check_id in sorted(declared_check_ids & planned_check_ids):
        failures.append(f"{check_id}: benchmark cannot be both a declared check and planned candidate")
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
        if (declared_check or not planned_candidate) and status_policy not in score_policy_ids:
            failures.append(f"{check_id}: scoring_policy_id is not declared")
        if not isinstance(status.get("promotion_blockers"), list) or not status.get("promotion_blockers"):
            failures.append(f"{check_id}: promotion_blockers must be a non-empty list")
        maturity = str(status.get("maturity") or "")
        runnable_status = str(status.get("runnable_status") or "")
        if planned_candidate:
            if runnable_status != "not_runnable":
                failures.append(
                    f"{check_id}: planned candidate must remain not_runnable until moved into checks"
                )
            if maturity.endswith("_runnable"):
                failures.append(
                    f"{check_id}: planned candidate cannot declare runnable maturity"
                )
        if declared_check and runnable_status.startswith("runnable_"):
            if "not_implemented" in str(status.get("harness_status") or ""):
                failures.append(
                    f"{check_id}: runnable check requires an implemented harness"
                )
            if str(status.get("expected_duration_token_volume_status") or "") == "unknown":
                failures.append(
                    f"{check_id}: runnable check requires bounded duration and token-volume status"
                )
        if declared_check and maturity.endswith("_runnable"):
            if not runnable_status.startswith("runnable_"):
                failures.append(
                    f"{check_id}: runnable maturity requires runnable_status"
                )
            revision_status = str(status.get("fixture_or_dataset_revision_status") or "")
            if "pinned" not in revision_status:
                failures.append(
                    f"{check_id}: runnable reference or gold maturity requires a pinned fixture or dataset"
                )
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
        if check.get("canary_only") is True:
            if check.get("allowed_tiers") != ["canary"]:
                failures.append(f"{check_id}: canary-only check must allow exactly canary")
            if check.get("attestation_state") != "unreviewed":
                failures.append(f"{check_id}: canary-only check must declare unreviewed attestation")
            if check.get("group_id") not in (None, ""):
                failures.append(f"{check_id}: canary-only check must not declare a benchmark group")
            weight = check.get("primary_score_weight")
            if (
                isinstance(weight, bool)
                or not isinstance(weight, (int, float))
                or float(weight) != 0.0
            ):
                failures.append(f"{check_id}: canary-only check must have zero score weight")
            if check.get("score_role") != "diagnostic_only":
                failures.append(f"{check_id}: canary-only check must be diagnostic_only")
            for field in (
                "excluded_from_default_groups",
                "excluded_from_suites",
                "excluded_from_weighted_score",
                "excluded_from_readiness",
                "excluded_from_recommendation",
                "excluded_from_release_evidence",
            ):
                if check.get(field) is not True:
                    failures.append(f"{check_id}: canary-only {field} must be true")
            if status.get("canary_only") is not True:
                failures.append(f"{check_id}: status matrix must preserve canary_only")
            if status.get("allowed_tiers") != ["canary"]:
                failures.append(f"{check_id}: status matrix must allow exactly canary")
            if status.get("attestation_state") != "unreviewed":
                failures.append(f"{check_id}: status matrix must declare unreviewed attestation")
            for field in (
                "excluded_from_default_groups",
                "excluded_from_suites",
                "excluded_from_weighted_score",
                "excluded_from_readiness",
                "excluded_from_recommendation",
                "excluded_from_release_evidence",
            ):
                if status.get(field) is not True:
                    failures.append(f"{check_id}: status matrix {field} must be true")
            if any(
                check_id in list(item.get("default_check_ids") or [])
                for item in list(payload.get("benchmark_groups") or [])
            ):
                failures.append(f"{check_id}: canary-only check must not be in a benchmark group")
            if any(
                check_id in list(item.get("check_ids") or [])
                or check_id in list(item.get("default_check_ids") or [])
                for item in list(payload.get("shortcuts") or [])
            ):
                failures.append(f"{check_id}: canary-only check must not be in a shortcut")
            if any(
                check_id in list(item.get("default_check_ids") or [])
                for item in list(payload.get("suites") or [])
            ):
                failures.append(f"{check_id}: canary-only check must not be in a suite")
            for use_case_defaults in (payload.get("legacy_tier_defaults") or {}).values():
                if any(
                    check_id in list(tier_defaults.get("check_ids") or [])
                    for tier_defaults in (use_case_defaults or {}).values()
                    if isinstance(tier_defaults, dict)
                ):
                    failures.append(f"{check_id}: canary-only check must not be in legacy defaults")
    for item in coverage_expansion_priorities(payload):
        priority_id = str(item.get("priority_id") or "").strip()
        if not priority_id:
            failures.append("coverage_expansion_priorities: priority_id must be non-empty")
        for field in ("hardware_class", "model_family", "use_case", "why", "what_it_would_change", "status"):
            if not str(item.get(field) or "").strip():
                failures.append(f"{priority_id or '<missing>'}: coverage priority field {field} must be non-empty")
        if not isinstance(item.get("target_quants"), list) or not item.get("target_quants"):
            failures.append(f"{priority_id or '<missing>'}: target_quants must be a non-empty list")
        if item.get("headroom_challenge_eligible") is True:
            if item.get("calibration_campaign_eligible") is not True:
                failures.append(
                    f"{priority_id or '<missing>'}: headroom challenge must be calibration campaign eligible"
                )
            if item.get("model_freshness") not in {"current_generation", "recent_generation"}:
                failures.append(
                    f"{priority_id or '<missing>'}: headroom challenge must be current or recent generation"
                )
            if not str(item.get("model_id") or item.get("checkpoint_name") or "").strip():
                failures.append(
                    f"{priority_id or '<missing>'}: headroom challenge requires exact model identity"
                )
            target_observations = item.get("target_observations")
            if (
                isinstance(target_observations, bool)
                or not isinstance(target_observations, int)
                or target_observations < 2
            ):
                failures.append(
                    f"{priority_id or '<missing>'}: headroom challenge requires at least two target observations"
                )
            if not str(item.get("headroom_challenge_rationale") or "").strip():
                failures.append(
                    f"{priority_id or '<missing>'}: headroom challenge rationale must be non-empty"
                )
        generation_preset_id = str(item.get("generation_preset_id") or "").strip()
        if generation_preset_id and generation_preset_id not in SUPPORTED_COVERAGE_GENERATION_PRESETS:
            failures.append(
                f"{priority_id or '<missing>'}: unsupported coverage generation_preset_id "
                f"{generation_preset_id!r}"
            )
        check_ids = item.get("benchmark_check_ids")
        if not isinstance(check_ids, list) or not check_ids:
            failures.append(f"{priority_id or '<missing>'}: benchmark_check_ids must be a non-empty list")
            continue
        for check_id in check_ids:
            if str(check_id) not in declared_check_ids:
                failures.append(f"{priority_id or '<missing>'}: unknown coverage benchmark_check_id {check_id!r}")
    from infergrade.capability_scoring import primary_surface_for_use_case

    checks_by_id = check_index(payload)
    challenge_priorities = [
        item for item in coverage_expansion_priorities(payload)
        if item.get("headroom_challenge_eligible") is True
    ]
    for surface_id, policy in surface_score_policies.items():
        if surface_id not in surfaces:
            failures.append(f"{surface_id}: surface score policy references an unknown surface")
        for field in ("display_name", "score_version", "score_method", "claim_boundary"):
            if not str(policy.get(field) or "").strip():
                failures.append(f"{surface_id}: surface score policy field {field} must be non-empty")
        protocol_version = str(policy.get("protocol_version") or "").strip()
        protocol_label = str(policy.get("protocol_label") or "").strip()
        if bool(protocol_version) != bool(protocol_label):
            failures.append(f"{surface_id}: protocol_version and protocol_label must be declared together")
        if protocol_version and not re.match(r"^[0-9]+\.[0-9]+$", protocol_version):
            failures.append(f"{surface_id}: protocol_version must use major.minor notation")
        minimum_coverage = policy.get("minimum_coverage_fraction")
        if not isinstance(minimum_coverage, (int, float)) or not 0 <= float(minimum_coverage) <= 1:
            failures.append(f"{surface_id}: minimum_coverage_fraction must be between 0 and 1")
        for field in ("minimum_scored_components", "minimum_score_dimensions"):
            value = policy.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 2:
                failures.append(f"{surface_id}: {field} must be an integer of at least 2")
        for field in ("dominant_component_weight_fraction", "maximum_component_weight_fraction"):
            fraction = policy.get(field)
            if not isinstance(fraction, (int, float)) or isinstance(fraction, bool) or not 0 < float(fraction) <= 1:
                failures.append(f"{surface_id}: {field} must be above 0 and at most 1")
        if policy.get("calibration_status") != "not_psychometrically_calibrated":
            failures.append(f"{surface_id}: calibration_status must preserve the non-calibrated claim boundary")
        calibration_policy = dict(policy.get("calibration_policy") or {})
        confidence_level = calibration_policy.get(
            "ceiling_fraction_confidence_level"
        )
        if (
            isinstance(confidence_level, bool)
            or not isinstance(confidence_level, (int, float))
            or not 0.0 < float(confidence_level) < 1.0
        ):
            failures.append(
                f"{surface_id}: calibration_policy ceiling_fraction_confidence_level "
                "must be greater than 0 and less than 1"
            )
        headline_check_ids = {
            check_id
            for check_id, check in checks_by_id.items()
            if check.get("surface_id") == surface_id
            and check.get("evidence_kind") == "capability"
            and isinstance(check.get("primary_score_weight"), (int, float))
            and float(check.get("primary_score_weight")) > 0
        }
        surface_challenge_priorities = [
            item for item in challenge_priorities
            if primary_surface_for_use_case(item.get("use_case")) == surface_id
            and headline_check_ids.issubset({
                str(check_id)
                for check_id in list(item.get("benchmark_check_ids") or [])
            })
        ]
        if (
            calibration_policy.get("minimum_headroom_challenge_observations")
            and not surface_challenge_priorities
        ):
            failures.append(
                f"{surface_id}: headroom challenge gate requires an explicit eligible campaign "
                "target covering every positively weighted capability check"
            )
        weights = [
            float(check.get("primary_score_weight"))
            for check in checks_by_id.values()
            if check.get("surface_id") == surface_id
            and check.get("evidence_kind") == "capability"
            and isinstance(check.get("primary_score_weight"), (int, float))
            and float(check.get("primary_score_weight")) > 0
        ]
        if not weights:
            failures.append(f"{surface_id}: surface score policy has no positively weighted capability checks")
        elif abs(sum(weights) - 1.0) > 0.000001:
            failures.append(f"{surface_id}: positive primary score weights must sum to 1.0")
    # Local import avoids a module cycle while keeping the established catalog
    # legitimacy gate authoritative for representativeness metadata too.
    from infergrade.benchmark_adequacy import validate_benchmark_adequacy_metadata

    failures.extend(validate_benchmark_adequacy_metadata(payload))
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
    _raise_on_malformed_foundation_canary_metadata(payload)
    _raise_on_malformed_content_pack_metadata(payload)
    _raise_on_malformed_qualification_metadata(payload)
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

    selection = {
        "suite_ids": suite_ids,
        "group_ids": group_ids,
        "check_ids": check_ids,
    }
    if REASONING_V2_QUALIFICATION_BENCHMARK_ID in selection["check_ids"]:
        if (
            len(selection["check_ids"]) != 1
            or selection["suite_ids"]
            or selection["group_ids"]
        ):
            raise ValueError(
                "benchmark_qualification_only:%s:selection_must_be_exclusive"
                % REASONING_V2_QUALIFICATION_BENCHMARK_ID
            )
    reject_quarantined_benchmarks(selection["check_ids"], payload)
    reject_tier_restricted_benchmarks(
        selection["check_ids"],
        request.tier,
        tier_was_explicit=request.tier_was_explicit,
        group_ids=selection["group_ids"],
        suite_ids=selection["suite_ids"],
        catalog=payload,
    )
    return selection


def normalize_request_selection(request: RunRequest, catalog: Optional[Dict[str, Any]] = None) -> RunRequest:
    """Apply selection defaults and compatibility-derived fields directly onto a request."""
    payload = catalog or load_capability_catalog()
    suites = suite_index(payload)
    selection = resolve_request_selection(request, payload)

    suite_ids = list(selection["suite_ids"])
    group_ids = list(selection["group_ids"])
    check_ids = list(selection["check_ids"])

    request.capability_suite_ids = suite_ids
    request.benchmark_group_ids = group_ids
    request.benchmark_check_ids = check_ids
    if DIRECT_ANSWER_PROTOCOL_CHECK_IDS.intersection(check_ids):
        request.generation_preset = DIRECT_ANSWER_GENERATION_PRESET
    if REASONING_V2_QUALIFICATION_BENCHMARK_ID in check_ids:
        requested_policy = request.generation_preset
        if requested_policy not in (
            None,
            DEFAULT_GENERATION_PRESET,
            REASONING_V2_QUALIFICATION_GENERATION_POLICY_ID,
        ):
            raise ValueError(
                "benchmark_qualification_only:%s:generation_policy_mismatch:%s"
                % (REASONING_V2_QUALIFICATION_BENCHMARK_ID, requested_policy)
            )
        # run_infergrade resolves the ordinary deterministic default before it
        # calls this function.  The qualification candidate is the one narrow
        # exception: its benchmark contract owns the exact reasoning policy.
        request.generation_preset = REASONING_V2_QUALIFICATION_GENERATION_POLICY_ID

    if check_ids and not request.tier_was_explicit:
        request.tier = derive_tier_from_selection(check_ids, group_ids=group_ids, suite_ids=suite_ids, catalog=payload)

    reject_tier_restricted_benchmarks(
        check_ids,
        request.tier,
        tier_was_explicit=request.tier_was_explicit,
        group_ids=group_ids,
        suite_ids=suite_ids,
        catalog=payload,
    )

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
    _raise_on_malformed_content_pack_metadata(payload)
    checks = check_index(payload)
    selection = resolve_request_selection(request, payload)
    return [
        item
        for item in _dedupe_strings(selection.get("check_ids"))
        if checks.get(item, {}).get("evidence_kind") == "capability"
        and (
            not is_benchmark_excluded_from_evidence(item, payload)
            or is_benchmark_qualification_only(item, payload)
        )
    ]


def deployment_profile_ids_for_request(
    request: RunRequest,
    catalog: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Return selected deployment profile ids."""
    payload = catalog or load_capability_catalog()
    _raise_on_malformed_content_pack_metadata(payload)
    checks = check_index(payload)
    selection = resolve_request_selection(request, payload)
    return [
        str(checks[item]["runner_target"])
        for item in _dedupe_strings(selection.get("check_ids"))
        if checks.get(item, {}).get("evidence_kind") == "deployment"
        and not is_benchmark_excluded_from_evidence(item, payload)
    ]


def fidelity_enabled_for_request(
    request: RunRequest,
    catalog: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return whether the request explicitly includes fidelity evidence."""
    payload = catalog or load_capability_catalog()
    _raise_on_malformed_content_pack_metadata(payload)
    checks = check_index(payload)
    selection = resolve_request_selection(request, payload)
    return any(
        checks.get(item, {}).get("evidence_kind") == "fidelity"
        and not is_benchmark_excluded_from_evidence(item, payload)
        for item in _dedupe_strings(selection.get("check_ids"))
    )


def benchmark_scope_summary_for_selection(
    check_ids: List[str],
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Summarize whether a selected benchmark set is decision-sized or reference-sized."""
    payload = catalog or load_capability_catalog()
    _raise_on_malformed_foundation_canary_metadata(payload)
    _raise_on_malformed_content_pack_metadata(payload)
    _raise_on_malformed_qualification_metadata(payload)
    checks = check_index(payload)
    selected_ids = [item for item in _dedupe_strings(check_ids) if item in checks]
    selected = [checks[item] for item in selected_ids]
    excluded_ids = [
        item for item in selected_ids if is_benchmark_excluded_from_evidence(item, payload)
    ]
    eligible_ids = [item for item in selected_ids if item not in excluded_ids]
    selected = [checks[item] for item in eligible_ids]
    exclusion_reasons = {
        item: benchmark_evidence_exclusion_reason(item, payload)
        for item in excluded_ids
    }
    if not selected_ids:
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
    if not selected:
        content_identity_ids = [
            item for item in excluded_ids
            if item in EXPECTED_CONTENT_PACK_BENCHMARK_IDS
        ]
        qualification_ids = [
            item
            for item in excluded_ids
            if item in REASONING_V2_QUALIFICATION_BENCHMARKS
        ]
        if qualification_ids:
            return {
                "scope": "qualification_only",
                "scope_label": "Qualification-only Runner execution",
                "qualification_only": True,
                "eligible_benchmark_check_ids": [],
                "identity_only_benchmark_check_ids": [],
                "qualification_only_benchmark_check_ids": qualification_ids,
                "excluded_benchmark_check_ids": excluded_ids,
                "evidence_exclusion_reasons": exclusion_reasons,
                "selection_guidance": REASONING_V2_QUALIFICATION_SELECTION_GUIDANCE,
                "claim_boundary": REASONING_V2_QUALIFICATION_CLAIM_BOUNDARY,
                "effort_level": "deep",
                "expected_duration_band": "5-45 min",
                "token_volume_band": "medium",
                "metadata_sources": _metadata_sources(payload, []),
                "metadata_confidence": _metadata_confidence(_metadata_sources(payload, [])),
                "execution_patterns": ["native_reasoning_v2_qualification"],
                "resumability_boundaries": ["case"],
            }
        return {
            "scope": "identity_only",
            "scope_label": (
                "Future benchmark content identity only"
                if content_identity_ids
                else "Foundation identity only"
            ),
            "identity_only": True,
            "eligible_benchmark_check_ids": [],
            "identity_only_benchmark_check_ids": [
                item for item in excluded_ids
                if item in EXPECTED_CONTENT_PACK_BENCHMARK_IDS
                or item in FOUNDATION_CANARY_BENCHMARKS
            ],
            "qualification_only_benchmark_check_ids": [],
            "excluded_benchmark_check_ids": excluded_ids,
            "evidence_exclusion_reasons": exclusion_reasons,
            "selection_guidance": (
                CONTENT_PACK_SELECTION_GUIDANCE
                if content_identity_ids
                else FOUNDATION_CANARY_SELECTION_GUIDANCE
            ),
            "effort_level": "short",
            "expected_duration_band": "not estimated",
            "token_volume_band": "not estimated",
            "metadata_sources": _metadata_sources(payload, []),
            "metadata_confidence": _metadata_confidence(_metadata_sources(payload, [])),
            "execution_patterns": [],
            "resumability_boundaries": [],
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
        "eligible_benchmark_check_ids": eligible_ids,
        "identity_only_benchmark_check_ids": excluded_ids,
        "qualification_only_benchmark_check_ids": [
            item for item in excluded_ids if item in REASONING_V2_QUALIFICATION_BENCHMARKS
        ],
        "excluded_benchmark_check_ids": excluded_ids,
        "evidence_exclusion_reasons": exclusion_reasons,
    }


def capability_coverage_guidance_for_selection(
    check_ids: List[str],
    catalog: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return user-facing coverage guidance without treating unknown as failure."""
    payload = catalog or load_capability_catalog()
    _raise_on_malformed_foundation_canary_metadata(payload)
    _raise_on_malformed_content_pack_metadata(payload)
    _raise_on_malformed_qualification_metadata(payload)
    checks = check_index(payload)
    selected_ids = [item for item in _dedupe_strings(check_ids) if item in checks]
    excluded_ids = [
        item for item in selected_ids if is_benchmark_excluded_from_evidence(item, payload)
    ]
    eligible_ids = [item for item in selected_ids if item not in excluded_ids]
    selected_checks = [checks[item] for item in eligible_ids]
    selected_kinds = set(_dedupe_strings([item.get("evidence_kind") for item in selected_checks]))
    selected_decision = [item["check_id"] for item in selected_checks if item.get("suite_scope") == "decision"]
    selected_reference = [item["check_id"] for item in selected_checks if item.get("suite_scope") == "reference"]
    selected_lane_ids = _dedupe_strings([_evidence_lane_id_for_item(payload, item) for item in selected_checks])
    available_reference = [
        check_id
        for check_id, check in checks.items()
        if check.get("suite_scope") == "reference"
        and check_id not in selected_ids
        and check.get("status", "available") != "planned"
        and not is_benchmark_excluded_from_evidence(check_id, payload)
    ]
    planned = [
        _planned_benchmark_candidate_payload(payload, item)
        for item in list(payload.get("planned_benchmark_candidates") or [])
        if str(item.get("check_id") or "").strip()
        not in EXPECTED_CONTENT_PACK_BENCHMARK_IDS
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
        and not is_benchmark_excluded_from_evidence(check_id, payload)
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
        "selected_benchmark_check_ids": selected_ids,
        "eligible_benchmark_check_ids": eligible_ids,
        "identity_only_benchmark_check_ids": [
            item for item in excluded_ids
            if item in EXPECTED_CONTENT_PACK_BENCHMARK_IDS
            or item in FOUNDATION_CANARY_BENCHMARKS
        ],
        "qualification_only_benchmark_check_ids": [
            item for item in excluded_ids if item in REASONING_V2_QUALIFICATION_BENCHMARKS
        ],
        "excluded_benchmark_check_ids": excluded_ids,
        "evidence_exclusion_reasons": {
            item: benchmark_evidence_exclusion_reason(item, payload)
            for item in excluded_ids
        },
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
    excluded_ids = [
        item
        for item in normalized["check_ids"]
        if is_benchmark_excluded_from_evidence(item, payload)
    ]
    eligible_ids = [
        item for item in normalized["check_ids"] if item not in excluded_ids
    ]
    identity_only_ids = [
        item for item in excluded_ids
        if item in EXPECTED_CONTENT_PACK_BENCHMARK_IDS
        or item in FOUNDATION_CANARY_BENCHMARKS
    ]
    qualification_only_ids = [
        item for item in excluded_ids if item in REASONING_V2_QUALIFICATION_BENCHMARKS
    ]
    return {
        "catalog_version": payload.get("catalog_version"),
        "shortcut_id": request.benchmark_shortcut_id,
        "benchmark_scope": benchmark_scope,
        "capability_coverage_guidance": coverage_guidance,
        "capability_suite_ids": list(normalized["suite_ids"]),
        "benchmark_group_ids": list(normalized["group_ids"]),
        "benchmark_check_ids": list(normalized["check_ids"]),
        "eligible_benchmark_check_ids": eligible_ids,
        "identity_only_benchmark_check_ids": identity_only_ids,
        "qualification_only_benchmark_check_ids": qualification_only_ids,
        "excluded_benchmark_check_ids": excluded_ids,
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
        [
            checks[item].get("score_policy_id")
            for item in _dedupe_strings(check_ids)
            if item in checks and not is_benchmark_excluded_from_evidence(item, catalog)
        ]
    )
    return [policies[policy_id] for policy_id in selected_policy_ids if policy_id in policies]


def _benchmark_check_metadata(catalog: Dict[str, Any], check_id: str, check: Dict[str, Any]) -> Dict[str, Any]:
    excluded = is_benchmark_excluded_from_evidence(check_id, catalog)
    identity = (
        FOUNDATION_CANARY_BENCHMARKS.get(check_id)
        or CONTENT_PACK_BENCHMARKS.get(check_id)
        or REASONING_V2_QUALIFICATION_BENCHMARKS.get(check_id)
    ) if excluded else None
    lane_id = None if excluded else _evidence_lane_id_for_item(catalog, check)
    lane = {} if excluded else _evidence_lane_payload(catalog, lane_id)
    legitimacy_status = benchmark_status_index(catalog).get(check_id, {})
    return {
        "check_id": check_id,
        "display_name": identity.get("display_name") if identity else check.get("display_name"),
        "description": identity.get("description") if identity else check.get("description"),
        "evidence_kind": check.get("evidence_kind"),
        "surface_id": check.get("surface_id"),
        "evidence_lane_id": lane_id,
        "evidence_lane_label": lane.get("display_name"),
        "claim_strength": lane.get("claim_strength"),
        "claim_boundary": identity.get("claim_boundary") if identity else lane.get("claim_boundary"),
        "group_id": check.get("group_id"),
        "suite_scope": None if excluded else check.get("suite_scope"),
        "effort_level": check.get("effort_level"),
        "expected_duration_band": check.get("expected_duration_band"),
        "token_volume_band": check.get("token_volume_band"),
        "resumability_boundary": check.get("resumability_boundary"),
        "execution_pattern": check.get("execution_pattern"),
        "selection_guidance": identity.get("selection_guidance") if identity else check.get("selection_guidance"),
        "status": check.get("status", "available"),
        "score_dimension": check.get("score_dimension"),
        "primary_score_metric": check.get("primary_score_metric"),
        "score_floor": check.get("score_floor"),
        "primary_score_weight": check.get("primary_score_weight"),
        "score_role": check.get("score_role"),
        "discrimination_status": check.get("discrimination_status"),
        "saturation_evidence": dict(check.get("saturation_evidence") or {}),
        "higher_is_better": check.get("higher_is_better"),
        "score_policy_id": check.get("score_policy_id"),
        "empirical_saturation_slice_policy": (
            dict(check["empirical_saturation_slice_policy"])
            if isinstance(check.get("empirical_saturation_slice_policy"), dict)
            else {}
        ),
        "generation_constraint_id": legitimacy_status.get("generation_constraint_id"),
        "score_breakdown_fields": list(check.get("score_breakdown_fields") or []),
        "benchmark_maturity": legitimacy_status.get("maturity"),
        "runnable_status": legitimacy_status.get("runnable_status"),
        "default_inclusion_status": legitimacy_status.get("default_inclusion_status"),
        "fixture_or_dataset_revision_status": legitimacy_status.get("fixture_or_dataset_revision_status"),
        "harness_status": legitimacy_status.get("harness_status"),
        "sample_policy": legitimacy_status.get("sample_policy"),
        "benchmark_claim_boundary": (
            identity.get("claim_boundary")
            if identity
            else legitimacy_status.get("claim_boundary")
        ),
        "quarantine_reason_code": benchmark_quarantine_reason(check_id, catalog),
        "evidence_exclusion_reason": benchmark_evidence_exclusion_reason(check_id, catalog),
        "runnable_evidence": not excluded,
        "identity_only": bool(excluded and check_id not in REASONING_V2_QUALIFICATION_BENCHMARKS),
        "qualification_only": bool(check_id in REASONING_V2_QUALIFICATION_BENCHMARKS),
        "canary_only": bool(check.get("canary_only")),
        "allowed_tiers": list(check.get("allowed_tiers") or []),
        "attestation_state": check.get("attestation_state"),
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
        normalized = _selection_normalized_scalar(value)
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
