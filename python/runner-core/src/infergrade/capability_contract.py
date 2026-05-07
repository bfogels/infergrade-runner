"""Validation helpers for Runner-owned capability run artifacts."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

EVIDENCE_LANES = ("smoke", "decision", "reference", "gold")
CAPABILITY_SURFACES = (
    "local_assistant_capability",
    "local_coding_capability",
    "local_reasoning_capability",
    "quant_fidelity",
    "deployment_fitness",
)
CAPABILITY_STATES = ("scored", "partial", "failed", "skipped", "not_yet_benchmarked", "not_comparable")
CONFIDENCE_LABELS = (
    "single_smoke",
    "thin_local_sample",
    "repeated_local_run",
    "stronger_local_sample",
    "reference_sample",
    "gold",
)
SCORER_TYPES = (
    "exact_match",
    "regex",
    "json_schema",
    "unit_test",
    "static_check",
    "multiple_choice",
    "perplexity",
    "metric_only",
    "manual_review",
)


def repo_root() -> Path:
    """Return the repository root for the Runner workspace."""
    return Path(__file__).resolve().parents[4]


def capability_run_schema_path(root: Optional[Path] = None) -> Path:
    """Return the path to the capability run artifact schema."""
    base = Path(root) if root is not None else repo_root()
    return base / "schemas" / "json" / "capability_run.schema.json"


def load_capability_run_schema(root: Optional[Path] = None) -> Dict[str, Any]:
    """Load the capability run artifact schema."""
    return json.loads(capability_run_schema_path(root).read_text(encoding="utf-8"))


def validate_capability_run_artifact(artifact: Dict[str, Any]) -> List[str]:
    """Return validation errors for the v1 capability run artifact semantics."""
    errors: List[str] = []
    _require(artifact, "artifact_spec_version", errors)
    if artifact.get("artifact_kind") != "capability_run":
        errors.append("artifact_kind must be capability_run")
    _require(artifact, "capability_run_id", errors)
    _require(artifact, "created_at", errors)

    evidence = artifact.get("evidence")
    if not isinstance(evidence, dict):
        errors.append("evidence must be an object")
    else:
        _enum(evidence, "lane", EVIDENCE_LANES, errors, prefix="evidence.")
        _enum(evidence, "surface", CAPABILITY_SURFACES, errors, prefix="evidence.")
        _enum(evidence, "confidence_label", CONFIDENCE_LABELS, errors, prefix="evidence.")
        if "experimental" not in evidence or not isinstance(evidence.get("experimental"), bool):
            errors.append("evidence.experimental must be a boolean")
        _require(evidence, "grade", errors, prefix="evidence.")

    protocol = artifact.get("protocol")
    if not isinstance(protocol, dict):
        errors.append("protocol must be an object")
    else:
        _require(protocol, "task_family", errors, prefix="protocol.")
        _require(protocol, "fixture_revision", errors, prefix="protocol.")
        _enum(
            protocol,
            "scorer_type",
            SCORER_TYPES,
            errors,
            prefix="protocol.",
        )
        _require(protocol, "scoring_policy", errors, prefix="protocol.")
        repetitions = protocol.get("repetitions")
        if not isinstance(repetitions, int) or repetitions < 1:
            errors.append("protocol.repetitions must be an integer >= 1")

    summary = artifact.get("summary")
    if not isinstance(summary, dict):
        errors.append("summary must be an object")
    else:
        _enum(summary, "state", CAPABILITY_STATES, errors)
        state = summary.get("state")
        if state == "scored" and summary.get("score") is None:
            errors.append("summary.score is required when summary.state is scored")
        if state in ("failed", "skipped", "not_yet_benchmarked", "not_comparable") and summary.get("score") is not None:
            errors.append("summary.score must be null unless the run is scored or partial")

    tasks = artifact.get("tasks")
    if not isinstance(tasks, list):
        errors.append("tasks must be an array")
    else:
        for index, task in enumerate(tasks):
            if not isinstance(task, dict):
                errors.append("tasks[%d] must be an object" % index)
                continue
            prefix = "tasks[%d]." % index
            _require(task, "task_id", errors, prefix=prefix)
            _require(task, "task_family", errors, prefix=prefix)
            _enum(task, "state", CAPABILITY_STATES, errors, prefix=prefix)
            state = task.get("state")
            if state == "scored" and task.get("score") is None:
                errors.append(prefix + "score is required when state is scored")
            if state == "scored":
                _require(task, "scorer_type", errors, prefix=prefix)
                _require(task, "scoring_policy", errors, prefix=prefix)
            if state in ("failed", "skipped", "not_yet_benchmarked", "not_comparable") and task.get("score") is not None:
                errors.append(prefix + "score must be null unless the task is scored or partial")
            if state == "failed" and not task.get("error_class"):
                errors.append(prefix + "error_class is required when state is failed")

    claim_boundary = artifact.get("claim_boundary")
    if not isinstance(claim_boundary, dict):
        errors.append("claim_boundary must be an object")
    else:
        for key in ("supported_claims", "unsupported_claims"):
            value = claim_boundary.get(key)
            if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
                errors.append("claim_boundary.%s must be a non-empty string array" % key)

    return errors


def _require(payload: Dict[str, Any], key: str, errors: List[str], prefix: str = "") -> None:
    value = payload.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        errors.append(prefix + key + " is required")


def _enum(payload: Dict[str, Any], key: str, values: tuple, errors: List[str], prefix: str = "") -> None:
    if payload.get(key) not in values:
        errors.append(prefix + key + " must be one of: " + ", ".join(values))
