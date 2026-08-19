#!/usr/bin/env python3
"""Prepare and score InferGrade's pinned LongBench v2 local reference subset."""

import argparse
import hashlib
import json
import os
import re
from collections import defaultdict
from typing import Iterable, List, Optional


DEFAULT_DATA_PATH = os.environ.get(
    "LONGBENCH_V2_DATA_PATH", "/opt/longbench-v2/snapshot.jsonl"
)
DEFAULT_METADATA_PATH = os.environ.get(
    "LONGBENCH_V2_METADATA_PATH", "/opt/longbench-v2/snapshot_metadata.json"
)
LETTERS = "ABCD"
ANSWER_PATTERNS = (
    re.compile(r"\bfinal\s+answer\s+letter\s*:\s*([A-D])\b", re.IGNORECASE),
    re.compile(r"\b(?:answer|option|choice)\s*(?:is|:)?\s*\(?([A-D])\)?\b", re.IGNORECASE),
    re.compile(r"^\s*\(?([A-D])\)?(?:[\).:]|\s*$)", re.IGNORECASE),
)
TERMINAL_MARKERS = ("[end of text]", "<|end_of_text|>", "<|endoftext|>", "</s>")
EMPTY_THINK_PREFIX = re.compile(r"^\s*<think>\s*</think>\s*", re.IGNORECASE)
EXPECTED_SELECTION_SHA256 = "1a5f48517a31dc80083700955b92d9524cba2d863448209956e2cf1b423079a3"
EXPECTED_SNAPSHOT_SHA256 = "677ac38dc799b0bbe61816f1d0c245bb93f01dd535a71ecfde6fa619d3eb86db"
SELECTION_DIGEST_ALGORITHM = "sorted_utf8_newline_sha256_v1"
SELECTION_DIGEST_CONVENTION = (
    "sha256 of sorted raw LongBench _id values joined by one UTF-8 newline, "
    "with no trailing newline"
)
SUPPORTED_TIER_PREFIXES = {"canary": 6, "standard": 12, "gold": 23}
CONTEXT_BUCKETS = (16384, 32768, 65536, 131072)


