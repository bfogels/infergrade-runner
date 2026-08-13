#!/usr/bin/env python3
"""Build InferGrade's pinned LiveCodeBench v6 local-reference snapshot."""

import base64
import hashlib
import io
import json
import os
import pickle
import tempfile
import urllib.request
import zlib
from collections import defaultdict
from pathlib import Path


BENCHMARK_ID = "livecodebench_reference_v1"
DATASET = "livecodebench/code_generation_lite"
DATASET_REVISION = "0fe84c3912ea0c4d4a78037083943e8f0c4dd505"
DATASET_FILE = "test6.jsonl"
DATASET_URL = (
    "https://huggingface.co/datasets/"
    + DATASET
    + "/resolve/"
    + DATASET_REVISION
    + "/"
    + DATASET_FILE
)
DATASET_SHA256 = "bb4c364f71921c4495a6ad15abe1a927350b720009f4933e2e71f8af0f6fd1f5"
UPSTREAM_CODE_REVISION = "28fef95ea8c9f7a547c8329f2cd3d32b92c1fa24"
SELECTION_SHA256 = "caafbae85c53215efdeb6299e22a6fb46aca158d94b124fbf73212b312cd0f5c"
# Exact reviewed digest of the normalized 48-task snapshot.
SNAPSHOT_SHA256 = "ff6f7d15528d110e1bb6846336dcc312feba11395202672eddb3df7c7bbc69e0"
PLATFORMS = ("atcoder", "leetcode")
DIFFICULTIES = ("easy", "medium", "hard")
ROWS_PER_STRATUM = 8
SOURCE_CASE_COUNT = 175


class _PrimitiveOnlyUnpickler(pickle.Unpickler):
    """Reject every pickle global; the pinned source encodes a primitive JSON string."""

    def find_class(self, module, name):
        raise pickle.UnpicklingError(
            "LiveCodeBench private-test pickle referenced forbidden global %s.%s"
            % (module, name)
        )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def _download(path: Path) -> None:
    digest = hashlib.sha256()
    request = urllib.request.Request(
        DATASET_URL,
        headers={"User-Agent": "infergrade-livecodebench-snapshot"},
    )
    with urllib.request.urlopen(request, timeout=300) as response, path.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            handle.write(chunk)
    if digest.hexdigest() != DATASET_SHA256:
        raise ValueError(
            "LiveCodeBench dataset SHA-256 mismatch: expected %s, got %s"
            % (DATASET_SHA256, digest.hexdigest())
        )


