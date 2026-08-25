"""Privacy-safe quick scoring over an already-running local model server.

The observed lane deliberately does not create a normal ``RunRequest`` bundle:
an endpoint URL or server-reported raw model path is local addressing data, not
publishable model identity.  This module keeps both in memory and returns only
bounded diagnostics plus the redacted ``observed_runtime_v1`` receipt.
"""

from collections import Counter
from typing import Any, Dict

from infergrade.adapters.openai_compatible import OpenAICompatibleAdapter
from infergrade.models import RunRequest
from infergrade.observed_runtime import (
    FAILURE_CODES,
    QUICK_GENERATION_PROFILE_VERSION,
    validate_observed_runtime_receipt,
)
from infergrade.reasoning_constraint_stress_v2 import (
    extract_diagnostic_terminal_integer_candidate,
    parse_final_answer,
)
from infergrade.reasoning_constraint_stress_v2_qualification import (
    qualification_cases_for_tier,
    validate_locked_content_pack,
    validate_tier_cases,
)


OBSERVED_QUICK_SUITE_VERSION = "observed_quick_suite_v1"
OBSERVED_QUICK_GENERATION_POLICY_ID = "observed_quick_generation_v1"
PROTOCOL_CANARY_ID = "strict_terminal_integer_canary_v1"
PROTOCOL_CANARY_PROMPT = (
    "Follow this output protocol test. Return exactly one line and no other text: "
    "FINAL_ANSWER: 7"
)
OBSERVED_QUICK_PROMPT_DIRECTIVE = (
    "Solve the problem internally but do not show reasoning or any other text. "
    "Your entire response must be exactly one line in the form "
    "FINAL_ANSWER: <signed integer>. Do not use Markdown fences."
)
CLAIM_BOUNDARY = (
    "Local observed diagnostic only. The endpoint, runtime build, model artifact, "
    "publisher, and quantization are not independently verified. Scores are not "
    "comparable, promotion-eligible, recommendation evidence, or headline capability evidence."
)
STABLE_GENERATION_FAILURE_CODES = frozenset(FAILURE_CODES)


def _stable_generation_failure_code(value: Any) -> str:
    code = str(value or "").strip()
    return code if code in STABLE_GENERATION_FAILURE_CODES else "generation_failed"


def _empty_metrics(expected_case_count: int) -> Dict[str, Any]:
    return {
        "exact_signed_integer_accuracy": None,
        "correct_count": 0,
        "completed_case_count": 0,
        "expected_case_count": expected_case_count,
        "format_invalid_count": 0,
        "generation_failure_count": 0,
        "not_attempted_count": expected_case_count,
        "parser_code_counts": {},
        "generation_failure_code_counts": {},
        "diagnostic_semantic_candidate_count": 0,
        "diagnostic_semantic_correct_count": 0,
        "diagnostic_semantic_incorrect_count": 0,
        "diagnostic_semantic_unavailable_count": expected_case_count,
        "diagnostic_failure_class_counts": {
            "format_only": 0,
            "substantive_wrong": 0,
            "unavailable": expected_case_count,
        },
        "failure_denominator_policy": {
            "model_output_failures": "scored_zero",
            "generation_failures": "excluded_unscored",
            "not_attempted": "excluded_unscored",
        },
    }


def _case_identity(case: Dict[str, Any]) -> str:
    return str(case.get("task_id") or case.get("case_id"))


def _not_attempted_row(case: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "case_id": str(case.get("case_id") or _case_identity(case)),
        "task_id": _case_identity(case),
        "family": case.get("category"),
        "structural_level": case.get("structural_level"),
        "variant": case.get("variant"),
        "state": "not_attempted",
        "score": None,
        "format_valid": None,
        "parser_code": "not_attempted",
        "error_class": "protocol_canary_failed",
        "diagnostic_semantic_candidate": None,
        "diagnostic_semantic_candidate_available": False,
        "diagnostic_semantic_correct": None,
        "diagnostic_semantic_candidate_code": "unavailable_not_attempted",
        "diagnostic_failure_class": "unavailable",
    }


def _request() -> RunRequest:
    # The placeholder never selects or asserts model identity. The adapter uses
    # its in-memory explicit ID or the endpoint's sole reported ID.
    return RunRequest(
        model="observed-endpoint-model",
        backend="openai-compatible-observed",
        tier="canary",
        execution_mode="local_native",
        simulate=False,
    )


