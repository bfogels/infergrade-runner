"""Independent six-case foundation for the reasoning constraint-stress v2 lane.

This module is deliberately fixture- and parser-only.  It does not select a
runtime, change an adapter, or make the v2 lane runnable.  The parser returns
stable outcome codes and never includes model-authored text in its result.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from infergrade.selection_identity import (
    SORTED_JSON_STRING_ARRAY_SHA256_V1,
    selection_digest,
)


FIXTURE_REVISION = "2026-08-reasoning-constraint-stress-v2"
SCORING_POLICY = "reasoning_constraint_stress_v2_exact_signed_integer_v1"
SELECTION_DIGEST_ALGORITHM = SORTED_JSON_STRING_ARRAY_SHA256_V1
FINAL_ANSWER_MARKER = "FINAL_ANSWER:"
FINAL_ANSWER_PARSER_ID = "final_answer_integer_v1"
MAX_INTEGER_DIGITS = 64


_SIGNED_INTEGER = re.compile(r"[+-]?[0-9]+\Z")
_MARKER_LIKE = re.compile(r"(?i)\bfinal[ _-]*answer(?:\s*[:=]|\s+|$)")
_FENCE = re.compile(r"(?:```|~~~)")


@dataclass(frozen=True)
class FinalAnswerParseResult:
    """Stable parser result with no raw response or excerpts."""

    value: Optional[int]
    code: str

    @property
    def ok(self) -> bool:
        return self.code == "ok"

    @property
    def accepted(self) -> bool:
        return self.ok

    @property
    def error_code(self) -> Optional[str]:
        return None if self.ok else self.code

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "value": self.value,
            "code": self.code,
        }


def parse_final_answer(response: str) -> FinalAnswerParseResult:
    """Parse one terminal signed integer without exposing response content.

    Reasoning and other prose are allowed before the terminal line.  The
    marker line must be the only exact marker and the final non-empty line;
    trailing blank lines are harmless, while any trailing content is not.
    """

    if not isinstance(response, str):
        return FinalAnswerParseResult(None, "invalid_input")
    if _FENCE.search(response):
        return FinalAnswerParseResult(None, "fenced_output")

    marker_count = response.count(FINAL_ANSWER_MARKER)
    lines = response.splitlines()
    marker_lines = [
        index for index, line in enumerate(lines) if FINAL_ANSWER_MARKER in line
    ]
    if marker_count == 0:
        if any(_MARKER_LIKE.search(line) for line in lines):
            return FinalAnswerParseResult(None, "marker_like_output")
        return FinalAnswerParseResult(None, "missing_marker")
    if marker_count != 1 or len(marker_lines) != 1:
        return FinalAnswerParseResult(None, "duplicate_marker")

    marker_index = marker_lines[0]
    if not lines[marker_index].startswith(FINAL_ANSWER_MARKER):
        return FinalAnswerParseResult(None, "marker_like_output")
    if any(line.strip() for line in lines[marker_index + 1 :]):
        return FinalAnswerParseResult(None, "trailing_output")
    if any(
        index != marker_index
        and _MARKER_LIKE.search(line)
        for index, line in enumerate(lines)
    ):
        return FinalAnswerParseResult(None, "marker_like_output")

    marker_line = lines[marker_index]
    answer_text = marker_line.split(FINAL_ANSWER_MARKER, 1)[1].strip()
    if not answer_text:
        return FinalAnswerParseResult(None, "empty_answer")
    if not _SIGNED_INTEGER.fullmatch(answer_text):
        return FinalAnswerParseResult(None, "non_integer_answer")
    digits = answer_text[1:] if answer_text[:1] in "+-" else answer_text
    if len(digits) > MAX_INTEGER_DIGITS:
        return FinalAnswerParseResult(None, "integer_too_large")
    try:
        value = int(answer_text, 10)
    except (TypeError, ValueError, OverflowError):
        return FinalAnswerParseResult(None, "non_integer_answer")
    return FinalAnswerParseResult(value, "ok")


# Names kept explicit for callers that identify the protocol by benchmark
# rather than by the generic terminal parser name.
parse_reasoning_constraint_stress_v2_answer = parse_final_answer
parse_terminal_integer = parse_final_answer


_CASES = (
    {
        "case_id": "reasoning-v2-ledger-reconciliation-01",
        "task_id": "reasoning_constraint_stress_v2/ledger-reconciliation-01",
        "category": "signed_ledger",
        "prompt": (
            "A reserve starts at -24. Apply a deposit of 58, a fee of 17, "
            "a transfer of 29 out, and a rebate of 6. Show concise reasoning "
            "and finish with FINAL_ANSWER: followed by the signed balance."
        ),
        "expected_answers": ["-6"],
    },
    {
        "case_id": "reasoning-v2-cyclic-schedule-01",
        "task_id": "reasoning_constraint_stress_v2/cyclic-schedule-01",
        "category": "cyclic_schedule",
        "prompt": (
            "A schedule counter starts at 11. Apply these ordered offsets: "
            "+17, -8, +23, -19, +7, -14, +5. Work it out and finish with "
            "FINAL_ANSWER: followed by the signed counter."
        ),
        "expected_answers": ["22"],
    },
    {
        "case_id": "reasoning-v2-weighted-adjustment-01",
        "task_id": "reasoning_constraint_stress_v2/weighted-adjustment-01",
        "category": "weighted_adjustment",
        "prompt": (
            "Start with a score of -13. Add four groups of 9, subtract three "
            "groups of 7, add two groups of 5, then apply an adjustment of -8. "
            "Explain briefly and finish with FINAL_ANSWER: and the signed score."
        ),
        "expected_answers": ["4"],
    },
    {
        "case_id": "reasoning-v2-capacity-margin-01",
        "task_id": "reasoning_constraint_stress_v2/capacity-margin-01",
        "category": "capacity_margin",
        "prompt": (
            "A store has capacity 480. Four reservations use 137, 86, 59, and "
            "72 units. Determine the remaining margin, then finish with "
            "FINAL_ANSWER: followed by that signed integer."
        ),
        "expected_answers": ["126"],
    },
    {
        "case_id": "reasoning-v2-event-balance-01",
        "task_id": "reasoning_constraint_stress_v2/event-balance-01",
        "category": "event_balance",
        "prompt": (
            "An event balance starts at -4 and changes in order by +9, +8, -3, "
            "and +5. Show the arithmetic and finish with "
            "FINAL_ANSWER: followed by the signed balance."
        ),
        "expected_answers": ["15"],
    },
    {
        "case_id": "reasoning-v2-register-recurrence-01",
        "task_id": "reasoning_constraint_stress_v2/register-recurrence-01",
        "category": "register_recurrence",
        "prompt": (
            "A register starts at 19. For five cycles replace it with three "
            "times its current value minus 4. Reason through the cycles and "
            "finish with FINAL_ANSWER: followed by the signed register value."
        ),
        "expected_answers": ["4133"],
    },
)


def reasoning_constraint_stress_v2_cases() -> List[Dict[str, Any]]:
    """Return fresh copies of the six independent v2 foundation cases."""

    return [
        dict(case, expected_answers=list(case["expected_answers"]))
        for case in _CASES
    ]


SELECTION_DIGEST_SHA256 = selection_digest(
    (case["task_id"] for case in _CASES),
    SELECTION_DIGEST_ALGORITHM,
)
SELECTION_DIGEST = SELECTION_DIGEST_SHA256
EXPECTED_ANSWER_VECTOR = ("-6", "22", "4", "126", "15", "4133")
ANSWER_VECTOR = EXPECTED_ANSWER_VECTOR
FIXTURE_SHA256 = hashlib.sha256(
    json.dumps(_CASES, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()
FULL_FIXTURE_SHA256 = FIXTURE_SHA256


__all__ = [
    "FINAL_ANSWER_MARKER",
    "FINAL_ANSWER_PARSER_ID",
    "FIXTURE_REVISION",
    "MAX_INTEGER_DIGITS",
    "SCORING_POLICY",
    "SELECTION_DIGEST",
    "SELECTION_DIGEST_ALGORITHM",
    "SELECTION_DIGEST_SHA256",
    "ANSWER_VECTOR",
    "EXPECTED_ANSWER_VECTOR",
    "FIXTURE_SHA256",
    "FULL_FIXTURE_SHA256",
    "FinalAnswerParseResult",
    "parse_final_answer",
    "parse_reasoning_constraint_stress_v2_answer",
    "parse_terminal_integer",
    "reasoning_constraint_stress_v2_cases",
]
