#!/usr/bin/env python3
"""Prepare and score InferGrade's pinned BFCL V4 local reference subset."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Optional


DEFAULT_DATA_PATH = os.environ.get("BFCL_DATA_PATH", "/opt/bfcl/snapshot.jsonl")
DEFAULT_METADATA_PATH = os.environ.get("BFCL_METADATA_PATH", "/opt/bfcl/snapshot_metadata.json")
TERMINAL_MARKERS = ("[end of text]", "<|end_of_text|>", "<|endoftext|>", "</s>")
IRRELEVANCE_CATEGORIES = {"irrelevance", "live_irrelevance"}
RELEVANCE_CATEGORIES = {"live_relevance"}


def _read_jsonl(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_json(path: str, payload) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _write_jsonl(path: str, rows: Iterable[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _sample_rows(rows: list[dict], limit: Optional[int]) -> list[dict]:
    if not limit or limit >= len(rows):
        return list(rows)
    grouped = defaultdict(list)
    for row in rows:
        grouped[str(row["category"])].append(row)
    for category, bucket in grouped.items():
        bucket.sort(
            key=lambda row: hashlib.sha256(
                (
                    "bfcl_category_rank_v2\0"
                    + category
                    + "\0"
                    + str(row.get("id"))
                ).encode("utf-8")
            ).hexdigest()
        )
    categories = sorted(grouped)
    selected = []
    while len(selected) < limit and categories:
        for category in list(categories):
            if len(selected) >= limit:
                break
            selected.append(grouped[category].pop(0))
            if not grouped[category]:
                categories.remove(category)
    return selected


def _selection_digest(rows: list[dict]) -> str:
    row_ids = sorted(str(row.get("id")) for row in rows)
    return hashlib.sha256("\n".join(row_ids).encode("utf-8")).hexdigest()


def _conversation_text(question) -> str:
    turns = question[0] if question and isinstance(question[0], list) else question
    rendered = []
    for turn in turns or []:
        role = str(turn.get("role") or "user").upper()
        rendered.append("%s: %s" % (role, str(turn.get("content") or "").strip()))
    return "\n".join(rendered)


def _render_prompt(row: dict) -> str:
    category = str(row["category"])
    no_call_instruction = (
        "If none of the tools can answer the request, return the empty JSON array []."
        if category in IRRELEVANCE_CATEGORIES
        else "Use every tool call required to satisfy the request."
    )
    return (
        "You are being evaluated on structured tool use. Choose only from the tools below.\n"
        "Return only a JSON array. Each call must have exactly this shape: "
        '{"name":"tool.name","arguments":{"argument":"value"}}. '
        "Do not execute the tools, add prose, or wrap the JSON in markdown. "
        + no_call_instruction
        + "\n\nTOOLS:\n"
        + json.dumps(row["function"], ensure_ascii=False, sort_keys=True)
        + "\n\nREQUEST:\n"
        + _conversation_text(row["question"])
        + "\n\nJSON tool calls:"
    )


def _case_from_row(row: dict) -> dict:
    row_id = str(row["id"])
    return {
        "case_id": "bfcl_v4/%s" % row_id,
        "task_id": "bfcl_v4/%s" % row_id,
        "question_id": row_id,
        "category": str(row["category"]),
        "prompt": _render_prompt(row),
        "function": row["function"],
        "ground_truth": row.get("ground_truth"),
    }


def prepare(output_dir: str, limit: Optional[int] = None, data_path: str = DEFAULT_DATA_PATH) -> None:
    full_rows = _read_jsonl(data_path)
    rows = _sample_rows(full_rows, limit)
    if not rows:
        raise ValueError("BFCL snapshot is empty: %s" % data_path)
    cases = [_case_from_row(row) for row in rows]
    _write_jsonl(os.path.join(output_dir, "cases.jsonl"), cases)
    snapshot_metadata = json.loads(Path(DEFAULT_METADATA_PATH).read_text(encoding="utf-8"))
    _write_json(
        os.path.join(output_dir, "benchmark_metadata.json"),
        {
            "benchmark_id": "bfcl_local_reference_v1",
            "display_name": "BFCL V4 local tool-use reference",
            "case_count": len(cases),
            "category_count": len({case["category"] for case in cases}),
            "categories": sorted({case["category"] for case in cases}),
            "sample_policy": (
                "category_round_robin_%d_v2" % len(cases)
                if len(rows) < len(full_rows)
                else "pinned_snapshot_order"
            ),
            "selection_digest_algorithm": "sorted_utf8_newline_sha256_v1",
            "selection_sha256": _selection_digest(rows),
            "prompt_format": "infergrade_json_tool_calls_v1",
            "upstream_revision": snapshot_metadata["upstream_revision"],
            "dataset_revision": snapshot_metadata["upstream_revision"],
            "upstream_version": snapshot_metadata["upstream_version"],
            "snapshot_sha256": snapshot_metadata["snapshot_sha256"],
            "claim_boundary": {
                "can_claim": ["pinned BFCL-derived local structured tool-use diagnostic"],
                "cannot_claim": [
                    "official BFCL V4 leaderboard score",
                    "native runtime function-calling support",
                    "BFCL agentic or multi-turn capability",
                ],
            },
        },
    )


def _strip_transport_markers(completion: str) -> str:
    text = str(completion or "").strip()
    while text:
        marker = next((item for item in TERMINAL_MARKERS if text.lower().endswith(item.lower())), None)
        if not marker:
            break
        text = text[: -len(marker)].rstrip()
    return text


def _parse_calls(completion: str) -> tuple[Optional[list[dict]], Optional[str]]:
    try:
        payload = json.loads(_strip_transport_markers(completion))
    except (TypeError, ValueError) as exc:
        return None, "malformed_json:%s" % exc
    if not isinstance(payload, list):
        return None, "wrong_top_level_type"
    calls = []
    for item in payload:
        if not isinstance(item, dict) or set(item) != {"name", "arguments"}:
            return None, "invalid_call_shape"
        if not isinstance(item["name"], str) or not isinstance(item["arguments"], dict):
            return None, "invalid_call_types"
        calls.append({"name": item["name"], "arguments": item["arguments"]})
    return calls, None


def _same_value(actual, expected) -> bool:
    if isinstance(expected, str):
        return isinstance(actual, str) and " ".join(actual.split()).casefold() == " ".join(expected.split()).casefold()
    if isinstance(expected, bool):
        return isinstance(actual, bool) and actual == expected
    if isinstance(expected, (int, float)):
        return not isinstance(actual, bool) and isinstance(actual, (int, float)) and actual == expected
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            _same_value(actual_item, expected_item) for actual_item, expected_item in zip(actual, expected)
        )
    if isinstance(expected, dict):
        return isinstance(actual, dict) and set(actual) == set(expected) and all(
            _same_value(actual[key], expected[key]) for key in expected
        )
    return actual == expected


def _arguments_match(actual: dict, allowed: dict) -> bool:
    allowed_keys = set(allowed)
    if not set(actual).issubset(allowed_keys):
        return False
    for name, choices in allowed.items():
        optional = "" in choices
        if name not in actual:
            if optional:
                continue
            return False
        concrete = [choice for choice in choices if choice != ""]
        if not any(_same_value(actual[name], choice) for choice in concrete):
            return False
    return True


def _call_matches(actual: dict, expected: dict) -> bool:
    expected_name, allowed = next(iter(expected.items()))
    return actual["name"] == expected_name and _arguments_match(actual["arguments"], allowed)


def _exact_calls_match(actual: list[dict], expected: list[dict]) -> bool:
    if len(actual) != len(expected):
        return False
    unmatched = list(actual)
    for expected_call in expected:
        match_index = next((index for index, call in enumerate(unmatched) if _call_matches(call, expected_call)), None)
        if match_index is None:
            return False
        unmatched.pop(match_index)
    return not unmatched


def _function_selection_matches(actual: list[dict], expected: list[dict]) -> bool:
    return Counter(call["name"] for call in actual) == Counter(next(iter(call)) for call in expected)


def _offered_function_names(case: dict) -> set[str]:
    return {str(item.get("name")) for item in case.get("function") or [] if item.get("name")}


def _score_case(case: dict, completion: str) -> dict:
    calls, parse_error = _parse_calls(completion)
    category = str(case["category"])
    if calls is None:
        return {"correct": False, "function_selection_correct": False, "malformed": True, "error_type": parse_error}
    offered = _offered_function_names(case)
    calls_well_scoped = all(call["name"] in offered for call in calls)
    if category in IRRELEVANCE_CATEGORIES:
        correct = calls == []
        return {
            "correct": correct,
            "function_selection_correct": correct,
            "malformed": False,
            "error_type": None if correct else "irrelevant_tool_call",
        }
    if category in RELEVANCE_CATEGORIES:
        correct = bool(calls) and calls_well_scoped
        return {
            "correct": correct,
            "function_selection_correct": correct,
            "malformed": False,
            "error_type": None if correct else "missing_or_unknown_relevant_tool_call",
        }
    expected = list(case.get("ground_truth") or [])
    selection_correct = calls_well_scoped and _function_selection_matches(calls, expected)
    correct = calls_well_scoped and _exact_calls_match(calls, expected)
    return {
        "correct": correct,
        "function_selection_correct": selection_correct,
        "malformed": False,
        "error_type": None if correct else ("argument_mismatch" if selection_correct else "function_selection_mismatch"),
    }


def evaluate(output_dir: str) -> None:
    cases = {str(item["task_id"]): item for item in _read_jsonl(os.path.join(output_dir, "cases.jsonl"))}
    predictions = _read_jsonl(os.path.join(output_dir, "predictions.jsonl"))
    totals = defaultdict(int)
    correct = defaultdict(int)
    selection_correct = 0
    malformed = 0
    case_results = []
    for prediction in predictions:
        if str(prediction.get("generation_status") or "completed") != "completed":
            continue
        task_id = str(prediction.get("task_id") or prediction.get("case_id") or "")
        case = cases.get(task_id)
        if case is None:
            continue
        result = _score_case(case, str(prediction.get("completion") or prediction.get("response") or ""))
        category = str(case["category"])
        totals[category] += 1
        correct[category] += int(result["correct"])
        selection_correct += int(result["function_selection_correct"])
        malformed += int(result["malformed"])
        case_results.append(
            {
                "case_id": case["case_id"],
                "task_id": task_id,
                "category": category,
                "correct": result["correct"],
                "function_selection_correct": result["function_selection_correct"],
                "malformed": result["malformed"],
                "error_type": result["error_type"],
            }
        )
    total = len(case_results)
    correct_count = sum(correct.values())
    accuracy = round(correct_count / float(total), 6) if total else None
    selection_accuracy = round(selection_correct / float(total), 6) if total else None
    category_metrics = {
        category: {
            "accuracy": round(correct[category] / float(count), 6) if count else None,
            "correct_count": correct[category],
            "total_count": count,
        }
        for category, count in sorted(totals.items())
    }
    payload = {
        "benchmark_id": "bfcl_local_reference_v1",
        "display_name": "BFCL V4 local tool-use reference",
        "status": "completed" if total else "failed",
        "primary_metric": {"name": "accuracy", "value": accuracy},
        "metrics": {
            "accuracy": accuracy,
            "correct_count": correct_count,
            "total_count": total,
            "function_selection_accuracy": selection_accuracy,
            "function_selection_correct_count": selection_correct,
            "malformed_output_count": malformed,
        },
        "category_metrics": category_metrics,
        "case_results": case_results,
        "scoring_policy": "infergrade_bfcl_structured_call_accuracy_v1",
        "claim_boundary": {
            "can_claim": ["pinned BFCL-derived local structured tool-use diagnostic"],
            "cannot_claim": [
                "official BFCL V4 leaderboard score",
                "native runtime function-calling support",
                "BFCL agentic or multi-turn capability",
            ],
        },
    }
    if not total:
        payload["error"] = "BFCL scorer received no completed generations"
    _write_json(os.path.join(output_dir, "summary.json"), payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--output-dir", required=True)
    prepare_parser.add_argument("--limit", type=int)
    prepare_parser.add_argument("--data-path", default=DEFAULT_DATA_PATH)
    evaluate_parser = commands.add_parser("evaluate")
    evaluate_parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    if args.command == "prepare":
        prepare(args.output_dir, limit=args.limit, data_path=args.data_path)
    else:
        evaluate(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