def _write_json(path: str, payload) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _write_jsonl(path: str, rows: Iterable[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: str) -> List[dict]:
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Expected an object in %s" % path)
    return payload


def _selection_digest(rows: List[dict]) -> str:
    ids = sorted(str(row.get("_id")) for row in rows)
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


def _selection_projection(row: dict) -> dict:
    """Return the prompt-free public identity projection for one selected row."""
    return {
        "_id": str(row["_id"]),
        "domain": str(row["domain"]),
        "sub_domain": str(row["sub_domain"]),
        "difficulty": str(row["difficulty"]),
        "length": str(row["length"]),
    }


def _tier_for_limit(limit: Optional[int]) -> tuple:
    if limit is None:
        return "gold", SUPPORTED_TIER_PREFIXES["gold"]
    if limit not in SUPPORTED_TIER_PREFIXES.values():
        raise ValueError(
            "Unsupported LongBench tier limit %r; expected one of %s"
            % (limit, sorted(SUPPORTED_TIER_PREFIXES.values()))
        )
    return next(tier for tier, count in SUPPORTED_TIER_PREFIXES.items() if count == limit), limit


def _validate_source_metadata(full_rows: List[dict], source_metadata: dict, snapshot_sha256: str) -> None:
    expected = {
        "benchmark_id": "longbench_v2_local_reference_v1",
        "dataset": "zai-org/LongBench-v2",
        "dataset_revision": "2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9",
        "dataset_sha256": "15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2",
        "dataset_license": "Apache-2.0",
        "case_count": 23,
        "source_case_count": 503,
        "source_short_case_count": 180,
        "source_context_fit_case_count": 177,
        "maximum_estimated_context_tokens": 131072,
        "domain_count": 6,
        "difficulty_count": 2,
        "length_scope": "short",
        "selection_policy": "short_domain_difficulty_hash_rank_balanced_tier_blocks_v1",
        "selection_digest_algorithm": SELECTION_DIGEST_ALGORITHM,
        "selection_digest_convention": SELECTION_DIGEST_CONVENTION,
        "snapshot_sha256": snapshot_sha256,
    }
    for field, expected_value in expected.items():
        if source_metadata.get(field) != expected_value:
            raise ValueError("LongBench v2 snapshot metadata mismatch: %s" % field)
    selected_ids = [str(row.get("_id") or "") for row in full_rows]
    if any(not item for item in selected_ids):
        raise ValueError("LongBench v2 snapshot contains a missing raw _id")
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("LongBench v2 snapshot contains duplicate raw _id values")
    if source_metadata.get("selected_ids") != selected_ids:
        raise ValueError("LongBench v2 snapshot metadata selected_ids order mismatch")
    if source_metadata.get("selection_sha256") != _selection_digest(full_rows):
        raise ValueError("LongBench v2 snapshot metadata selection digest mismatch")
    if source_metadata.get("selection_projection") != [
        _selection_projection(row) for row in full_rows
    ]:
        raise ValueError("LongBench v2 snapshot metadata selection projection mismatch")


def _nominal_context_bucket_tokens(context: str) -> int:
    """Choose a conservative reviewed bucket without relying on source text."""
    text = str(context)
    approximate_tokens = max(
        int(len(text.split()) * 1.5),
        int(len(text) / 3.0),
    ) + 1024
    for bucket in CONTEXT_BUCKETS:
        if approximate_tokens <= bucket:
            return bucket
    raise ValueError(
        "LongBench v2 short-context case exceeds the reviewed 131072-token local bucket"
    )


def _case_from_row(row: dict) -> dict:
    row_id = str(row["_id"])
    context = str(row["context"])
    nominal_context_bucket_tokens = _nominal_context_bucket_tokens(context)
    options = "\n".join(
        "%s. %s" % (letter, str(row["choice_" + letter]).strip())
        for letter in LETTERS
    )
    prompt = (
        "InferGrade nominal context bucket: {context_bucket} tokens.\n"
        "Read the complete long context and answer the multiple-choice question. "
        "Use the context rather than outside knowledge. Think carefully, but final output "
        "must be only the option letter.\n\n"
        "Context:\n{context}\n\n"
        "Question: {question}\n\n{options}\n\nFinal answer letter:"
    ).format(
        context_bucket=nominal_context_bucket_tokens,
        context=context,
        question=str(row["question"]).strip(),
        options=options,
    )
    return {
        "case_id": "longbench_v2/%s" % row_id,
        "task_id": "longbench_v2/%s" % row_id,
        "question_id": row_id,
        "category": str(row["domain"]),
        "sub_domain": str(row["sub_domain"]),
        "difficulty": str(row["difficulty"]),
        "length": str(row["length"]),
        "context_word_count": len(str(row["context"]).split()),
        "nominal_context_bucket_tokens": nominal_context_bucket_tokens,
        "prompt": prompt,
        "answer": str(row["answer"]).strip().upper(),
        "answer_index": LETTERS.index(str(row["answer"]).strip().upper()),
    }


def _strip_terminal_markers(completion: str) -> str:
    text = completion.strip()
    while text:
        lowered = text.lower()
        marker = next(
            (item for item in TERMINAL_MARKERS if lowered.endswith(item.lower())),
            None,
        )
        if not marker:
            break
        text = text[: -len(marker)].rstrip()
    return text


def _prediction_letter(completion: str) -> Optional[str]:
    text = EMPTY_THINK_PREFIX.sub(
        "", _strip_terminal_markers(str(completion or "")), count=1
    )
    for pattern in ANSWER_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).upper()
    return None


