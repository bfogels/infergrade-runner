#!/usr/bin/env python3
"""Prepare and score InferGrade's pinned LiveCodeBench v6 local reference."""

import argparse
import ast
import hashlib
import json
import os
import re
import resource
import signal
import subprocess
import sys
import time
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


BENCHMARK_ID = "livecodebench_reference_v1"
DEFAULT_DATA_PATH = Path(
    os.environ.get("LIVECODEBENCH_DATA_PATH", "/opt/livecodebench/snapshot.jsonl")
)
DEFAULT_METADATA_PATH = Path(
    os.environ.get(
        "LIVECODEBENCH_METADATA_PATH", "/opt/livecodebench/snapshot_metadata.json"
    )
)
EXPECTED_SELECTION_SHA256 = "caafbae85c53215efdeb6299e22a6fb46aca158d94b124fbf73212b312cd0f5c"
EXPECTED_SNAPSHOT_SHA256 = "ff6f7d15528d110e1bb6846336dcc312feba11395202672eddb3df7c7bbc69e0"
CASE_LIMITS = (6, 18, 48)
MAX_CODE_BYTES = 131072
PER_TEST_TIMEOUT_SECONDS = 6.0
PER_TASK_TIMEOUT_SECONDS = 30.0
CHILD_MEMORY_BYTES = 1536 * 1024 * 1024
MAX_CAPTURE_BYTES = 8 * 1024 * 1024
CODE_FENCE = re.compile(
    r"\A\s*```(?:python|py)?\s*\n(.*?)\n```\s*\Z", re.DOTALL | re.IGNORECASE
)


CHILD_PROGRAM = r'''
import contextlib
import io
import json
import sys
from bisect import *
from collections import *
from copy import *
from functools import *
from heapq import *
from itertools import *
from math import *
from operator import *
from string import *
from typing import *
import bisect, collections, copy, functools, heapq, itertools, math, operator, re

BASE_NAMESPACE = {
    name: value for name, value in globals().items() if not name.startswith("_")
}

class _CappedWriter(io.StringIO):
    def write(self, value):
        if self.tell() + len(str(value)) > int(PAYLOAD["max_capture_bytes"]):
            raise RuntimeError("generated output exceeded capture limit")
        return super().write(value)

PAYLOAD = json.load(sys.stdin)
ORIGINAL_STDOUT = sys.stdout
capture = _CappedWriter()
namespace = dict(BASE_NAMESPACE)
namespace["__name__"] = "__main__" if PAYLOAD["testtype"] == "stdin" else "candidate"
try:
    with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
        if PAYLOAD["testtype"] == "stdin":
            original_stdin = sys.stdin
            sys.stdin = io.StringIO(PAYLOAD["input"])
            try:
                exec(compile(PAYLOAD["code"], "<candidate>", "exec"), namespace)
            finally:
                sys.stdin = original_stdin
            result = capture.getvalue()
        else:
            exec(compile(PAYLOAD["code"], "<candidate>", "exec"), namespace)
            owner = namespace.get("Solution")
            target = owner() if owner is not None else namespace
            method = getattr(target, PAYLOAD["function_name"], None)
            if method is None and isinstance(target, dict):
                method = target.get(PAYLOAD["function_name"])
            if not callable(method):
                raise AttributeError("required function is missing")
            values = PAYLOAD["arguments"]
            result = method(*values)
    serialized_result = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if len(serialized_result.encode("utf-8")) > int(PAYLOAD["max_capture_bytes"]):
        raise RuntimeError("generated result exceeded capture limit")
    envelope = '{"status":"ok","result":' + serialized_result + '}'
except BaseException as exc:
    envelope = json.dumps(
        {"status": "error", "error_type": type(exc).__name__},
        separators=(",", ":"),
    )
ORIGINAL_STDOUT.write(envelope)
'''


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Expected an object in %s" % path)
    return payload


