#!/usr/bin/env python3
"""Build a deterministic, hash-verified BFCL V4 single-turn snapshot."""

from __future__ import annotations

import hashlib
import json
import os
import ssl
from pathlib import Path
from urllib.request import Request, urlopen


UPSTREAM_REVISION = "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
UPSTREAM_REPOSITORY_ROOT = (
    "https://raw.githubusercontent.com/ShishirPatil/gorilla/"
    + UPSTREAM_REVISION
)
UPSTREAM_ROOT = UPSTREAM_REPOSITORY_ROOT + "/berkeley-function-call-leaderboard/bfcl_eval/data"
UPSTREAM_LICENSE_SHA256 = "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"
CASES_PER_CATEGORY = 10
CATEGORIES = (
    "simple_python",
    "multiple",
    "parallel",
    "parallel_multiple",
    "irrelevance",
    "live_simple",
    "live_multiple",
    "live_parallel",
    "live_parallel_multiple",
    "live_irrelevance",
    "live_relevance",
)
RELEVANCE_CATEGORIES = {"irrelevance", "live_irrelevance", "live_relevance"}
FILE_SHA256 = {
    "BFCL_v4_simple_python.json": "82dd63ba502eb2520c6b5d1d9a5c4b590e03ff261565175561f6228a367d1991",
    "BFCL_v4_multiple.json": "aef168155ebd74b7ac2401198b201343bc7d16d7a3d7e0d4e6d8ee82c6969b2a",
    "BFCL_v4_parallel.json": "19f51a82eff42e5d62541aa500115a056eb78f437c2ba1f10415fd7c8e5dda84",
    "BFCL_v4_parallel_multiple.json": "8863ea8433239f55c5f016154cf0830853c89f693c6ea270396a2fa121960579",
    "BFCL_v4_irrelevance.json": "2b6ed4c2e992cdcf5f1678a701851f944bef7550ee026ed1ddb89efed5be01a6",
    "BFCL_v4_live_simple.json": "1af2ac87dca47556db7b7e37e51e28b459a38b594e3c7b3c792b4903598ca0c4",
    "BFCL_v4_live_multiple.json": "fd8ccfad4d911420d0e3341dbe2fff77d1d341da934248b9bb2bda24ab3a10c8",
    "BFCL_v4_live_parallel.json": "6c26e9fdc3350cf596e6d1ea9c179cbff834761bccf562f4141ed29a839ca421",
    "BFCL_v4_live_parallel_multiple.json": "21d4b9319c1faac431e22757b367ea28917fe467364c3a4b17f16ec06d4f6e79",
    "BFCL_v4_live_irrelevance.json": "6559fda2beaceb609a2cd2e504c65b4a56cb448e1ef88fddfd199e163d163349",
    "BFCL_v4_live_relevance.json": "e03f9e241657a137cba48a89ee12f47bf3fcb7e4f6274263e9c699a0c974203a",
    "possible_answer/BFCL_v4_simple_python.json": "90cd5bc653690ee8e459b5b3f3fc9458606f7f3fcbf795bb51b7dc581f8c86dc",
    "possible_answer/BFCL_v4_multiple.json": "244e00ce9395df948bcafc7bee64e8f9c87ef70887587d83cae45b13699f3047",
    "possible_answer/BFCL_v4_parallel.json": "8a6aa19c1adddc6a5a2f7e40f9dbf30cc7e95815e7b830c90589ab318229e0f0",
    "possible_answer/BFCL_v4_parallel_multiple.json": "5ebf24f458c1f16300c05505d83d6f0a1b68b79be273a033febd0d4f840507e3",
    "possible_answer/BFCL_v4_live_simple.json": "fec9cfa9744a936f9126981e85a2023da1e63e273eafebc81923a1162fad70ce",
    "possible_answer/BFCL_v4_live_multiple.json": "97e90d59c5bd76c55a2920ce93e5566e9046307d3f558578f085f9d3a56c3084",
    "possible_answer/BFCL_v4_live_parallel.json": "8a9f189ff0e832ebbbbdade1fd95a7dbcc67406e9177df3f0aad76f59ab00350",
    "possible_answer/BFCL_v4_live_parallel_multiple.json": "f5b5f360556c5feb51db46fb9f56ee4b304f4b45b161599bbb14161c98a2873f",
}