def prepare(
    output_dir: str,
    limit: int = None,
    data_path: str = DEFAULT_DATA_PATH,
    metadata_path: str = DEFAULT_METADATA_PATH,
) -> None:
    full_rows = _read_jsonl(data_path)
    if len(full_rows) != 23:
        raise ValueError("Expected 23 LongBench v2 snapshot rows, found %d" % len(full_rows))
    tier, expected_count = _tier_for_limit(limit)
    rows = full_rows[:expected_count]
    if not rows:
        raise ValueError("LongBench v2 selection cannot be empty")
    source_metadata = _read_json(metadata_path)
    actual_selection_sha256 = _selection_digest(full_rows)
    with open(data_path, "rb") as snapshot_handle:
        actual_snapshot_sha256 = hashlib.sha256(snapshot_handle.read()).hexdigest()
    if actual_selection_sha256 != EXPECTED_SELECTION_SHA256:
        raise ValueError("LongBench v2 selected case identity does not match the reviewed snapshot")
    if actual_snapshot_sha256 != EXPECTED_SNAPSHOT_SHA256:
        raise ValueError("LongBench v2 snapshot content does not match the reviewed snapshot")
    _validate_source_metadata(full_rows, source_metadata, actual_snapshot_sha256)
    cases = [_case_from_row(row) for row in rows]
    _write_jsonl(os.path.join(output_dir, "cases.jsonl"), cases)
    selected_ids = [str(row["_id"]) for row in rows]
    _write_json(
        os.path.join(output_dir, "selection_receipt.json"),
        {
            "artifact_kind": "longbench_selection_receipt",
            "artifact_spec_version": "0.1.0",
            "benchmark_id": source_metadata["benchmark_id"],
            "dataset": source_metadata["dataset"],
            "dataset_revision": source_metadata["dataset_revision"],
            "dataset_sha256": source_metadata["dataset_sha256"],
            "dataset_license": source_metadata["dataset_license"],
            "source_case_count": source_metadata["source_case_count"],
            "source_short_case_count": source_metadata["source_short_case_count"],
            "source_context_fit_case_count": source_metadata["source_context_fit_case_count"],
            "maximum_estimated_context_tokens": source_metadata["maximum_estimated_context_tokens"],
            "domain_count": source_metadata["domain_count"],
            "difficulty_count": source_metadata["difficulty_count"],
            "length_scope": source_metadata["length_scope"],
            "selection_policy": source_metadata["selection_policy"],
            "selection_digest_algorithm": SELECTION_DIGEST_ALGORITHM,
            "selection_digest_convention": SELECTION_DIGEST_CONVENTION,
            "snapshot_sha256": actual_snapshot_sha256,
            "tier": tier,
            "case_count": len(cases),
            "selected_ids": selected_ids,
            "prepared_ids": [str(case["question_id"]) for case in cases],
            "selection_projection": [_selection_projection(row) for row in rows],
            "selection_sha256": _selection_digest(rows),
        },
    )
    _write_json(
        os.path.join(output_dir, "benchmark_metadata.json"),
        {
            "benchmark_id": "longbench_v2_local_reference_v1",
            "display_name": "LongBench v2 local reference",
            "case_count": len(cases),
            "category_count": len(set(case["category"] for case in cases)),
            "difficulty_count": len(set(case["difficulty"] for case in cases)),
            "length_scope": "short",
            "minimum_context_word_count": min(case["context_word_count"] for case in cases),
            "maximum_context_word_count": max(case["context_word_count"] for case in cases),
            "context_bucket_counts": {
                str(bucket): len(
                    [
                        case
                        for case in cases
                        if case["nominal_context_bucket_tokens"] == bucket
                    ]
                )
                for bucket in CONTEXT_BUCKETS
                if any(
                    case["nominal_context_bucket_tokens"] == bucket
                    for case in cases
                )
            },
            "dataset": source_metadata["dataset"],
            "dataset_revision": source_metadata["dataset_revision"],
            "dataset_sha256": source_metadata["dataset_sha256"],
            "dataset_license": source_metadata["dataset_license"],
            "snapshot_sha256": actual_snapshot_sha256,
            "sample_policy": (
                "short_domain_balanced_difficulty_mixed_6_v1"
                if len(cases) == 6
                else "short_domain_difficulty_balanced_%d_v1" % len(cases)
            ),
            "selection_digest_algorithm": "sorted_utf8_newline_sha256_v1",
            "selection_digest_convention": SELECTION_DIGEST_CONVENTION,
            "selection_sha256": _selection_digest(rows),
        },
    )