def _read_jsonl(path: Path) -> List[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def _selection_digest(rows: List[dict]) -> str:
    ids = sorted(str(row.get("question_id")) for row in rows)
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


def _verified_snapshot(data_path: Path, metadata_path: Path) -> Tuple[List[dict], dict]:
    rows = _read_jsonl(data_path)
    metadata = _read_json(metadata_path)
    actual_selection = _selection_digest(rows)
    actual_snapshot = _file_sha256(data_path)
    if len(rows) != 48:
        raise ValueError("Expected 48 LiveCodeBench snapshot rows, found %d" % len(rows))
    if actual_selection != EXPECTED_SELECTION_SHA256:
        raise ValueError("LiveCodeBench selected case identity does not match the reviewed snapshot")
    if actual_snapshot != EXPECTED_SNAPSHOT_SHA256:
        raise ValueError("LiveCodeBench snapshot content does not match the reviewed snapshot")
    if metadata.get("selection_sha256") != actual_selection:
        raise ValueError("LiveCodeBench metadata selection identity does not match snapshot rows")
    if metadata.get("snapshot_sha256") != actual_snapshot:
        raise ValueError("LiveCodeBench metadata content identity does not match snapshot bytes")
    return rows, metadata


def _prompt(row: dict) -> str:
    starter = str(row.get("starter_code") or "").rstrip()
    starter_section = (
        "\n\nUse this required interface:\n```python\n%s\n```" % starter
        if starter
        else ""
    )
    return (
        "Solve this programming problem in Python 3 using only the standard library. "
        "Return one complete executable solution and no explanation. A single Python code "
        "fence is accepted.\n\n%s%s"
        % (str(row["question_content"]).strip(), starter_section)
    )


def _public_case(row: dict) -> dict:
    question_id = str(row["question_id"])
    return {
        "case_id": "livecodebench_v6/%s" % question_id,
        "task_id": "livecodebench_v6/%s" % question_id,
        "question_id": question_id,
        "question_title": str(row["question_title"]),
        "platform": str(row["platform"]),
        "difficulty": str(row["difficulty"]),
        "contest_month": str(row["contest_date"])[:7],
        "test_interface": "functional" if row.get("starter_code") else "stdin",
        "prompt": _prompt(row),
    }


def prepare(
    output_dir: str,
    limit: Optional[int] = None,
    data_path: Path = DEFAULT_DATA_PATH,
    metadata_path: Path = DEFAULT_METADATA_PATH,
) -> None:
    if limit is not None and limit not in CASE_LIMITS:
        raise ValueError("LiveCodeBench limit must be one of 6, 18, or 48")
    rows, source_metadata = _verified_snapshot(Path(data_path), Path(metadata_path))
    selected = rows[:limit] if limit else rows
    cases = [_public_case(row) for row in selected]
    root = Path(output_dir)
    _write_jsonl(root / "cases.jsonl", cases)
    _write_json(
        root / "benchmark_metadata.json",
        {
            "benchmark_id": BENCHMARK_ID,
            "display_name": "LiveCodeBench v6 local reference",
            "case_count": len(cases),
            "platform_count": len({case["platform"] for case in cases}),
            "difficulty_count": len({case["difficulty"] for case in cases}),
            "month_count": len({case["contest_month"] for case in cases}),
            "test_interface_counts": {
                interface: len([case for case in cases if case["test_interface"] == interface])
                for interface in ("stdin", "functional")
            },
            "dataset": source_metadata["dataset"],
            "dataset_file": source_metadata["dataset_file"],
            "dataset_revision": source_metadata["dataset_revision"],
            "dataset_sha256": source_metadata["dataset_sha256"],
            "upstream_code_revision": source_metadata["upstream_code_revision"],
            "dataset_license_status": source_metadata["dataset_license_status"],
            "dataset_card_license_value": source_metadata.get(
                "dataset_card_license_value"
            ),
            "dataset_loader_license_notice": source_metadata.get(
                "dataset_loader_license_notice"
            ),
            "snapshot_sha256": source_metadata["snapshot_sha256"],
            "selected_test_count": sum(len(row["tests"]) for row in selected),
            "maximum_test_input_bytes": max(
                len(test["input"].encode("utf-8"))
                for row in selected
                for test in row["tests"]
            ),
            "maximum_test_output_bytes": max(
                len(test["output"].encode("utf-8"))
                for row in selected
                for test in row["tests"]
            ),
            "sample_policy": "platform_difficulty_temporal_balanced_%d_v1" % len(cases),
            "selection_digest_algorithm": "sorted_utf8_newline_sha256_v1",
            "selection_sha256": _selection_digest(selected),
            "scoring_policy": "livecodebench_v6_local_pass_at_1_v1",
            "repetitions": 1,
        },
    )


def _normalized_code(completion: str) -> Tuple[Optional[str], Optional[str]]:
    text = str(completion or "").strip()
    fenced = CODE_FENCE.fullmatch(text)
    if fenced:
        text = fenced.group(1).strip()
    if not text:
        return None, "empty_code"
    if len(text.encode("utf-8")) > MAX_CODE_BYTES:
        return None, "code_too_large"
    if "\x00" in text:
        return None, "nul_byte"
    try:
        ast.parse(text)
    except (SyntaxError, ValueError, MemoryError):
        return None, "invalid_python"
    return text + "\n", None


def _json_values(value: str) -> List[object]:
    decoder = json.JSONDecoder()
    text = str(value)
    cursor = 0
    values = []
    while True:
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor >= len(text):
            return values
        decoded, cursor = decoder.raw_decode(text, cursor)
        values.append(decoded)


def _drop_and_limit_child() -> None:
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)
    resource.setrlimit(resource.RLIMIT_AS, (CHILD_MEMORY_BYTES, CHILD_MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (7, 7))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_CAPTURE_BYTES, MAX_CAPTURE_BYTES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    if hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))


