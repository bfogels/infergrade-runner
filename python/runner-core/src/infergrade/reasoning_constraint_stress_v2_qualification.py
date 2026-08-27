"""Runner-owned qualification adapter for the reasoning v2 content identity.

This module is intentionally a separate candidate lane.  It consumes exact
prefixes of the immutable 40-case content pack, but it does not alter the
content pack's identity or make a headline evidence claim.  Runtime policy
enforcement is recorded as ``requested_unverified`` until a backend receipt can
prove that the thinking budget was enforced; llama.cpp currently exposes no
independent receipt for that proof.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Mapping

from infergrade.generation_policies import (
    REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID,
    resolve_generation_policy,
)
from infergrade.reasoning_constraint_stress_v2 import (
    FINAL_ANSWER_PARSER_ID,
    SCORING_POLICY,
    extract_diagnostic_terminal_integer_candidate,
    parse_final_answer,
)
from infergrade.reasoning_constraint_stress_v2_content import (
    BENCHMARK_ID as CONTENT_PACK_BENCHMARK_ID,
    FAMILY_ORDER,
    FIXTURE_REVISION as CONTENT_PACK_FIXTURE_REVISION,
    FULL_FIXTURE_SHA256,
    FULL_SELECTION_SHA256,
    GENERATOR_ALGORITHM,
    GENERATOR_ID,
    GENERATOR_REVISION,
    GENERATOR_SEED_SHA256,
    LOCKED_FIXTURE_SHA256,
    LOCKED_FULL_SELECTION_SHA256,
    LOCKED_GENERATOR_SEED_SHA256,
    LOCKED_TIER_COVERAGE,
    LOCKED_TIER_SELECTION_DIGESTS,
    STRUCTURAL_LEVEL_ORDER,
    TIER_COVERAGE,
    TIER_PREFIX_COUNTS,
    TIER_SELECTION_DIGESTS,
    VARIANT_ORDER,
    independent_oracle_answers,
    reasoning_constraint_stress_v2_content_cases,
)
from infergrade.selection_identity import (
    SORTED_JSON_STRING_ARRAY_SHA256_V1,
    selection_digest,
)


BENCHMARK_ID = "reasoning_constraint_stress_v2_qualification_v1"
QUALIFICATION_BENCHMARK_ID = BENCHMARK_ID
QUALIFICATION_REVISION = "reasoning_constraint_stress_v2_qualification_v1"
GENERATION_POLICY_ID = REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID
SELECTION_DIGEST_ALGORITHM_ID = SORTED_JSON_STRING_ARRAY_SHA256_V1
FAILURE_DENOMINATOR_POLICY_ID = "qualification_failure_denominator_v1"
POLICY_ENFORCEMENT_REQUESTED_UNVERIFIED = "requested_unverified"
POLICY_ENFORCEMENT_VERIFIED = "verified"
CLAIM_BOUNDARY = (
    "Qualification-only Runner execution over the immutable reasoning v2 content pack. "
    "This is not headline capability evidence, a readiness signal, a recommendation, "
    "a release gate, or proof that backend thinking-budget enforcement is verified."
)


def _stable_identity(case: Mapping[str, Any]) -> str:
    identity = case.get("task_id") or case.get("case_id")
    if identity is None or not str(identity).strip():
        raise ValueError("reasoning_v2_selection_identity_mismatch:missing_case_identity")
    return str(identity)


def _coverage_for(cases: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, int]]:
    rows = list(cases)
    return {
        "family_counts": dict(Counter(str(case.get("category") or "") for case in rows)),
        "structural_level_counts": dict(
            Counter(str(case.get("structural_level") or "") for case in rows)
        ),
        "variant_counts": dict(Counter(str(case.get("variant") or "") for case in rows)),
    }


def _case_answers(cases: Iterable[Mapping[str, Any]]) -> Dict[str, str]:
    answers: Dict[str, str] = {}
    for case in cases:
        identity = _stable_identity(case)
        expected = list(case.get("expected_answers") or [])
        if len(expected) != 1 or not isinstance(expected[0], str):
            raise ValueError(
                "reasoning_v2_selection_identity_mismatch:expected_answer:%s" % identity
            )
        answers[identity] = expected[0]
    return answers


@lru_cache(maxsize=1)
def validate_locked_content_pack() -> Dict[str, Any]:
    """Validate generated content, independent oracles, and all locked prefixes."""

    if GENERATOR_SEED_SHA256 != LOCKED_GENERATOR_SEED_SHA256:
        raise ValueError("reasoning_v2_content_identity_mismatch:generator_seed")
    if FULL_FIXTURE_SHA256 != LOCKED_FIXTURE_SHA256:
        raise ValueError("reasoning_v2_content_identity_mismatch:fixture")
    if FULL_SELECTION_SHA256 != LOCKED_FULL_SELECTION_SHA256:
        raise ValueError("reasoning_v2_content_identity_mismatch:full_selection")
    if TIER_SELECTION_DIGESTS != LOCKED_TIER_SELECTION_DIGESTS:
        raise ValueError("reasoning_v2_content_identity_mismatch:tier_selection")
    if TIER_COVERAGE != LOCKED_TIER_COVERAGE:
        raise ValueError("reasoning_v2_content_identity_mismatch:tier_coverage")

    cases = reasoning_constraint_stress_v2_content_cases()
    if len(cases) != TIER_PREFIX_COUNTS["gold"]:
        raise ValueError("reasoning_v2_content_identity_mismatch:case_count")
    identities = [_stable_identity(case) for case in cases]
    if len(set(identities)) != len(identities):
        raise ValueError("reasoning_v2_content_identity_mismatch:duplicate_identity")
    expected = _case_answers(cases)
    independent = independent_oracle_answers()
    if expected != independent:
        raise ValueError("reasoning_v2_content_identity_mismatch:independent_oracle")
    return {
        "content_pack_benchmark_id": CONTENT_PACK_BENCHMARK_ID,
        "content_pack_fixture_revision": CONTENT_PACK_FIXTURE_REVISION,
        "content_pack_full_fixture_sha256": LOCKED_FIXTURE_SHA256,
        "content_pack_full_selection_sha256": LOCKED_FULL_SELECTION_SHA256,
        "generator_id": GENERATOR_ID,
        "generator_revision": GENERATOR_REVISION,
        "generator_algorithm": GENERATOR_ALGORITHM,
        "generator_seed_sha256": LOCKED_GENERATOR_SEED_SHA256,
        "selection_digest_algorithm": SELECTION_DIGEST_ALGORITHM_ID,
        "tier_selection_digests": dict(LOCKED_TIER_SELECTION_DIGESTS),
        "tier_coverage": deepcopy(LOCKED_TIER_COVERAGE),
        "family_order": list(FAMILY_ORDER),
        "structural_level_order": list(STRUCTURAL_LEVEL_ORDER),
        "variant_order": list(VARIANT_ORDER),
    }


def qualification_cases_for_tier(tier: str) -> List[Dict[str, Any]]:
    """Return the exact immutable content prefix for ``tier``."""

    validate_locked_content_pack()
    tier_key = str(tier or "")
    if tier_key not in TIER_PREFIX_COUNTS:
        raise ValueError("reasoning_v2_selection_identity_mismatch:unknown_tier:%s" % tier_key)
    cases = reasoning_constraint_stress_v2_content_cases()[: TIER_PREFIX_COUNTS[tier_key]]
    validate_tier_cases(cases, tier_key)
    return deepcopy(cases)


def validate_tier_cases(cases: List[Dict[str, Any]], tier: str) -> Dict[str, Any]:
    """Require loaded cases to equal the locked prefix byte-for-byte in shape/value."""

    validate_locked_content_pack()
    tier_key = str(tier or "")
    if tier_key not in TIER_PREFIX_COUNTS:
        raise ValueError("reasoning_v2_selection_identity_mismatch:unknown_tier:%s" % tier_key)
    expected_cases = reasoning_constraint_stress_v2_content_cases()[: TIER_PREFIX_COUNTS[tier_key]]
    if len(cases) != len(expected_cases):
        raise ValueError(
            "reasoning_v2_selection_identity_mismatch:%s:case_count" % tier_key
        )
    if cases != expected_cases:
        raise ValueError(
            "reasoning_v2_selection_identity_mismatch:%s:case_payload" % tier_key
        )
    digest = selection_digest(
        (_stable_identity(case) for case in cases), SELECTION_DIGEST_ALGORITHM_ID
    )
    expected_digest = LOCKED_TIER_SELECTION_DIGESTS[tier_key]
    if digest != expected_digest:
        raise ValueError(
            "reasoning_v2_selection_identity_mismatch:%s:digest" % tier_key
        )
    coverage = _coverage_for(cases)
    expected_coverage = LOCKED_TIER_COVERAGE[tier_key]
    if (
        coverage["family_counts"] != expected_coverage["family_counts"]
        or coverage["structural_level_counts"] != expected_coverage["structural_level_counts"]
        or coverage["variant_counts"] != expected_coverage["variant_counts"]
    ):
        raise ValueError(
            "reasoning_v2_selection_identity_mismatch:%s:coverage" % tier_key
        )
    return {
        "tier": tier_key,
        "case_count": len(cases),
        "selection_digest_algorithm": SELECTION_DIGEST_ALGORITHM_ID,
        "selection_sha256": digest,
        "coverage": deepcopy(expected_coverage),
    }


def qualification_tier_metadata(tier: str) -> Dict[str, Any]:
    """Return receipt-ready identity metadata after validating the prefix."""

    cases = qualification_cases_for_tier(tier)
    metadata = validate_tier_cases(cases, tier)
    metadata.update(
        {
            "benchmark_id": BENCHMARK_ID,
            "qualification_revision": QUALIFICATION_REVISION,
            "content_pack_benchmark_id": CONTENT_PACK_BENCHMARK_ID,
            "content_pack_fixture_revision": CONTENT_PACK_FIXTURE_REVISION,
            "content_pack_full_fixture_sha256": LOCKED_FIXTURE_SHA256,
            "content_pack_full_selection_sha256": LOCKED_FULL_SELECTION_SHA256,
            "scoring_policy_id": SCORING_POLICY,
            "generation_policy_id": GENERATION_POLICY_ID,
            "generation_constraint_id": FINAL_ANSWER_PARSER_ID,
            "failure_denominator_policy_id": FAILURE_DENOMINATOR_POLICY_ID,
            "claim_boundary": CLAIM_BOUNDARY,
        }
    )
    return metadata


def _prediction_identity(prediction: Mapping[str, Any]) -> List[str]:
    identities = []
    for field in ("case_id", "task_id"):
        if field in prediction:
            value = prediction.get(field)
            if value is None or not str(value).strip():
                raise ValueError(
                    "reasoning_v2_prediction_identity_mismatch:empty_%s" % field
                )
            identities.append(str(value))
    if not identities:
        raise ValueError("reasoning_v2_prediction_identity_mismatch:missing_identity")
    return identities


def _prediction_rows_for_cases(
    cases: List[Dict[str, Any]], predictions: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    aliases: Dict[str, str] = {}
    canonical: Dict[str, Dict[str, Any]] = {}
    for case in cases:
        task_id = _stable_identity(case)
        case_id = str(case.get("case_id") or task_id)
        if task_id in canonical:
            raise ValueError("reasoning_v2_prediction_identity_mismatch:duplicate_case:%s" % task_id)
        canonical[task_id] = {"task_id": task_id, "case_id": case_id}
        for alias in {task_id, case_id}:
            if alias in aliases and aliases[alias] != task_id:
                raise ValueError("reasoning_v2_prediction_identity_mismatch:ambiguous_alias:%s" % alias)
            aliases[alias] = task_id
    matched: Dict[str, Dict[str, Any]] = {}
    for prediction in predictions:
        if not isinstance(prediction, dict):
            raise ValueError("reasoning_v2_prediction_identity_mismatch:prediction_not_object")
        identities = _prediction_identity(prediction)
        resolved = {aliases.get(identity) for identity in identities}
        if None in resolved:
            raise ValueError("reasoning_v2_prediction_identity_mismatch:foreign_identity")
        resolved.discard(None)
        if len(resolved) != 1:
            raise ValueError("reasoning_v2_prediction_identity_mismatch:alias_conflict")
        task_id = next(iter(resolved))
        if task_id in matched:
            raise ValueError("reasoning_v2_prediction_identity_mismatch:duplicate_prediction:%s" % task_id)
        row = dict(prediction)
        row.update(canonical[task_id])
        matched[task_id] = row
    rows = []
    for case in cases:
        task_id = _stable_identity(case)
        row = matched.get(task_id)
        if row is None:
            row = {
                "case_id": str(case.get("case_id") or task_id),
                "task_id": task_id,
                "generation_status": "failed",
                "generation_failure_kind": "generation_not_attempted",
                "generation_error": "No prediction was recorded before the benchmark stopped.",
                "prediction_missing": True,
                "generation_policy_id": GENERATION_POLICY_ID,
                "generation_policy_enforcement": POLICY_ENFORCEMENT_REQUESTED_UNVERIFIED,
            }
        rows.append(row)
    return rows


def _metric_group(case_results: List[Dict[str, Any]], field: str) -> Dict[str, Any]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for result in case_results:
        value = str(result.get(field) or "unknown")
        groups.setdefault(value, []).append(result)
    output = {}
    for key, rows in sorted(groups.items()):
        scored = [row for row in rows if row.get("score") is not None]
        correct = len([row for row in scored if row.get("score") == 1.0])
        output[key] = {
            "correct_count": correct,
            "total_count": len(scored),
            "generation_failure_count": len(
                [row for row in rows if row.get("state") == "failed"]
            ),
            "accuracy": round(correct / float(len(scored)), 6) if scored else None,
        }
    return output


def _diagnostic_failure_class(
    score: Any,
    diagnostic_semantic_correct: Any,
) -> str:
    """Partition strict non-passes without changing the strict score."""

    if score == 1.0:
        return "none"
    if diagnostic_semantic_correct is True:
        return "format_only"
    if diagnostic_semantic_correct is False:
        return "substantive_wrong"
    return "unavailable"


def score_qualification_predictions(
    cases: List[Dict[str, Any]],
    predictions: List[Dict[str, Any]],
    tier: str,
    *,
    generation_policy_id: str = GENERATION_POLICY_ID,
) -> Dict[str, Any]:
    """Score strict terminal answers with generation failures out of denominator."""

    selection = validate_tier_cases(cases, tier)
    policy = resolve_generation_policy(generation_policy_id)
    if policy.policy_id != GENERATION_POLICY_ID:
        raise ValueError("reasoning_v2_generation_policy_mismatch:%s" % policy.policy_id)
    rows = _prediction_rows_for_cases(cases, predictions)
    expected = _case_answers(cases)
    case_results: List[Dict[str, Any]] = []
    parser_codes: Counter = Counter()
    generation_failure_count = 0
    policy_enforcement_states: Counter = Counter()

    for prediction, case in zip(rows, cases):
        task_id = _stable_identity(case)
        generation_policy = str(prediction.get("generation_policy_id") or "").strip()
        if generation_policy != GENERATION_POLICY_ID:
            raise ValueError(
                "reasoning_v2_generation_policy_mismatch:%s" % (generation_policy or "missing")
            )
        observed_fingerprint = str(
            prediction.get("generation_policy_fingerprint") or ""
        ).strip()
        if observed_fingerprint and observed_fingerprint != policy.fingerprint_sha256:
            raise ValueError("reasoning_v2_generation_policy_fingerprint_mismatch")
        receipt = prediction.get("generation_policy_receipt")
        if receipt is not None:
            if not isinstance(receipt, dict):
                raise ValueError("reasoning_v2_generation_policy_receipt_invalid")
            if receipt.get("policy_id") != GENERATION_POLICY_ID:
                raise ValueError("reasoning_v2_generation_policy_receipt_mismatch")
            receipt_fingerprint = str(receipt.get("fingerprint_sha256") or "").strip()
            if receipt_fingerprint != policy.fingerprint_sha256:
                raise ValueError("reasoning_v2_generation_policy_receipt_mismatch")
        enforcement = str(
            prediction.get("generation_policy_enforcement")
            or POLICY_ENFORCEMENT_REQUESTED_UNVERIFIED
        )
        if enforcement not in {
            POLICY_ENFORCEMENT_REQUESTED_UNVERIFIED,
            POLICY_ENFORCEMENT_VERIFIED,
        }:
            raise ValueError("reasoning_v2_policy_enforcement_unknown:%s" % enforcement)
        if enforcement == POLICY_ENFORCEMENT_VERIFIED:
            receipt = prediction.get("generation_policy_receipt")
            if (
                not isinstance(receipt, dict)
                or receipt.get("enforced") is not True
                or receipt.get("enforcement_state") != POLICY_ENFORCEMENT_VERIFIED
            ):
                raise ValueError("reasoning_v2_policy_enforcement_receipt_missing")
        elif receipt is not None and (
            receipt.get("enforced") is not None
            or receipt.get("enforcement_state") != POLICY_ENFORCEMENT_REQUESTED_UNVERIFIED
        ):
            raise ValueError("reasoning_v2_policy_enforcement_receipt_mismatch")
        policy_enforcement_states[enforcement] += 1
        generation_status = str(prediction.get("generation_status") or "failed")
        diagnostics = {
            "case_id": str(case.get("case_id") or task_id),
            "task_id": task_id,
            "family": case.get("category"),
            "category": case.get("category"),
            "structural_level": case.get("structural_level"),
            "variant": case.get("variant"),
            "generation_policy_id": generation_policy,
            "generation_policy_enforcement": enforcement,
        }
        if generation_status != "completed":
            generation_failure_count += 1
            error_class = (
                "token_budget_exhausted"
                if prediction.get("token_budget_exhausted") is True
                else str(prediction.get("generation_failure_kind") or "generation_failed")
            )
            case_results.append(
                {
                    **diagnostics,
                    "state": "failed",
                    "score": None,
                    "format_valid": None,
                    "parser_code": "not_attempted",
                    "error_class": error_class,
                    "diagnostic_semantic_candidate": None,
                    "diagnostic_semantic_candidate_available": False,
                    "diagnostic_semantic_correct": None,
                    "diagnostic_semantic_candidate_code": "unavailable_generation_failure",
                    "diagnostic_failure_class": "unavailable",
                }
            )
            parser_codes["not_attempted"] += 1
            continue

        response = str(
            prediction.get("completion")
            or prediction.get("response")
            or prediction.get("text")
            or ""
        )
        parsed = parse_final_answer(response)
        diagnostic_candidate = extract_diagnostic_terminal_integer_candidate(response)
        diagnostic_semantic_correct = (
            diagnostic_candidate.available
            and diagnostic_candidate.value == int(expected[task_id], 10)
        )
        parser_codes[parsed.code] += 1
        token_exhausted = prediction.get("token_budget_exhausted") is True
        semantic_correct = parsed.ok and str(parsed.value) == expected[task_id]
        error_class = None
        if token_exhausted:
            error_class = "token_budget_exhausted"
            semantic_correct = False
        elif not parsed.ok:
            error_class = parsed.code
        case_results.append(
            {
                **diagnostics,
                "state": "scored",
                "score": 1.0 if semantic_correct else 0.0,
                "format_valid": parsed.ok and not token_exhausted,
                "semantic_correct": bool(semantic_correct),
                "parser_code": parsed.code,
                "error_class": error_class,
                "parsed_value": parsed.value if parsed.ok else None,
                "diagnostic_semantic_candidate": (
                    diagnostic_candidate.value
                    if diagnostic_candidate.available
                    else None
                ),
                "diagnostic_semantic_candidate_available": diagnostic_candidate.available,
                "diagnostic_semantic_correct": (
                    bool(diagnostic_semantic_correct)
                    if diagnostic_candidate.available
                    else None
                ),
                "diagnostic_semantic_candidate_code": diagnostic_candidate.code,
                "diagnostic_failure_class": _diagnostic_failure_class(
                    1.0 if semantic_correct else 0.0,
                    (
                        bool(diagnostic_semantic_correct)
                        if diagnostic_candidate.available
                        else None
                    ),
                ),
            }
        )

    scored = [result for result in case_results if result.get("score") is not None]
    correct_count = len([result for result in scored if result.get("score") == 1.0])
    malformed_output_count = len(
        [result for result in scored if result.get("parser_code") not in {"ok"}]
    )
    format_invalid_count = len(
        [result for result in scored if result.get("format_valid") is False]
    )
    format_valid_count = len(
        [result for result in scored if result.get("format_valid") is True]
    )
    semantic_incorrect_format_valid_count = len(
        [
            result
            for result in scored
            if result.get("format_valid") is True and result.get("score") == 0.0
        ]
    )
    token_budget_exhaustion_count = len(
        [result for result in scored if result.get("error_class") == "token_budget_exhausted"]
    )
    diagnostic_candidate_count = len(
        [
            result
            for result in case_results
            if result.get("diagnostic_semantic_candidate_available") is True
        ]
    )
    diagnostic_semantic_correct_count = len(
        [result for result in case_results if result.get("diagnostic_semantic_correct") is True]
    )
    diagnostic_semantic_incorrect_count = len(
        [result for result in case_results if result.get("diagnostic_semantic_correct") is False]
    )
    diagnostic_semantic_unavailable_count = len(
        [result for result in case_results if result.get("diagnostic_semantic_correct") is None]
    )
    diagnostic_failure_classes = Counter(
        str(result.get("diagnostic_failure_class") or "unavailable")
        for result in case_results
        if result.get("score") != 1.0
    )
    status = "completed"
    if generation_failure_count == len(case_results):
        status = "failed"
    elif generation_failure_count:
        status = "partial"
    metrics = {
        "exact_signed_integer_accuracy": (
            round(correct_count / float(len(scored)), 6) if scored else None
        ),
        "case_accuracy": (
            round(correct_count / float(len(scored)), 6) if scored else None
        ),
        "correct_count": correct_count,
        "semantic_correct_count": correct_count,
        "total_count": len(scored),
        "format_valid_count": format_valid_count,
        "semantic_incorrect_format_valid_count": semantic_incorrect_format_valid_count,
        "expected_case_count": len(case_results),
        "completed_case_count": len(scored),
        # Generation failures, including synthesized not-attempted rows, are
        # reported for run completeness but excluded from the score
        # denominator.  Completed malformed/model outputs remain scored zero.
        "generation_failure_count": generation_failure_count,
        "not_attempted_count": parser_codes.get("not_attempted", 0),
        "generation_failure_count_includes_not_attempted": True,
        "generation_failure_rate": round(
            generation_failure_count / float(len(case_results)), 6
        )
        if case_results
        else 0.0,
        "unscored_generation_failure_count": generation_failure_count,
        "unscored_generation_failure_rate": round(
            generation_failure_count / float(len(case_results)), 6
        )
        if case_results
        else 0.0,
        "malformed_output_count": malformed_output_count,
        "format_invalid_count": format_invalid_count,
        "model_output_diagnostic_count": malformed_output_count,
        "token_budget_exhaustion_count": token_budget_exhaustion_count,
        # These are score-inert diagnostics.  Failure-class counts partition
        # strict non-passes; generation failures are therefore unavailable and
        # remain excluded from the strict denominator.
        "diagnostic_semantic_candidate_count": diagnostic_candidate_count,
        "diagnostic_semantic_correct_count": diagnostic_semantic_correct_count,
        "diagnostic_semantic_incorrect_count": diagnostic_semantic_incorrect_count,
        "diagnostic_semantic_unavailable_count": diagnostic_semantic_unavailable_count,
        "diagnostic_failure_class_counts": {
            "format_only": diagnostic_failure_classes.get("format_only", 0),
            "substantive_wrong": diagnostic_failure_classes.get("substantive_wrong", 0),
            "unavailable": diagnostic_failure_classes.get("unavailable", 0),
        },
        "diagnostic_format_only_failure_count": diagnostic_failure_classes.get(
            "format_only", 0
        ),
        "diagnostic_substantive_wrong_count": diagnostic_failure_classes.get(
            "substantive_wrong", 0
        ),
        "diagnostic_unavailable_count": diagnostic_failure_classes.get("unavailable", 0),
        "parser_code_counts": dict(sorted(parser_codes.items())),
        "parser_total_count": sum(parser_codes.values()) - parser_codes.get("not_attempted", 0),
        "family_metrics": _metric_group(case_results, "family"),
        "structural_level_metrics": _metric_group(case_results, "structural_level"),
        "variant_metrics": _metric_group(case_results, "variant"),
        "policy_enforcement_states": dict(sorted(policy_enforcement_states.items())),
        "failure_denominator_policy": {
            "policy_id": FAILURE_DENOMINATOR_POLICY_ID,
            "model_output_failures": "scored_zero",
            "generation_failures": "excluded_unscored",
            "missing_predictions": "generation_failure_and_not_attempted",
            "token_budget_exhaustion": "completed_scored_zero",
        },
    }
    return {
        "benchmark_id": BENCHMARK_ID,
        "display_name": "Reasoning constraint stress v2 qualification",
        "status": status,
        "primary_metric": {
            "name": "exact_signed_integer_accuracy",
            "value": metrics["exact_signed_integer_accuracy"],
        },
        "metrics": metrics,
        "case_results": case_results,
        "scoring_policy": SCORING_POLICY,
        "generation_policy_id": GENERATION_POLICY_ID,
        "generation_policy_fingerprint": policy.fingerprint_sha256,
        "generation_constraint_id": FINAL_ANSWER_PARSER_ID,
        "selection": selection,
        "claim_boundary": CLAIM_BOUNDARY,
    }


__all__ = [
    "BENCHMARK_ID",
    "CLAIM_BOUNDARY",
    "CONTENT_PACK_BENCHMARK_ID",
    "FAILURE_DENOMINATOR_POLICY_ID",
    "GENERATION_POLICY_ID",
    "POLICY_ENFORCEMENT_REQUESTED_UNVERIFIED",
    "POLICY_ENFORCEMENT_VERIFIED",
    "QUALIFICATION_BENCHMARK_ID",
    "QUALIFICATION_REVISION",
    "SELECTION_DIGEST_ALGORITHM_ID",
    "qualification_cases_for_tier",
    "qualification_tier_metadata",
    "score_qualification_predictions",
    "validate_locked_content_pack",
    "validate_tier_cases",
]
