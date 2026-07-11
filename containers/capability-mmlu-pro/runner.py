import argparse
import json
import os
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Optional


DEFAULT_DATA_PATH = os.environ.get("MMLU_PRO_DATA_PATH", "/opt/mmlu_pro/test.jsonl")
LETTERS = "ABCDEFGHIJ"
ANSWER_PATTERNS = (
    re.compile(r"\b(?:answer|option|choice)\s*(?:is|:)?\s*\(?([A-J])\)?\b", re.IGNORECASE),
    re.compile(r"^\s*\(?([A-J])\)?(?:[\).:]|\s*$)", re.IGNORECASE),
)
TERMINAL_MARKERS = (
    "[end of text]",
    "<|end_of_text|>",
    "<|endoftext|>",
    "</s>",
)


def _write_json(path: str, payload) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _write_jsonl(path: str, rows: Iterable[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _read_jsonl(path: str) -> List[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _load_rows(data_path: str) -> List[dict]:
    if not os.path.exists(data_path):
        raise FileNotFoundError(
            "MMLU-Pro data snapshot is missing at %s. Rebuild the capability image with the pinned dataset snapshot."
            % data_path
        )
    rows = _read_jsonl(data_path)
    if not rows:
        raise ValueError("MMLU-Pro data snapshot is empty: %s" % data_path)
    return rows


def _sample_rows(rows: List[dict], limit: Optional[int]) -> List[dict]:
    if not limit or limit >= len(rows):
        return list(rows)
    grouped: Dict[str, List[dict]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("category") or "unknown")].append(row)

    selected = []
    categories = sorted(grouped)
    cursor = 0
    while len(selected) < limit and categories:
        category = categories[cursor % len(categories)]
        bucket = grouped[category]
        if bucket:
            selected.append(bucket.pop(0))
        categories = [item for item in categories if grouped[item]]
        cursor += 1
    return selected[:limit]


def _answer_letter(row: dict) -> str:
    answer_index = row.get("answer_index")
    try:
        index = int(answer_index)
    except (TypeError, ValueError):
        index = -1
    if 0 <= index < len(LETTERS):
        return LETTERS[index]
    answer = str(row.get("answer") or "").strip().upper()
    if len(answer) == 1 and answer in LETTERS:
        return answer
    raise ValueError("MMLU-Pro row has no supported answer index or letter: %r" % (row.get("question_id"),))


def _render_prompt(row: dict) -> str:
    options = list(row.get("options") or [])
    rendered_options = []
    for index, option in enumerate(options):
        if index >= len(LETTERS):
            break
        rendered_options.append("%s. %s" % (LETTERS[index], str(option).strip()))
    return (
        "Answer the following multiple-choice question. Think carefully, but final output must be only the option letter.\n\n"
        "Subject: {category}\n"
        "Question: {question}\n\n"
        "{options}\n\n"
        "Final answer letter:"
    ).format(
        category=str(row.get("category") or "unknown"),
        question=str(row.get("question") or "").strip(),
        options="\n".join(rendered_options),
    )


def _case_from_row(row: dict) -> dict:
    question_id = str(row.get("question_id"))
    answer_letter = _answer_letter(row)
    return {
        "case_id": "mmlu_pro/%s" % question_id,
        "task_id": "mmlu_pro/%s" % question_id,
        "question_id": row.get("question_id"),
        "category": str(row.get("category") or "unknown"),
        "source": str(row.get("src") or ""),
        "prompt": _render_prompt(row),
        "answer": answer_letter,
        "answer_index": LETTERS.index(answer_letter),
    }


def _prediction_letter(completion: str) -> Optional[str]:
    text = _strip_terminal_markers(str(completion or ""))
    for pattern in ANSWER_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).upper()
    return None


def _strip_terminal_markers(completion: str) -> str:
    """Remove only trailing runtime end-of-generation sentinels.

    llama.cpp may render a terminal token after otherwise valid model output.
    These markers are transport metadata, not model-authored answer text. Keep
    normalization deliberately suffix-only so additional prose remains visible
    to the strict multiple-choice parser instead of being hidden.
    """
    text = completion.strip()
    while text:
        lowered = text.lower()
        matched = False
        for marker in TERMINAL_MARKERS:
            if lowered.endswith(marker.lower()):
                text = text[: -len(marker)].rstrip()
                matched = True
                break
        if not matched:
            break
    return text


def prepare(output_dir: str, limit: int = None, data_path: str = DEFAULT_DATA_PATH) -> None:
    rows = _sample_rows(_load_rows(data_path), limit)
    cases = [_case_from_row(row) for row in rows]
    _write_jsonl(os.path.join(output_dir, "cases.jsonl"), cases)
    _write_json(
        os.path.join(output_dir, "benchmark_metadata.json"),
        {
            "benchmark_id": "mmlu_pro_reference_v1",
            "display_name": "MMLU-Pro reference",
            "case_count": len(cases),
            "data_path": data_path,
            "dataset_revision": os.environ.get("MMLU_PRO_DATASET_REVISION"),
            "sample_policy": "category_round_robin_v1" if limit else "full_snapshot_order",
            "category_count": len(set(case["category"] for case in cases)),
        },
    )


def evaluate(output_dir: str) -> None:
    cases = {str(item["task_id"]): item for item in _read_jsonl(os.path.join(output_dir, "cases.jsonl"))}
    predictions = _read_jsonl(os.path.join(output_dir, "predictions.jsonl"))
    category_totals = defaultdict(int)
    category_correct = defaultdict(int)
    case_results = []
    correct_count = 0
    invalid_count = 0

    for prediction in predictions:
        task_id = str(prediction.get("task_id") or prediction.get("case_id") or "")
        case = cases.get(task_id)
        if not case:
            invalid_count += 1
            continue
        predicted = _prediction_letter(str(prediction.get("completion") or prediction.get("response") or ""))
        expected = str(case.get("answer") or "").upper()
        category = str(case.get("category") or "unknown")
        is_correct = predicted == expected
        category_totals[category] += 1
        if predicted is None:
            invalid_count += 1
        if is_correct:
            correct_count += 1
            category_correct[category] += 1
        case_results.append(
            {
                "case_id": case.get("case_id"),
                "task_id": task_id,
                "category": category,
                "expected": expected,
                "predicted": predicted,
                "correct": is_correct,
            }
        )

    total = len(case_results)
    category_metrics = {
        category: {
            "accuracy": round(category_correct[category] / float(total_count), 6) if total_count else None,
            "correct_count": category_correct[category],
            "total_count": total_count,
        }
        for category, total_count in sorted(category_totals.items())
    }
    accuracy = round(correct_count / float(total), 6) if total else None
    _write_json(
        os.path.join(output_dir, "summary.json"),
        {
            "benchmark_id": "mmlu_pro_reference_v1",
            "display_name": "MMLU-Pro reference",
            "status": "completed",
            "primary_metric": {"name": "accuracy", "value": accuracy},
            "metrics": {
                "accuracy": accuracy,
                "correct_count": correct_count,
                "total_count": total,
                "invalid_count": invalid_count,
            },
            "category_metrics": category_metrics,
            "case_results": case_results,
            "scoring_policy": "exact_multiple_choice_letter_accuracy_v1",
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--output-dir", required=True)
    prepare_parser.add_argument("--limit", type=int)
    prepare_parser.add_argument("--data-path", default=DEFAULT_DATA_PATH)

    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--output-dir", required=True)

    args = parser.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    if args.command == "prepare":
        prepare(args.output_dir, limit=args.limit, data_path=args.data_path)
        return 0
    evaluate(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