def _kill_process_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        raise RuntimeError(
            "LiveCodeBench root scorer requires CAP_KILL to terminate the unprivileged process group"
        ) from exc


def _run_test(code: str, row: dict, test: dict, timeout: float) -> dict:
    testtype = str(test["testtype"])
    payload = {
        "code": code,
        "testtype": testtype,
        "input": str(test["input"]),
        "max_capture_bytes": MAX_CAPTURE_BYTES,
    }
    if testtype == "functional":
        payload["arguments"] = _json_values(str(test["input"]))
        payload["function_name"] = str(row.get("function_name") or "")
        if not payload["function_name"]:
            return {"status": "sandbox_failure", "error_type": "missing_function_name"}
    process = subprocess.Popen(
        [sys.executable, "-I", "-S", "-c", CHILD_PROGRAM],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"},
        preexec_fn=_drop_and_limit_child,
        start_new_session=True,
    )
    try:
        stdout, _stderr = process.communicate(
            json.dumps(payload, ensure_ascii=False), timeout=max(0.1, timeout)
        )
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        process.communicate()
        return {"status": "timeout"}
    if process.returncode != 0:
        return {"status": "runtime_failure"}
    try:
        envelope = json.loads(stdout)
    except (TypeError, ValueError):
        return {"status": "runtime_failure"}
    if envelope.get("status") != "ok":
        return {
            "status": "runtime_failure",
            "error_type": str(envelope.get("error_type") or "candidate_error"),
        }
    return {"status": "ok", "result": envelope.get("result")}


def _stdin_matches(actual: str, expected: str) -> bool:
    actual_lines = [line.strip() for line in str(actual).strip().splitlines()]
    expected_lines = [line.strip() for line in str(expected).strip().splitlines()]
    if actual_lines == expected_lines:
        return True
    if len(actual_lines) != len(expected_lines):
        return False
    for actual_line, expected_line in zip(actual_lines, expected_lines):
        try:
            if [Decimal(item) for item in actual_line.split()] != [
                Decimal(item) for item in expected_line.split()
            ]:
                return False
        except InvalidOperation:
            return False
    return True


def _test_matches(test: dict, actual) -> bool:
    if str(test["testtype"]) == "stdin":
        return _stdin_matches(str(actual), str(test["output"]))
    try:
        expected = json.loads(str(test["output"]))
    except (TypeError, ValueError):
        return False
    return actual == expected


def _score_code(row: dict, completion: str) -> dict:
    code, error = _normalized_code(completion)
    if error:
        return {
            "passed": False,
            "failure_class": "malformed_output",
            "failure_detail": error,
            "tests_passed": 0,
            "tests_executed": 0,
            "tests_total": len(row["tests"]),
        }
    deadline = time.monotonic() + PER_TASK_TIMEOUT_SECONDS
    passed = 0
    for test in row["tests"]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {
                "passed": False,
                "failure_class": "timeout",
                "tests_passed": passed,
                "tests_executed": passed,
                "tests_total": len(row["tests"]),
            }
        result = _run_test(code or "", row, test, min(PER_TEST_TIMEOUT_SECONDS, remaining))
        if result["status"] != "ok":
            return {
                "passed": False,
                "failure_class": result["status"],
                "tests_passed": passed,
                "tests_executed": passed + 1,
                "tests_total": len(row["tests"]),
            }
        if not _test_matches(test, result.get("result")):
            return {
                "passed": False,
                "failure_class": "test_failed",
                "tests_passed": passed,
                "tests_executed": passed + 1,
                "tests_total": len(row["tests"]),
            }
        passed += 1
    return {
        "passed": True,
        "failure_class": None,
        "tests_passed": passed,
        "tests_executed": passed,
        "tests_total": len(row["tests"]),
    }


def _group_metrics(results: List[dict], field: str) -> dict:
    totals = defaultdict(int)
    passed = defaultdict(int)
    for result in results:
        key = str(result[field])
        totals[key] += 1
        passed[key] += int(bool(result["passed"]))
    return {
        key: {
            "pass_at_1": round(passed[key] / float(total), 6),
            "passed_count": passed[key],
            "total_count": total,
        }
        for key, total in sorted(totals.items())
    }