def run_observed_quick_suite(
    adapter: OpenAICompatibleAdapter,
    *,
    tier: str = "canary",
    max_tokens: int = 512,
) -> Dict[str, Any]:
    """Run an exact 5/20/40 prefix without retaining prompts or completions."""

    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 4096:
        raise ValueError("observed_quick_suite_invalid_max_tokens")
    cases = qualification_cases_for_tier(tier)
    selection = validate_tier_cases(cases, tier)
    content_identity = validate_locked_content_pack()
    request = _request()

    try:
        canary_generation = adapter.generate_text(request, PROTOCOL_CANARY_PROMPT, min(max_tokens, 32))
    except Exception:
        # A first-call exception has no trustworthy receipt to normalize into
        # a result. Fail with one stable code and never echo adapter text.
        raise ValueError("observed_quick_suite_generation_failed")
    runtime_receipt = dict(canary_generation.get("observed_runtime") or {})
    validate_observed_runtime_receipt(runtime_receipt)
    canary_parse = parse_final_answer(str(canary_generation.get("text") or ""))
    canary_completed = canary_generation.get("status") == "completed"
    canary_passed = bool(canary_completed and canary_parse.ok and canary_parse.value == 7)
    canary = {
        "canary_id": PROTOCOL_CANARY_ID,
        "status": "passed" if canary_passed else "failed",
        "generation_status": "completed" if canary_completed else "failed",
        "format_valid": bool(canary_completed and canary_parse.ok),
        "answer_correct": canary_passed,
        "parser_code": canary_parse.code if canary_completed else "not_attempted",
        "error_class": None if canary_passed else (
            canary_parse.code
            if canary_completed
            else _stable_generation_failure_code(canary_generation.get("error"))
        ),
    }

    if not canary_passed:
        case_results = [_not_attempted_row(case) for case in cases]
        metrics = _empty_metrics(len(cases))
        return _result_envelope(
            status="failed",
            tier=tier,
            selection=selection,
            content_identity=content_identity,
            canary=canary,
            runtime_receipt=runtime_receipt,
            metrics=metrics,
            case_results=case_results,
        )

    case_results = []
    parser_codes: Counter = Counter()
    generation_failure_codes: Counter = Counter()
    correct_count = 0
    format_invalid_count = 0
    generation_failure_count = 0
    aborted = False

    for case in cases:
        if aborted:
            case_results.append({
                **_not_attempted_row(case),
                "error_class": "generation_aborted_after_failure",
            })
            continue
        generation_prompt = "%s\n\n%s" % (
            str(case["prompt"]),
            OBSERVED_QUICK_PROMPT_DIRECTIVE,
        )
        try:
            generation = adapter.generate_text(request, generation_prompt, max_tokens)
        except Exception:
            # The protocol canary already supplied a validated receipt. Reuse
            # it for a bounded failure row without exposing exception text.
            generation = {
                "status": "failed",
                "error": "generation_failed",
                "observed_runtime": runtime_receipt,
            }
        runtime_receipt = dict(generation.get("observed_runtime") or runtime_receipt)
        validate_observed_runtime_receipt(runtime_receipt)
        diagnostics = {
            "case_id": str(case.get("case_id") or _case_identity(case)),
            "task_id": _case_identity(case),
            "family": case.get("category"),
            "structural_level": case.get("structural_level"),
            "variant": case.get("variant"),
        }
        if generation.get("status") != "completed":
            code = _stable_generation_failure_code(generation.get("error"))
            generation_failure_codes[code] += 1
            generation_failure_count += 1
            aborted = True
            case_results.append({
                **diagnostics,
                "state": "failed",
                "score": None,
                "format_valid": None,
                "parser_code": "not_attempted",
                "error_class": code,
                "diagnostic_semantic_candidate": None,
                "diagnostic_semantic_candidate_available": False,
                "diagnostic_semantic_correct": None,
                "diagnostic_semantic_candidate_code": "unavailable_generation_failure",
                "diagnostic_failure_class": "unavailable",
            })
            continue

        response = str(generation.get("text") or "")
        parsed = parse_final_answer(response)
        diagnostic_candidate = extract_diagnostic_terminal_integer_candidate(response)
        parser_codes[parsed.code] += 1
        expected = str((case.get("expected_answers") or [""])[0])
        correct = bool(parsed.ok and str(parsed.value) == expected)
        diagnostic_correct = (
            diagnostic_candidate.available
            and diagnostic_candidate.value == int(expected, 10)
        )
        diagnostic_failure_class = (
            "format_only"
            if not correct and diagnostic_candidate.available and diagnostic_correct
            else "substantive_wrong"
            if not correct and diagnostic_candidate.available
            else "unavailable"
            if not correct
            else None
        )
        correct_count += int(correct)
        format_invalid_count += int(not parsed.ok)
        case_results.append({
            **diagnostics,
            "state": "scored",
            "score": 1.0 if correct else 0.0,
            "format_valid": parsed.ok,
            "parser_code": parsed.code,
            "error_class": None if correct else (parsed.code if not parsed.ok else "incorrect_answer"),
            "diagnostic_semantic_candidate": (
                diagnostic_candidate.value if diagnostic_candidate.available else None
            ),
            "diagnostic_semantic_candidate_available": diagnostic_candidate.available,
            "diagnostic_semantic_correct": (
                bool(diagnostic_correct) if diagnostic_candidate.available else None
            ),
            "diagnostic_semantic_candidate_code": diagnostic_candidate.code,
            "diagnostic_failure_class": diagnostic_failure_class,
        })

    completed_case_count = len([row for row in case_results if row["state"] == "scored"])
    not_attempted_count = len([row for row in case_results if row["state"] == "not_attempted"])
    diagnostic_candidate_count = len([
        row for row in case_results if row["diagnostic_semantic_candidate_available"] is True
    ])
    diagnostic_semantic_correct_count = len([
        row for row in case_results if row["diagnostic_semantic_correct"] is True
    ])
    diagnostic_semantic_incorrect_count = len([
        row for row in case_results if row["diagnostic_semantic_correct"] is False
    ])
    diagnostic_semantic_unavailable_count = len([
        row for row in case_results if row["diagnostic_semantic_correct"] is None
    ])
    diagnostic_failure_classes = Counter(
        str(row.get("diagnostic_failure_class") or "unavailable")
        for row in case_results
        if row.get("score") != 1.0
    )
    metrics = {
        "exact_signed_integer_accuracy": (
            round(correct_count / float(completed_case_count), 6) if completed_case_count else None
        ),
        "correct_count": correct_count,
        "completed_case_count": completed_case_count,
        "expected_case_count": len(cases),
        "format_invalid_count": format_invalid_count,
        "generation_failure_count": generation_failure_count,
        "not_attempted_count": not_attempted_count,
        "parser_code_counts": dict(sorted(parser_codes.items())),
        "generation_failure_code_counts": dict(sorted(generation_failure_codes.items())),
        "diagnostic_semantic_candidate_count": diagnostic_candidate_count,
        "diagnostic_semantic_correct_count": diagnostic_semantic_correct_count,
        "diagnostic_semantic_incorrect_count": diagnostic_semantic_incorrect_count,
        "diagnostic_semantic_unavailable_count": diagnostic_semantic_unavailable_count,
        "diagnostic_failure_class_counts": {
            "format_only": diagnostic_failure_classes.get("format_only", 0),
            "substantive_wrong": diagnostic_failure_classes.get("substantive_wrong", 0),
            "unavailable": diagnostic_failure_classes.get("unavailable", 0),
        },
        "failure_denominator_policy": {
            "model_output_failures": "scored_zero",
            "generation_failures": "excluded_unscored",
            "not_attempted": "excluded_unscored",
        },
    }
    status = "completed" if not generation_failure_count else "partial"
    return _result_envelope(
        status=status,
        tier=tier,
        selection=selection,
        content_identity=content_identity,
        canary=canary,
        runtime_receipt=runtime_receipt,
        metrics=metrics,
        case_results=case_results,
    )


