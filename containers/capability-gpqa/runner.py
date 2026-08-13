import argparse
import csv
import hashlib
import json
import os
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional


DEFAULT_DATA_PATH = os.environ.get("GPQA_DATA_PATH", "/opt/gpqa/gpqa_diamond.csv")
LETTERS = "ABCD"
ANSWER_PATTERNS = (
    re.compile(r"\bfinal\s+answer\s+letter\s*:\s*([A-D])\b", re.IGNORECASE),
    re.compile(r"\b(?:answer|option|choice)\s*(?:is|:)?\s*\(?([A-D])\)?\b", re.IGNORECASE),
    re.compile(r"^\s*\(?([A-D])\)?(?:[\).:]|\s*$)", re.IGNORECASE),
)
TERMINAL_MARKERS = ("[end of text]", "<|end_of_text|>", "<|endoftext|>", "</s>")
EMPTY_THINK_PREFIX = re.compile(r"^\s*<think>\s*</think>\s*", re.IGNORECASE)


def _write_json(path: str, payload) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _write_jsonl(path: str, rows: Iterable[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _load_rows(path: str) -> List[dict]:
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 198:
        raise ValueError("Expected 198 GPQA Diamond rows, found %d" % len(rows))
    return rows


def _sample_rows(rows: List[dict], limit: Optional[int]) -> List[dict]:
    if not limit or limit >= len(rows):
        return list(rows)
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("High-level domain") or "unknown")].append(row)
    for domain, bucket in grouped.items():
        bucket.sort(
            key=lambda row: hashlib.sha256(
                (
                    "gpqa_domain_rank_v2\0"
                    + domain
                    + "\0"
                    + str(row.get("Record ID"))
                ).encode("utf-8")
            ).hexdigest()
        )
    selected = []
    domains = sorted(grouped)
    cursor = 0
    while len(selected) < limit and domains:
        domain = domains[cursor % len(domains)]
        selected.append(grouped[domain].pop(0))
        domains = [item for item in domains if grouped[item]]
        cursor += 1
    return selected


def _selection_digest(rows: List[dict]) -> str:
    record_ids = sorted(str(row.get("Record ID")) for row in rows)
    return hashlib.sha256("\n".join(record_ids).encode("utf-8")).hexdigest()


def _options_for_row(row: dict) -> List[str]:
    options = [
        str(row["Correct Answer"]),
        str(row["Incorrect Answer 1"]),
        str(row["Incorrect Answer 2"]),
        str(row["Incorrect Answer 3"]),
    ]
    seed = str(row.get("Record ID") or row.get("Question") or "")
    return sorted(options, key=lambda option: hashlib.sha256((seed + "\0" + option).encode("utf-8")).hexdigest())


def _case_from_row(row: dict) -> dict:
    options = _options_for_row(row)
    answer = LETTERS[options.index(str(row["Correct Answer"]))]
    record_id = str(row.get("Record ID") or hashlib.sha256(str(row["Question"]).encode()).hexdigest()[:16])
    rendered = "\n".join("%s. %s" % (LETTERS[index], option) for index, option in enumerate(options))
    prompt = (
        "Answer the following expert multiple-choice question. Think carefully, but final output must be only "
        "the option letter.\n\nDomain: {domain}\nQuestion: {question}\n\n{options}\n\nFinal answer letter:"
    ).format(
        domain=str(row.get("High-level domain") or "unknown"),
        question=str(row.get("Question") or "").strip(),
        options=rendered,
    )
    return {
        "case_id": "gpqa_diamond/%s" % record_id,
        "task_id": "gpqa_diamond/%s" % record_id,
        "question_id": record_id,
        "category": str(row.get("High-level domain") or "unknown"),
        "prompt": prompt,
        "answer": answer,
        "answer_index": LETTERS.index(answer),
    }


def _strip_terminal_markers(completion: str) -> str:
    text = completion.strip()
    while text:
        lowered = text.lower()
        marker = next((item for item in TERMINAL_MARKERS if lowered.endswith(item.lower())), None)
        if not marker:
            break
        text = text[: -len(marker)].rstrip()
    return text


def _prediction_letter(completion: str) -> Optional[str]:
    text = EMPTY_THINK_PREFIX.sub("", _strip_terminal_markers(str(completion or "")), count=1)
    for pattern in ANSWER_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).upper()
    return None


def prepare(output_dir: str, limit: int = None, data_path: str = DEFAULT_DATA_PATH) -> None:
    full_rows = _load_rows(data_path)
    rows = _sample_rows(full_rows, limit)
    cases = [_case_from_row(row) for row in rows]
    _write_jsonl(os.path.join(output_dir, "cases.jsonl"), cases)
    _write_json(
        os.path.join(output_dir, "benchmark_metadata.json"),
        {
            "benchmark_id": "gpqa_diamond_reference_v1",
            "display_name": "GPQA Diamond reference",
            "case_count": len(cases),
            "dataset_revision": os.environ.get("GPQA_REPOSITORY_REVISION"),
            "dataset_sha256": os.environ.get("GPQA_DATASET_SHA256"),
            "sample_policy": (
                "domain_round_robin_%d_v2" % len(cases)
                if len(rows) < len(full_rows)
                else "full_snapshot_order"
            ),
            "selection_sha256": _selection_digest(rows),
            "category_count": len(set(case["category"] for case in cases)),
        },
    )


def evaluate(output_dir: str) -> None:
    cases = {str(item["task_id"]): item for item in _read_jsonl(os.path.join(output_dir, "cases.jsonl"))}
    predictions = _read_jsonl(os.path.join(output_dir, "predictions.jsonl"))
    category_totals = defaultdict(int)
    category_correct = defaultdict(int)
    results = []
    correct_count = 0
    invalid_count = 0
    for prediction in predictions:
        if str(prediction.get("generation_status") or "completed") != "completed":
            continue
        task_id = str(prediction.get("task_id") or prediction.get("case_id") or "")
        case = cases.get(task_id)
        if not case:
            invalid_count += 1
            continue
        predicted = _prediction_letter(str(prediction.get("completion") or prediction.get("response") or ""))
        expected = str(case["answer"])
        category = str(case["category"])
        correct = predicted == expected
        category_totals[category] += 1
        category_correct[category] += int(correct)
        correct_count += int(correct)
        invalid_count += int(predicted is None)
        results.append(
            {
                "case_id": case["case_id"],
                "task_id": task_id,
                "category": category,
                "expected": expected,
                "predicted": predicted,
                "correct": correct,
            }
        )
    total = len(results)
    accuracy = round(correct_count / float(total), 6) if total else None
    category_metrics = {
        category: {
            "accuracy": round(category_correct[category] / float(count), 6) if count else None,
            "correct_count": category_correct[category],
            "total_count": count,
        }
        for category, count in sorted(category_totals.items())
    }
    _write_json(
        os.path.join(output_dir, "summary.json"),
        {
            "benchmark_id": "gpqa_diamond_reference_v1",
            "display_name": "GPQA Diamond reference",
            "status": "completed" if total else "failed",
            "primary_metric": {"name": "accuracy", "value": accuracy},
            "metrics": {
                "accuracy": accuracy,
                "correct_count": correct_count,
                "total_count": total,
                "invalid_count": invalid_count,
                "malformed_output_count": invalid_count,
            },
            "category_metrics": category_metrics,
            "case_results": results,
            "scoring_policy": "exact_multiple_choice_letter_accuracy_v4",
        },
    )


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
