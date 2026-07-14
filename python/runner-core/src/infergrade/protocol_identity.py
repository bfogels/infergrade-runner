"""Validation helpers for exact capability benchmark protocol identity."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

from infergrade.utils import stable_hash


BENCHMARK_PROTOCOL_IDENTITY_VERSION = "benchmark_protocol_identity_v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256.fullmatch(value))


def _validate_check_identity(benchmark_id: str, identity: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if identity.get("identity_version") != BENCHMARK_PROTOCOL_IDENTITY_VERSION:
        errors.append("%s: unsupported or missing identity_version" % benchmark_id)
    if identity.get("benchmark_id") != benchmark_id:
        errors.append("%s: protocol identity benchmark_id does not match result key" % benchmark_id)
    if not str(identity.get("registry_version") or "").strip():
        errors.append("%s: missing registry_version" % benchmark_id)
    for field_name in (
        "input_identity_sha256",
        "scoring_identity_sha256",
        "generation_identity_sha256",
        "fingerprint_sha256",
    ):
        if not _is_sha256(identity.get(field_name)):
            errors.append("%s: %s must be a lowercase SHA-256" % (benchmark_id, field_name))
    fingerprint = identity.get("fingerprint_sha256")
    canonical_identity = dict(identity)
    canonical_identity.pop("fingerprint_sha256", None)
    if _is_sha256(fingerprint) and fingerprint != stable_hash(canonical_identity, length=64):
        errors.append("%s: fingerprint_sha256 does not match the protocol identity payload" % benchmark_id)
    return errors


def validate_capability_protocol_identity(
    capability: Dict[str, Any], *, require_complete_coverage: bool = True
) -> Dict[str, Any]:
    """Validate exact per-check and aggregate identity for one capability result."""

    errors: List[str] = []
    coverage = capability.get("benchmark_coverage")
    results = capability.get("benchmark_results")
    aggregate = capability.get("benchmark_protocol_identity")
    if not isinstance(coverage, dict):
        errors.append("missing benchmark_coverage")
        coverage = {}
    if not isinstance(results, dict):
        errors.append("missing benchmark_results")
        results = {}
    if not isinstance(aggregate, dict):
        errors.append("missing benchmark_protocol_identity")
        aggregate = {}

    scored_ids = coverage.get("scored_benchmark_ids")
    if not isinstance(scored_ids, list) or not scored_ids:
        errors.append("benchmark_coverage.scored_benchmark_ids must be a non-empty list")
        scored_ids = []
    normalized_scored_ids: List[str] = []
    for item in scored_ids:
        benchmark_id = str(item or "").strip()
        if not benchmark_id:
            errors.append("benchmark_coverage.scored_benchmark_ids contains an empty id")
        elif benchmark_id in normalized_scored_ids:
            errors.append("benchmark_coverage.scored_benchmark_ids contains duplicate %s" % benchmark_id)
        else:
            normalized_scored_ids.append(benchmark_id)

    planned_ids = coverage.get("planned_benchmark_ids")
    if require_complete_coverage:
        if not isinstance(planned_ids, list) or not planned_ids:
            errors.append("benchmark_coverage.planned_benchmark_ids must be a non-empty list")
        else:
            normalized_planned_ids = [str(item or "").strip() for item in planned_ids]
            if (
                any(not item for item in normalized_planned_ids)
                or set(normalized_planned_ids) != set(normalized_scored_ids)
                or len(normalized_planned_ids) != len(normalized_scored_ids)
            ):
                errors.append("benchmark coverage must be complete: planned and scored benchmark ids differ")
        if coverage.get("coverage_state") != "complete":
            errors.append("benchmark_coverage.coverage_state must be complete")

    check_fingerprints: Dict[str, str] = {}
    for benchmark_id in normalized_scored_ids:
        benchmark_result = results.get(benchmark_id)
        if not isinstance(benchmark_result, dict):
            errors.append("%s: scored benchmark result is missing" % benchmark_id)
            continue
        if benchmark_result.get("status") != "completed":
            errors.append("%s: scored benchmark status must be completed" % benchmark_id)
        primary_metric = benchmark_result.get("primary_metric")
        if not isinstance(primary_metric, dict) or not isinstance(primary_metric.get("value"), (int, float)):
            errors.append("%s: scored benchmark primary_metric.value must be numeric" % benchmark_id)
        identity = benchmark_result.get("protocol_identity")
        if not isinstance(identity, dict):
            errors.append("%s: scored benchmark protocol_identity is missing" % benchmark_id)
            continue
        errors.extend(_validate_check_identity(benchmark_id, identity))
        fingerprint = identity.get("fingerprint_sha256")
        if _is_sha256(fingerprint):
            check_fingerprints[benchmark_id] = fingerprint

    expected_check_fingerprints = dict(sorted(check_fingerprints.items()))
    if aggregate.get("identity_version") != BENCHMARK_PROTOCOL_IDENTITY_VERSION:
        errors.append("aggregate: unsupported or missing identity_version")
    if aggregate.get("status") != "complete":
        errors.append("aggregate: status must be complete")
    if aggregate.get("missing_benchmark_ids") != []:
        errors.append("aggregate: missing_benchmark_ids must be empty")
    if aggregate.get("check_fingerprints") != expected_check_fingerprints:
        errors.append("aggregate: check_fingerprints do not exactly match scored benchmark identities")

    expected_aggregate = {
        "identity_version": BENCHMARK_PROTOCOL_IDENTITY_VERSION,
        "status": "complete",
        "check_fingerprints": expected_check_fingerprints,
        "missing_benchmark_ids": [],
    }
    expected_fingerprint = stable_hash(expected_aggregate, length=64) if normalized_scored_ids else None
    if aggregate.get("fingerprint_sha256") != expected_fingerprint:
        errors.append("aggregate: fingerprint_sha256 does not match the canonical aggregate payload")

    return {
        "status": "pass" if not errors else "fail",
        "scored_benchmark_ids": normalized_scored_ids,
        "verified_check_count": len(check_fingerprints),
        "aggregate_fingerprint_sha256": aggregate.get("fingerprint_sha256"),
        "errors": errors,
    }


def result_documents_from_path(path: Path) -> Iterable[tuple[str, Dict[str, Any]]]:
    """Yield result JSON documents from a result file or completed bundle directory."""

    if path.is_file():
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("result JSON must contain an object: %s" % path)
        yield str(path), payload
        return
    if not path.is_dir():
        raise ValueError("path does not exist: %s" % path)
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("bundle is missing manifest.json: %s" % path)
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    result_paths = (manifest.get("files") or {}).get("results") if isinstance(manifest, dict) else None
    if not isinstance(result_paths, list) or not result_paths:
        raise ValueError("bundle manifest does not list result files: %s" % manifest_path)
    for relative_path in result_paths:
        candidate = (path / str(relative_path)).resolve()
        try:
            candidate.relative_to(path.resolve())
        except ValueError as exc:
            raise ValueError("result path escapes bundle directory: %s" % relative_path) from exc
        if not candidate.is_file():
            raise ValueError("bundle result file is missing: %s" % candidate)
        with candidate.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("result JSON must contain an object: %s" % candidate)
        yield str(candidate), payload


def verify_protocol_identity_path(path: Path, *, require_complete_coverage: bool = True) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    document_count = 0
    capability_count = 0
    for source, document in result_documents_from_path(path):
        document_count += 1
        capability = document.get("capability")
        if not isinstance(capability, dict):
            results.append(
                {
                    "status": "fail",
                    "scored_benchmark_ids": [],
                    "verified_check_count": 0,
                    "aggregate_fingerprint_sha256": None,
                    "errors": ["result document is missing capability evidence"],
                    "source": source,
                    "result_id": document.get("result_id"),
                }
            )
            continue
        capability_count += 1
        report = validate_capability_protocol_identity(
            capability,
            require_complete_coverage=require_complete_coverage,
        )
        report["source"] = source
        report["result_id"] = document.get("result_id")
        results.append(report)
    errors = [error for result in results for error in result["errors"]]
    capability_results = [result for result in results if result["aggregate_fingerprint_sha256"]]
    aggregate_fingerprints = {
        result["aggregate_fingerprint_sha256"] for result in capability_results
    }
    if len(aggregate_fingerprints) > 1:
        errors.append("capability protocol identity differs across bundle result documents")
    if not results:
        errors.append("no capability-bearing result documents found")
    return {
        "status": "pass" if results and not errors else "fail",
        "source": str(path),
        "result_document_count": document_count,
        "capability_result_count": capability_count,
        "verified_check_count": sum(result["verified_check_count"] for result in results),
        "results": results,
        "errors": errors,
    }
