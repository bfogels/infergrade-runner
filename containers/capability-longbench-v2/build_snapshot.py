#!/usr/bin/env python3
"""Build a hash-verified, locally feasible LongBench v2 short-context snapshot."""

import hashlib
import json
import os
import tempfile
import urllib.request
from collections import defaultdict
from pathlib import Path


DATASET_REVISION = "2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9"
DATASET_SHA256 = "15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2"
DATASET_URL = (
    "https://huggingface.co/datasets/zai-org/LongBench-v2/resolve/"
    + DATASET_REVISION
    + "/data.json"
)
BENCHMARK_ID = "longbench_v2_local_reference_v1"
SELECTION_SHA256 = "1a5f48517a31dc80083700955b92d9524cba2d863448209956e2cf1b423079a3"
SNAPSHOT_SHA256 = "677ac38dc799b0bbe61816f1d0c245bb93f01dd535a71ecfde6fa619d3eb86db"
DOMAINS = (
    "Code Repository Understanding",
    "Long In-context Learning",
    "Long Structured Data Understanding",
    "Long-dialogue History Understanding",
    "Multi-Document QA",
    "Single-Document QA",
)
DIFFICULTIES = ("easy", "hard")
ROWS_PER_STRATUM = 2
MAX_ESTIMATED_CONTEXT_TOKENS = 131072


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
        headers={"User-Agent": "infergrade-longbench-v2-snapshot"},
    )
    with urllib.request.urlopen(request, timeout=180) as response, path.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            handle.write(chunk)
    if digest.hexdigest() != DATASET_SHA256:
        raise ValueError(
            "LongBench v2 dataset SHA-256 mismatch: expected %s, got %s"
            % (DATASET_SHA256, digest.hexdigest())
        )


def _json_array_rows(path: Path):
    decoder = json.JSONDecoder()
    buffer = ""
    started = False
    with path.open(encoding="utf-8") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            buffer += chunk
            cursor = 0
            if not started:
                cursor = len(buffer) - len(buffer.lstrip())
                if cursor >= len(buffer):
                    continue
                if buffer[cursor] != "[":
                    raise ValueError("LongBench v2 source must be a JSON array")
                cursor += 1
                started = True
            while True:
                while cursor < len(buffer) and buffer[cursor] in " \t\r\n,":
                    cursor += 1
                if cursor < len(buffer) and buffer[cursor] == "]":
                    return
                try:
                    row, end = decoder.raw_decode(buffer, cursor)
                except json.JSONDecodeError:
                    buffer = buffer[cursor:]
                    break
                if not isinstance(row, dict):
                    raise ValueError("LongBench v2 source rows must be objects")
                yield row
                cursor = end
            if len(buffer) > 32 * 1024 * 1024:
                raise ValueError("LongBench v2 source contains an unexpectedly large row")
    raise ValueError("LongBench v2 source ended before its JSON array closed")


def _rank(row: dict) -> str:
    identity = "%s\0%s\0%s\0%s" % (
        BENCHMARK_ID,
        row.get("domain"),
        row.get("difficulty"),
        row.get("_id"),
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _estimated_context_tokens(row: dict) -> int:
    context = str(row.get("context") or "")
    return max(
        int(len(context.split()) * 1.5),
        int(len(context) / 3.0),
    ) + 1024


def _selection_order(grouped: dict) -> list:
    ordered = []
    for rank_index in range(ROWS_PER_STRATUM):
        for difficulty_offset in range(2):
            for domain_index, domain in enumerate(DOMAINS):
                difficulty = DIFFICULTIES[(domain_index + difficulty_offset) % 2]
                bucket = grouped[(domain, difficulty)]
                if rank_index < len(bucket):
                    ordered.append(bucket[rank_index])
    return ordered


def build(output_dir: Path, source_path: Path = None) -> None:
    requested_revision = os.environ.get(
        "LONGBENCH_V2_DATASET_REVISION", DATASET_REVISION
    )
    requested_sha256 = os.environ.get(
        "LONGBENCH_V2_DATASET_SHA256", DATASET_SHA256
    )
    if requested_revision != DATASET_REVISION or requested_sha256 != DATASET_SHA256:
        raise ValueError("LongBench v2 build arguments must match the reviewed source identity")
    output_dir.mkdir(parents=True, exist_ok=True)
    owned_source = source_path is None
    if owned_source:
        temporary = tempfile.NamedTemporaryFile(
            prefix="longbench-v2-", suffix=".json", delete=False
        )
        temporary.close()
        source_path = Path(temporary.name)
        _download(source_path)
    else:
        actual = _file_sha256(source_path)
        if actual != DATASET_SHA256:
            raise ValueError("LongBench v2 local source SHA-256 mismatch: %s" % actual)
    try:
        grouped = defaultdict(list)
        source_count = 0
        short_count = 0
        context_fit_count = 0
        for row in _json_array_rows(source_path):
            source_count += 1
            if row.get("length") != "short":
                continue
            short_count += 1
            if _estimated_context_tokens(row) > MAX_ESTIMATED_CONTEXT_TOKENS:
                continue
            context_fit_count += 1
            key = (str(row.get("domain")), str(row.get("difficulty")))
            grouped[key].append(row)
        if source_count != 503 or short_count != 180:
            raise ValueError(
                "Unexpected LongBench v2 source counts: %d total, %d short"
                % (source_count, short_count)
            )
        for key in ((domain, difficulty) for domain in DOMAINS for difficulty in DIFFICULTIES):
            grouped[key].sort(key=_rank)
            if not grouped[key]:
                raise ValueError("LongBench v2 stratum %r is underfilled" % (key,))
            grouped[key] = grouped[key][:ROWS_PER_STRATUM]
        selected = _selection_order(grouped)
        snapshot_path = output_dir / "snapshot.jsonl"
        selected_ids = []
        with snapshot_path.open("w", encoding="utf-8") as handle:
            for row in selected:
                selected_ids.append(str(row["_id"]))
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        metadata = {
            "benchmark_id": BENCHMARK_ID,
            "dataset": "zai-org/LongBench-v2",
            "dataset_revision": DATASET_REVISION,
            "dataset_sha256": DATASET_SHA256,
            "dataset_license": "Apache-2.0",
            "source_case_count": source_count,
            "source_short_case_count": short_count,
            "source_context_fit_case_count": context_fit_count,
            "maximum_estimated_context_tokens": MAX_ESTIMATED_CONTEXT_TOKENS,
            "case_count": len(selected),
            "domain_count": len(DOMAINS),
            "difficulty_count": len(DIFFICULTIES),
            "length_scope": "short",
            "selection_policy": "short_domain_difficulty_hash_rank_balanced_tier_blocks_v1",
            "selected_ids": selected_ids,
            "selection_sha256": hashlib.sha256(
                "\n".join(sorted(selected_ids)).encode("utf-8")
            ).hexdigest(),
            "snapshot_sha256": _file_sha256(snapshot_path),
        }
        if metadata["selection_sha256"] != SELECTION_SHA256:
            raise ValueError(
                "LongBench v2 selected case identity drifted: %s"
                % metadata["selection_sha256"]
            )
        if metadata["snapshot_sha256"] != SNAPSHOT_SHA256:
            raise ValueError(
                "LongBench v2 snapshot content drifted: %s"
                % metadata["snapshot_sha256"]
            )
        (output_dir / "snapshot_metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    finally:
        if owned_source:
            source_path.unlink(missing_ok=True)


if __name__ == "__main__":
    build(Path(os.environ.get("LONGBENCH_V2_OUTPUT_DIR", "/opt/longbench-v2")))