def evaluate(
    output_dir: str,
    data_path: Path = DEFAULT_DATA_PATH,
    metadata_path: Path = DEFAULT_METADATA_PATH,
) -> None:
    root = Path(output_dir)
    snapshot, _source_metadata = _verified_snapshot(Path(data_path), Path(metadata_path))
    private = {
        "livecodebench_v6/%s" % row["question_id"]: row for row in snapshot
    }
    cases = {str(row["task_id"]): row for row in _read_jsonl(root / "cases.jsonl")}
    predictions = _read_jsonl(root / "predictions.jsonl")
    results = []
    seen = set()
    failure_counts = {
        "malformed_output_count": 0,
        "runtime_failure_count": 0,
        "timeout_count": 0,
        "test_failure_count": 0,
        "sandbox_failure_count": 0,
    }
    for prediction in predictions:
        if str(prediction.get("generation_status") or "completed") != "completed":
            continue
        task_id = str(prediction.get("task_id") or prediction.get("case_id") or "")
        if task_id in seen or task_id not in cases or task_id not in private:
            raise ValueError(
                "Prediction contains an unknown or duplicate LiveCodeBench task: %s"
                % task_id
            )
        seen.add(task_id)
        scored = _score_code(private[task_id], str(prediction.get("completion") or ""))
        failure_class = scored["failure_class"]
        if failure_class:
            key = "%s_count" % failure_class
            if key in failure_counts:
                failure_counts[key] += 1
        case = cases[task_id]
        results.append(
            {
                "case_id": task_id,
                "task_id": task_id,
                "platform": case["platform"],
                "difficulty": case["difficulty"],
                "contest_month": case["contest_month"],
                "test_interface": case["test_interface"],
                "score": 1.0 if scored["passed"] else 0.0,
                "passed": bool(scored["passed"]),
                "state": "scored",
                "error_class": failure_class,
                "tests_passed_before_failure": scored["tests_passed"],
                "tests_executed": scored["tests_executed"],
                "test_count": scored["tests_total"],
            }
        )
    total = len(results)
    passed_count = sum(int(result["passed"]) for result in results)
    pass_at_1 = round(passed_count / float(total), 6) if total else None
    _write_json(
        root / "summary.json",
        {
            "benchmark_id": BENCHMARK_ID,
            "display_name": "LiveCodeBench v6 local reference",
            "status": "completed" if total else "failed",
            "primary_metric": {"name": "pass_at_1", "value": pass_at_1},
            "metrics": {
                "pass_at_1": pass_at_1,
                "passed_count": passed_count,
                "failed_count": total - passed_count,
                "total_count": total,
                "executed_test_count": sum(result["tests_executed"] for result in results),
                "selected_test_count": sum(result["test_count"] for result in results),
                **failure_counts,
            },
            "platform_metrics": _group_metrics(results, "platform"),
            "difficulty_metrics": _group_metrics(results, "difficulty"),
            "month_metrics": _group_metrics(results, "contest_month"),
            "test_interface_metrics": _group_metrics(results, "test_interface"),
            "case_results": results,
            "scoring_policy": "livecodebench_v6_local_pass_at_1_v1",
            "repetitions": 1,
            "sandbox_policy": {
                "policy_id": "livecodebench_generated_python_subprocess_v1",
                "root_supervisor_capabilities": ["SETUID", "SETGID", "KILL"],
                "generated_code_user": "nobody:65534",
                "generated_child_capabilities": "cleared_after_setuid",
                "per_test_timeout_seconds": PER_TEST_TIMEOUT_SECONDS,
                "per_task_timeout_seconds": PER_TASK_TIMEOUT_SECONDS,
                "child_memory_bytes": CHILD_MEMORY_BYTES,
                "child_cpu_limit_seconds": 7,
                "maximum_captured_result_bytes": MAX_CAPTURE_BYTES,
                "hidden_expected_outputs_exposed_to_child": False,
            },
            "claim_boundary": {
                "can_claim": [
                    "pinned LiveCodeBench v6-derived local Python pass@1 reference"
                ],
                "cannot_claim": [
                    "official LiveCodeBench leaderboard score",
                    "LiveCodeBench pass@10 or multi-sample score",
                    "SWE-bench or repository-edit capability",
                    "general software-engineering capability",
                    "contamination-free evidence for models trained after April 2025",
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
    prepare_parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    prepare_parser.add_argument("--metadata-path", type=Path, default=DEFAULT_METADATA_PATH)
    evaluate_parser = commands.add_parser("evaluate")
    evaluate_parser.add_argument("--output-dir", required=True)
    evaluate_parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    evaluate_parser.add_argument("--metadata-path", type=Path, default=DEFAULT_METADATA_PATH)
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
        evaluate(
            args.output_dir,
            data_path=args.data_path,
            metadata_path=args.metadata_path,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