def _ssl_context():
    default_paths = ssl.get_default_verify_paths()
    system_ca = Path("/etc/ssl/cert.pem")
    context = None
    if system_ca.is_file() and (not default_paths.cafile or not Path(default_paths.cafile).is_file()):
        context = ssl.create_default_context(cafile=str(system_ca))
    return context


def _download(relative_path: str) -> bytes:
    request = Request(UPSTREAM_ROOT + "/" + relative_path, headers={"User-Agent": "infergrade-bfcl-snapshot"})
    with urlopen(request, timeout=60, context=_ssl_context()) as response:
        payload = response.read()
    actual = hashlib.sha256(payload).hexdigest()
    expected = FILE_SHA256[relative_path]
    if actual != expected:
        raise ValueError("BFCL source digest mismatch for %s: expected %s, got %s" % (relative_path, expected, actual))
    return payload


def _download_upstream_license() -> bytes:
    request = Request(UPSTREAM_REPOSITORY_ROOT + "/LICENSE", headers={"User-Agent": "infergrade-bfcl-snapshot"})
    with urlopen(request, timeout=60, context=_ssl_context()) as response:
        payload = response.read()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != UPSTREAM_LICENSE_SHA256:
        raise ValueError(
            "BFCL upstream license digest mismatch: expected %s, got %s"
            % (UPSTREAM_LICENSE_SHA256, actual)
        )
    return payload


def _jsonl(payload: bytes) -> list[dict]:
    return [json.loads(line) for line in payload.decode("utf-8").splitlines() if line.strip()]


def _rank(category: str, row: dict) -> str:
    return hashlib.sha256(("bfcl_local_reference_v1\0" + category + "\0" + str(row["id"])).encode("utf-8")).hexdigest()


def build(output_dir: Path) -> None:
    requested_revision = os.environ.get("BFCL_UPSTREAM_REVISION", UPSTREAM_REVISION)
    if requested_revision != UPSTREAM_REVISION:
        raise ValueError(
            "BFCL_UPSTREAM_REVISION must match the hash-verified source manifest: expected %s, got %s"
            % (UPSTREAM_REVISION, requested_revision)
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "LICENSE.apache2").write_bytes(_download_upstream_license())
    snapshot = []
    selected_ids = {}
    for category in CATEGORIES:
        prompt_path = "BFCL_v4_%s.json" % category
        prompts = _jsonl(_download(prompt_path))
        answers = {}
        if category not in RELEVANCE_CATEGORIES:
            answer_path = "possible_answer/BFCL_v4_%s.json" % category
            answers = {str(row["id"]): row["ground_truth"] for row in _jsonl(_download(answer_path))}
        selected = sorted(prompts, key=lambda row: _rank(category, row))[:CASES_PER_CATEGORY]
        if len(selected) != CASES_PER_CATEGORY:
            raise ValueError("BFCL category %s has only %d selectable rows" % (category, len(selected)))
        selected_ids[category] = [str(row["id"]) for row in selected]
        for row in selected:
            row_id = str(row["id"])
            if category not in RELEVANCE_CATEGORIES and row_id not in answers:
                raise ValueError("BFCL answer missing for %s" % row_id)
            snapshot.append(
                {
                    "id": row_id,
                    "category": category,
                    "question": row["question"],
                    "function": row["function"],
                    "ground_truth": answers.get(row_id),
                }
            )

    snapshot_path = output_dir / "snapshot.jsonl"
    with snapshot_path.open("w", encoding="utf-8") as handle:
        for row in snapshot:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    snapshot_sha256 = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    metadata = {
        "benchmark_id": "bfcl_local_reference_v1",
        "upstream": "https://github.com/ShishirPatil/gorilla",
        "upstream_revision": UPSTREAM_REVISION,
        "upstream_version": "BFCL_v4",
        "upstream_license": "Apache-2.0",
        "case_count": len(snapshot),
        "cases_per_category": CASES_PER_CATEGORY,
        "categories": list(CATEGORIES),
        "selection_policy": "sha256_rank_per_category_v1",
        "selected_ids": selected_ids,
        "source_file_sha256": FILE_SHA256,
        "snapshot_sha256": snapshot_sha256,
    }
    (output_dir / "snapshot_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    build(Path(os.environ.get("BFCL_OUTPUT_DIR", "/opt/bfcl")))
