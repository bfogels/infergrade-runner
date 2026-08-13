import argparse
import hashlib
import json
import os
import sys
from typing import Iterable, List

sys.path.insert(0, "/opt")

import nltk
from instruction_following_eval import evaluation_lib

_NLTK_TOKENIZER_RESOURCES = (
    ("tokenizers/punkt", "punkt"),
    ("tokenizers/punkt_tab/english", "punkt_tab"),
)


def _write_json(path: str, payload) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _write_jsonl(path: str, rows: Iterable[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def _read_predictions(path: str) -> dict:
    prompt_to_response = {}
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            prompt_to_response[row["prompt"]] = row.get("response", "")
    return prompt_to_response


def _instruction_accuracy(outputs: List) -> float:
    total = sum(len(output.follow_instruction_list) for output in outputs)
    if total == 0:
        return 0.0
    correct = sum(sum(output.follow_instruction_list) for output in outputs)
    return correct / float(total)


def _ensure_nltk_tokenizers(output_dir: str) -> None:
    nltk_data_dir = os.path.join(output_dir, "nltk_data")
    os.makedirs(nltk_data_dir, exist_ok=True)
    if nltk_data_dir not in nltk.data.path:
        nltk.data.path.insert(0, nltk_data_dir)
    existing_data_dirs = [item for item in os.environ.get("NLTK_DATA", "").split(os.pathsep) if item]
    if nltk_data_dir not in existing_data_dirs:
        os.environ["NLTK_DATA"] = os.pathsep.join([nltk_data_dir] + existing_data_dirs)
    missing_packages = []
    for resource_path, package_name in _NLTK_TOKENIZER_RESOURCES:
        try:
            nltk.data.find(resource_path)
        except LookupError:
            missing_packages.append(package_name)
    for package_name in missing_packages:
        nltk.download(package_name, download_dir=nltk_data_dir, quiet=True)
    for resource_path, _package_name in _NLTK_TOKENIZER_RESOURCES:
        nltk.data.find(resource_path)


def _sample_inputs(inputs: List, limit: int = None) -> List:
    """Select a deterministic tier that favors breadth across instruction types."""
    if not limit or limit >= len(inputs):
        return list(inputs)
    candidates = list(inputs)
    selected = []
    instruction_counts = {}
    while candidates and len(selected) < limit:
        def rank(item):
            instruction_ids = sorted(set(item.instruction_id_list))
            novel_count = sum(
                instruction_counts.get(instruction_id, 0) == 0
                for instruction_id in instruction_ids
            )
            coverage_load = sum(
                instruction_counts.get(instruction_id, 0)
                for instruction_id in instruction_ids
            )
            stable_rank = hashlib.sha256(
                ("ifeval_instruction_coverage_v1\0" + str(item.key)).encode("utf-8")
            ).hexdigest()
            return (-novel_count, coverage_load, stable_rank)

        chosen = min(candidates, key=rank)
        candidates.remove(chosen)
        selected.append(chosen)
        for instruction_id in set(chosen.instruction_id_list):
            instruction_counts[instruction_id] = instruction_counts.get(instruction_id, 0) + 1
    return selected


def _selection_digest(inputs: List) -> str:
    payload = "\n".join(str(item.key) for item in inputs).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def prepare(output_dir: str, limit: int = None) -> None:
    _ensure_nltk_tokenizers(output_dir)
    input_path = "/opt/instruction_following_eval/data/input_data.jsonl"
    full_inputs = evaluation_lib.read_prompt_list(input_path)
    inputs = _sample_inputs(full_inputs, limit)
    all_instruction_types = {
        instruction_id
        for item in full_inputs
        for instruction_id in item.instruction_id_list
    }
    selected_instruction_types = {
        instruction_id
        for item in inputs
        for instruction_id in item.instruction_id_list
    }

    filtered_input_path = os.path.join(output_dir, "input_data.jsonl")
    cases_path = os.path.join(output_dir, "cases.jsonl")

    _write_jsonl(
        filtered_input_path,
        [
            {
                "key": inp.key,
                "instruction_id_list": inp.instruction_id_list,
                "prompt": inp.prompt,
                "kwargs": inp.kwargs,
            }
            for inp in inputs
        ],
    )
    _write_jsonl(
        cases_path,
        [
            {
                "case_id": str(inp.key),
                "prompt": inp.prompt,
                "instruction_id_list": inp.instruction_id_list,
            }
            for inp in inputs
        ],
    )
    _write_json(
        os.path.join(output_dir, "benchmark_metadata.json"),
        {
            "benchmark_id": "ifeval",
            "display_name": "IFEval",
            "case_count": len(inputs),
            "instruction_count": sum(len(inp.instruction_id_list) for inp in inputs),
            "sample_policy": (
                "greedy_instruction_coverage_%d_sha256_v1" % len(inputs)
                if len(inputs) < len(full_inputs)
                else "full_snapshot_order"
            ),
            "selection_sha256": _selection_digest(inputs),
            "instruction_type_count": len(selected_instruction_types),
            "full_instruction_type_count": len(all_instruction_types),
            "instruction_type_coverage_fraction": round(
                len(selected_instruction_types) / float(len(all_instruction_types)),
                6,
            ) if all_instruction_types else None,
        },
    )


def evaluate(output_dir: str) -> None:
    _ensure_nltk_tokenizers(output_dir)
    filtered_input_path = os.path.join(output_dir, "input_data.jsonl")
    predictions_path = os.path.join(output_dir, "predictions.jsonl")
    inputs = evaluation_lib.read_prompt_list(filtered_input_path)
    prompt_to_response = _read_predictions(predictions_path)

    strict_outputs = [
        evaluation_lib.test_instruction_following_strict(inp, prompt_to_response)
        for inp in inputs
    ]
    loose_outputs = [
        evaluation_lib.test_instruction_following_loose(inp, prompt_to_response)
        for inp in inputs
    ]

    strict_path = os.path.join(output_dir, "strict_results.jsonl")
    loose_path = os.path.join(output_dir, "loose_results.jsonl")
    evaluation_lib.write_outputs(strict_path, strict_outputs)
    evaluation_lib.write_outputs(loose_path, loose_outputs)

    summary = {
        "benchmark_id": "ifeval",
        "display_name": "IFEval",
        "status": "completed",
        "case_count": len(inputs),
        "instruction_count": sum(len(inp.instruction_id_list) for inp in inputs),
        "primary_metric": {
            "name": "prompt_strict_accuracy",
            "value": round(
                sum(output.follow_all_instructions for output in strict_outputs) / float(len(strict_outputs) or 1),
                6,
            ),
        },
        "metrics": {
            "prompt_strict_correct_count": sum(
                output.follow_all_instructions for output in strict_outputs
            ),
            "total_count": len(strict_outputs),
            "prompt_strict_accuracy": round(
                sum(output.follow_all_instructions for output in strict_outputs) / float(len(strict_outputs) or 1),
                6,
            ),
            "instruction_strict_accuracy": round(_instruction_accuracy(strict_outputs), 6),
            "prompt_loose_accuracy": round(
                sum(output.follow_all_instructions for output in loose_outputs) / float(len(loose_outputs) or 1),
                6,
            ),
            "instruction_loose_accuracy": round(_instruction_accuracy(loose_outputs), 6),
        },
        "artifacts": {
            "strict_results_path": strict_path,
            "loose_results_path": loose_path,
        },
    }
    _write_json(os.path.join(output_dir, "summary.json"), summary)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--output-dir", required=True)
    prepare_parser.add_argument("--limit", type=int)

    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--output-dir", required=True)

    args = parser.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    if args.command == "prepare":
        prepare(args.output_dir, limit=args.limit)
        return 0
    evaluate(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