def _result_envelope(
    *,
    status: str,
    tier: str,
    selection: Dict[str, Any],
    content_identity: Dict[str, Any],
    canary: Dict[str, Any],
    runtime_receipt: Dict[str, Any],
    metrics: Dict[str, Any],
    case_results: list,
) -> Dict[str, Any]:
    return {
        "contract_version": OBSERVED_QUICK_SUITE_VERSION,
        "status": status,
        "suite": {
            "suite_id": OBSERVED_QUICK_SUITE_VERSION,
            "tier": tier,
            "generation_policy_id": OBSERVED_QUICK_GENERATION_POLICY_ID,
            "generation_profile_version": QUICK_GENERATION_PROFILE_VERSION,
            "content_pack_benchmark_id": content_identity["content_pack_benchmark_id"],
            "content_pack_fixture_revision": content_identity["content_pack_fixture_revision"],
            "content_pack_full_fixture_sha256": content_identity["content_pack_full_fixture_sha256"],
            "content_pack_full_selection_sha256": content_identity["content_pack_full_selection_sha256"],
            "selection": selection,
        },
        "protocol_canary": canary,
        "observed_runtime": runtime_receipt,
        "metrics": metrics,
        "case_results": case_results,
        "evidence_boundary": {
            "verification_status": "not_verified",
            "comparison_grade": "informational_only",
            "promotion_eligible": False,
            "recommendation_eligible": False,
            "headline_capability_eligible": False,
            "claim_boundary": CLAIM_BOUNDARY,
        },
    }


__all__ = [
    "CLAIM_BOUNDARY",
    "OBSERVED_QUICK_GENERATION_POLICY_ID",
    "OBSERVED_QUICK_PROMPT_DIRECTIVE",
    "OBSERVED_QUICK_SUITE_VERSION",
    "PROTOCOL_CANARY_ID",
    "run_observed_quick_suite",
]