def _group_metrics(results: List[dict], field: str) -> dict:
    totals = defaultdict(int)
    correct = defaultdict(int)
    for result in results:
        key = str(result[field])
        totals[key] += 1
        correct[key] += int(result["correct"])
    return {
        key: {
            "accuracy": round(correct[key] / float(total), 6) if total else None,
            "correct_count": correct[key],
            "total_count": total,
        }
        for key, total in sorted(totals.items())
    }


def evaluate(output_dir: str) -> None:
    cases = {
        str(item["task_id"]): item
        for item in _read_jsonl(os.path.join(output_dir, "cases.jsonl"))
    }
    predictions = _read_jsonl(os.path.join(output_dir, "predictions.jsonl"))
    results = []
    invalid_count = 0
    for prediction in predictions:
        if str(prediction.get("generation_status") or "completed") != "completed":
            continue
        task_id = str(prediction.get("task_id") or prediction.get("case_id") or "")
        case = cases.get(task_id)
        if not case:
            invalid_count += 1
            continue
        predicted = _prediction_letter(
            str(prediction.get("completion") or prediction.get("response") or "")
        )
        expected = str(case["answer"])
        invalid_count += int(predicted is None)
        results.append(
            {
                "case_id": case["case_id"],
                "task_id": task_id,
                "category": case["category"],
                "sub_domain": case["sub_domain"],
                "difficulty": case["difficulty"],
                "length": case["length"],
                "context_word_count": case["context_word_count"],
                "nominal_context_bucket_tokens": case[
                    "nominal_context_bucket_tokens"
                ],
                "expected": expected,
                "predicted": predicted,
                "correct": predicted == expected,
            }
        )
    total = len(results)
    correct_count = sum(int(result["correct"]) for result in results)
    accuracy = round(correct_count / float(total), 6) if total else None
    _write_json(
        os.path.join(output_dir, "summary.json"),
        {
            "benchmark_id": "longbench_v2_local_reference_v1",
            "display_name": "LongBench v2 local reference",
            "status": "completed" if total else "failed",
            "primary_metric": {"name": "accuracy", "value": accuracy},
            "metrics": {
                "accuracy": accuracy,
                "correct_count": correct_count,
                "total_count": total,
                "invalid_count": invalid_count,
                "malformed_output_count": invalid_count,
            },
            "category_metrics": _group_metrics(results, "category"),
            "difficulty_metrics": _group_metrics(results, "difficulty"),
            "length_metrics": _group_metrics(results, "length"),
            "context_bucket_metrics": _group_metrics(
                results, "nominal_context_bucket_tokens"
            ),
            "case_results": results,
            "scoring_policy": "longbench_v2_exact_answer_letter_accuracy_v1",
            "claim_boundary": {
                "can_claim": [
                    "pinned LongBench v2-derived short-context local reference accuracy"
                ],
                "cannot_claim": [
                    "official LongBench v2 leaderboard score",
                    "medium, long, or maximum-context capability",
                    "general long-context reasoning capability",
                ],
            },
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--output-dir", required=True)
    prepare_parser.add_argument("--limit", type=int)
    prepare_parser.add_argument("--data-path", default=DEFAULT_DATA_PATH)
    prepare_parser.add_argument("--metadata-path", default=DEFAULT_METADATA_PATH)
    evaluate_parser = commands.add_parser("evaluate")
    evaluate_parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    if args.command == "prepare":
        prepare(
            args.output_dir,
            limit=args.limit,
            data_path=args.data_path,
            metadata_path=args.metadata_path,
        )
    else:
        evaluate(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