def _source_rows(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(
                    "LiveCodeBench source row %d must be an object" % line_number
                )
            yield row


def _private_tests(encoded: str) -> list:
    try:
        compressed = base64.b64decode(str(encoded), validate=True)
        pickled = zlib.decompress(compressed)
        decoded = _PrimitiveOnlyUnpickler(io.BytesIO(pickled)).load()
        tests = json.loads(decoded)
    except (ValueError, TypeError, zlib.error, pickle.UnpicklingError) as exc:
        raise ValueError("LiveCodeBench private tests could not be decoded safely") from exc
    if not isinstance(decoded, str) or not isinstance(tests, list):
        raise ValueError("LiveCodeBench private tests must decode to a JSON list string")
    return tests


def _public_tests(encoded: str) -> list:
    tests = json.loads(str(encoded))
    if not isinstance(tests, list):
        raise ValueError("LiveCodeBench public tests must be a JSON list")
    return tests


def _validated_tests(row: dict) -> list:
    tests = _public_tests(row.get("public_test_cases")) + _private_tests(
        row.get("private_test_cases")
    )
    if not tests:
        raise ValueError("LiveCodeBench task %s has no tests" % row.get("question_id"))
    expected_type = "functional" if str(row.get("starter_code") or "").strip() else "stdin"
    for test in tests:
        if not isinstance(test, dict) or not {"input", "output", "testtype"}.issubset(test):
            raise ValueError("LiveCodeBench task contains a malformed test record")
        if str(test.get("testtype")) != expected_type:
            raise ValueError(
                "LiveCodeBench task %s mixes incompatible test types"
                % row.get("question_id")
            )
        if not isinstance(test.get("input"), str) or not isinstance(test.get("output"), str):
            raise ValueError("LiveCodeBench test inputs and outputs must be strings")
    return tests


def _month(row: dict) -> str:
    value = str(row.get("contest_date") or "")
    if len(value) < 7:
        raise ValueError("LiveCodeBench task has an invalid contest date")
    return value[:7]


def _rank(row: dict) -> str:
    identity = "%s\0%s\0%s\0%s" % (
        BENCHMARK_ID,
        row.get("platform"),
        row.get("difficulty"),
        row.get("question_id"),
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _temporally_balanced_bucket(rows: list) -> list:
    by_month = defaultdict(list)
    for row in rows:
        by_month[_month(row)].append(row)
    for month_rows in by_month.values():
        month_rows.sort(key=_rank)
    months = sorted(by_month, reverse=True)
    selected = []
    while len(selected) < ROWS_PER_STRATUM:
        progressed = False
        for month in months:
            if by_month[month]:
                selected.append(by_month[month].pop(0))
                progressed = True
                if len(selected) == ROWS_PER_STRATUM:
                    break
        if not progressed:
            break
    if len(selected) != ROWS_PER_STRATUM:
        raise ValueError("LiveCodeBench platform/difficulty stratum is underfilled")
    return selected


def _selection_order(rows: list) -> list:
    grouped = defaultdict(list)
    for row in rows:
        key = (str(row.get("platform")), str(row.get("difficulty")))
        if key not in {
            (platform, difficulty)
            for platform in PLATFORMS
            for difficulty in DIFFICULTIES
        }:
            raise ValueError("Unexpected LiveCodeBench stratum %r" % (key,))
        grouped[key].append(row)
    buckets = {
        key: _temporally_balanced_bucket(grouped[key])
        for key in (
            (platform, difficulty)
            for platform in PLATFORMS
            for difficulty in DIFFICULTIES
        )
    }
    return [
        buckets[(platform, difficulty)][rank_index]
        for rank_index in range(ROWS_PER_STRATUM)
        for platform in PLATFORMS
        for difficulty in DIFFICULTIES
    ]


def _normalized_row(row: dict) -> dict:
    metadata = row.get("metadata") or "{}"
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    if not isinstance(metadata, dict):
        raise ValueError("LiveCodeBench task metadata must be an object")
    return {
        "question_id": str(row["question_id"]),
        "question_title": str(row["question_title"]),
        "question_content": str(row["question_content"]),
        "platform": str(row["platform"]),
        "contest_id": str(row["contest_id"]),
        "contest_date": str(row["contest_date"]),
        "difficulty": str(row["difficulty"]),
        "starter_code": str(row.get("starter_code") or ""),
        "function_name": metadata.get("func_name"),
        "tests": _validated_tests(row),
    }


def build(output_dir: Path, source_path: Path = None) -> None:
    requested_revision = os.environ.get(
        "LIVECODEBENCH_DATASET_REVISION", DATASET_REVISION
    )
    requested_sha256 = os.environ.get(
        "LIVECODEBENCH_DATASET_SHA256", DATASET_SHA256
    )
    if requested_revision != DATASET_REVISION or requested_sha256 != DATASET_SHA256:
        raise ValueError("LiveCodeBench build arguments must match the reviewed source identity")
    output_dir.mkdir(parents=True, exist_ok=True)
    owned_source = source_path is None
    if owned_source:
        temporary = tempfile.NamedTemporaryFile(
            prefix="livecodebench-v6-", suffix=".jsonl", delete=False
        )
        temporary.close()
        source_path = Path(temporary.name)
        _download(source_path)
    else:
        actual = _file_sha256(source_path)
        if actual != DATASET_SHA256:
            raise ValueError("LiveCodeBench local source SHA-256 mismatch: %s" % actual)
    try:
        rows = list(_source_rows(source_path))
        if len(rows) != SOURCE_CASE_COUNT:
            raise ValueError(
                "Expected %d LiveCodeBench v6 rows, found %d"
                % (SOURCE_CASE_COUNT, len(rows))
            )
        selected = _selection_order(rows)
        selected_ids = [str(row["question_id"]) for row in selected]
        selection_sha256 = hashlib.sha256(
            "\n".join(sorted(selected_ids)).encode("utf-8")
        ).hexdigest()
        if selection_sha256 != SELECTION_SHA256:
            raise ValueError(
                "LiveCodeBench selected case identity drifted: %s" % selection_sha256
            )
        snapshot_path = output_dir / "snapshot.jsonl"
        selected_test_count = 0
        maximum_test_input_bytes = 0
        maximum_test_output_bytes = 0
        with snapshot_path.open("w", encoding="utf-8") as handle:
            for row in selected:
                normalized = _normalized_row(row)
                selected_test_count += len(normalized["tests"])
                maximum_test_input_bytes = max(
                    maximum_test_input_bytes,
                    *(len(test["input"].encode("utf-8")) for test in normalized["tests"]),
                )
                maximum_test_output_bytes = max(
                    maximum_test_output_bytes,
                    *(len(test["output"].encode("utf-8")) for test in normalized["tests"]),
                )
                handle.write(
                    json.dumps(
                        normalized,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    + "\n"
                )
        snapshot_sha256 = _file_sha256(snapshot_path)
        if snapshot_sha256 != SNAPSHOT_SHA256:
            raise ValueError(
                "LiveCodeBench snapshot content drifted: %s" % snapshot_sha256
            )
        snapshot_path.chmod(0o600)
        metadata = {
            "benchmark_id": BENCHMARK_ID,
            "dataset": DATASET,
            "dataset_file": DATASET_FILE,
            "dataset_revision": DATASET_REVISION,
            "dataset_sha256": DATASET_SHA256,
            "upstream_code_revision": UPSTREAM_CODE_REVISION,
            "dataset_license_status": "blocked_pending_upstream_metadata_review",
            "dataset_card_license_value": "cc",
            "dataset_loader_license_notice": "MIT",
            "source_case_count": len(rows),
            "case_count": len(selected),
            "selected_test_count": selected_test_count,
            "maximum_test_input_bytes": maximum_test_input_bytes,
            "maximum_test_output_bytes": maximum_test_output_bytes,
            "platforms": list(PLATFORMS),
            "difficulties": list(DIFFICULTIES),
            "month_count": len({_month(row) for row in selected}),
            "selection_policy": "platform_difficulty_month_round_robin_hash_rank_tier_blocks_v1",
            "selected_ids": selected_ids,
            "selection_sha256": selection_sha256,
            "snapshot_sha256": snapshot_sha256,
        }
        metadata_path = output_dir / "snapshot_metadata.json"
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        metadata_path.chmod(0o600)
    finally:
        if owned_source:
            source_path.unlink(missing_ok=True)


if __name__ == "__main__":
    build(Path(os.environ.get("LIVECODEBENCH_OUTPUT_DIR", "/opt/livecodebench")))
