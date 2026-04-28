import argparse
import json
import os

from evalplus.data import get_human_eval_plus, get_mbpp_plus, write_jsonl
from evalplus.data.mbpp import mbpp_serialize_inputs
from evalplus.evaluate import evaluate as evalplus_evaluate


def _write_json(path: str, payload) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _read_jsonl(path: str):
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _dataset_problems(dataset: str):
    if dataset == "humaneval":
        return get_human_eval_plus()
    if dataset == "mbpp":
        return get_mbpp_plus()
    raise ValueError("Unsupported EvalPlus dataset: %s" % dataset)


def _jsonl_ready_task(dataset: str, task: dict) -> dict:
    normalized = dict(task)
    if dataset == "mbpp":
        normalized["base_input"] = mbpp_serialize_inputs(task["task_id"], task["base_input"])
        normalized["plus_input"] = mbpp_serialize_inputs(task["task_id"], task["plus_input"])
    json.dumps(normalized)
    return normalized


def prepare(dataset: str, output_dir: str, limit: int = None) -> None:
    problems = _dataset_problems(dataset)
    items = list(problems.items())
    if limit:
        items = items[:limit]
    selected_tasks = [_jsonl_ready_task(dataset, problem) for _task_id, problem in items]
    override_path = os.path.join(output_dir, "%s_override.jsonl" % dataset)
    write_jsonl(override_path, selected_tasks, drop_builtin=False)
    write_jsonl(
        os.path.join(output_dir, "cases.jsonl"),
        [
            {
                "case_id": task["task_id"],
                "task_id": task["task_id"],
                "prompt": task["prompt"],
                "entry_point": task["entry_point"],
                "dataset": dataset,
            }
            for task in selected_tasks
        ],
        drop_builtin=False,
    )
    _write_json(
        os.path.join(output_dir, "benchmark_metadata.json"),
        {
            "benchmark_id": "evalplus_%s" % dataset,
            "display_name": "EvalPlus %s" % dataset,
            "dataset": dataset,
            "case_count": len(selected_tasks),
            "override_path": override_path,
        },
    )


def evaluate(dataset: str, output_dir: str) -> None:
    override_path = os.path.join(output_dir, "%s_override.jsonl" % dataset)
    predictions_path = os.path.join(output_dir, "predictions.jsonl")
    samples_path = os.path.join(output_dir, "samples.jsonl")
    results_path = os.path.join(output_dir, "eval_results.json")
    summary_path = os.path.join(output_dir, "summary.json")

    predictions = _read_jsonl(predictions_path)
    write_jsonl(
        samples_path,
        [
            {
                "task_id": row["task_id"],
                "completion": row.get("completion", ""),
            }
            for row in predictions
        ],
        drop_builtin=False,
    )

    if dataset == "humaneval":
        os.environ["HUMANEVAL_OVERRIDE_PATH"] = override_path
    elif dataset == "mbpp":
        os.environ["MBPP_OVERRIDE_PATH"] = override_path

    evalplus_evaluate(
        dataset=dataset,
        samples=samples_path,
        output_file=results_path,
        parallel=max(1, os.cpu_count() or 1),
        i_just_wanna_run=True,
    )
    results = json.load(open(results_path, "r", encoding="utf-8"))
    summary = {
        "benchmark_id": "evalplus_%s" % dataset,
        "display_name": "EvalPlus %s" % dataset,
        "status": "completed",
        "dataset": dataset,
        "case_count": len(results.get("eval", {})),
        "primary_metric": {
            "name": "pass_at_1_plus",
            "value": round(
                float(results.get("pass_at_k", {}).get("plus", {}).get("pass@1")
                      or results.get("pass_at_k", {}).get("base", {}).get("pass@1")
                      or 0.0),
                6,
            ),
        },
        "metrics": {
            "pass_at_1_base": round(float(results.get("pass_at_k", {}).get("base", {}).get("pass@1") or 0.0), 6),
            "pass_at_1_plus": round(float(results.get("pass_at_k", {}).get("plus", {}).get("pass@1") or 0.0), 6),
        },
        "artifacts": {
            "results_path": results_path,
            "samples_path": samples_path,
            "override_path": override_path,
        },
    }
    _write_json(summary_path, summary)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--dataset", required=True, choices=("humaneval", "mbpp"))
    prepare_parser.add_argument("--output-dir", required=True)
    prepare_parser.add_argument("--limit", type=int)

    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--dataset", required=True, choices=("humaneval", "mbpp"))
    evaluate_parser.add_argument("--output-dir", required=True)

    args = parser.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    if args.command == "prepare":
        prepare(args.dataset, args.output_dir, limit=args.limit)
        return 0
    evaluate(args.dataset, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
