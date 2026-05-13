"""Validation helpers for Runner-owned capability artifacts."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from infergrade.paths import runner_root

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
    "repeated_local_sample",
    "sampled_reference",
    "stronger_local_sample",
    "gold",
)
LEGACY_CONFIDENCE_LABELS = (
    "repeated_local_run",
    "reference_sample",
)
ACCEPTED_CONFIDENCE_LABELS = CONFIDENCE_LABELS + LEGACY_CONFIDENCE_LABELS
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
CAPABILITY_ARTIFACT_POINTER_KINDS = ("capability_run", "benchmark_summary", "unreadable_capability_run")


def repo_root() -> Path:
    """Return the repository root for the Runner workspace."""
    return runner_root()


def capability_run_schema_path(root: Optional[Path] = None) -> Path:
    """Return the path to the capability run artifact schema."""
    base = Path(root) if root is not None else repo_root()
    return base / "schemas" / "json" / "capability_run.schema.json"


def capability_summary_schema_path(root: Optional[Path] = None) -> Path:
    """Return the path to the capability summary artifact schema."""
    base = Path(root) if root is not None else repo_root()
    return base / "schemas" / "json" / "capability_summary.schema.json"


def load_capability_run_schema(root: Optional[Path] = None) -> Dict[str, Any]:
    """Load the capability run artifact schema."""
    return json.loads(capability_run_schema_path(root).read_text(encoding="utf-8"))


def load_capability_summary_schema(root: Optional[Path] = None) -> Dict[str, Any]:
    """Load the capability summary artifact schema."""
    return json.loads(capability_summary_schema_path(root).read_text(encoding="utf-8"))


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
        _enum(evidence, "confidence_label", ACCEPTED_CONFIDENCE_LABELS, errors, prefix="evidence.")
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


def validate_capability_summary_artifact(artifact: Dict[str, Any]) -> List[str]:
    """Return validation errors for the v1 capability summary artifact semantics."""
    errors: List[str] = []
    _require(artifact, "artifact_spec_version", errors)
    if artifact.get("artifact_kind") != "capability_summary":
        errors.append("artifact_kind must be capability_summary")
    _require(artifact, "summary_id", errors)
    _require(artifact, "created_at", errors)

    runner = artifact.get("runner")
    if not isinstance(runner, dict):
        errors.append("runner must be an object")
    else:
        _require(runner, "name", errors, prefix="runner.")
        _require(runner, "version", errors, prefix="runner.")

    surfaces = artifact.get("surfaces")
    if not isinstance(surfaces, list):
        errors.append("surfaces must be an array")
    else:
        seen_surfaces = set()
        for index, surface in enumerate(surfaces):
            if not isinstance(surface, dict):
                errors.append("surfaces[%d] must be an object" % index)
                continue
            prefix = "surfaces[%d]." % index
            _enum(surface, "surface", CAPABILITY_SURFACES, errors, prefix=prefix)
            _enum(surface, "state", CAPABILITY_STATES, errors, prefix=prefix)
            _optional_enum(surface, "lane", EVIDENCE_LANES, errors, prefix=prefix)
            _optional_enum(surface, "confidence_label", ACCEPTED_CONFIDENCE_LABELS, errors, prefix=prefix)
            if surface.get("surface") in seen_surfaces:
                errors.append(prefix + "surface must be unique")
            seen_surfaces.add(surface.get("surface"))
            if surface.get("state") == "scored" and surface.get("score") is None:
                errors.append(prefix + "score is required when state is scored")
            if surface.get("state") in ("failed", "skipped", "not_yet_benchmarked", "not_comparable") and surface.get("score") is not None:
                errors.append(prefix + "score must be null unless the surface is scored or partial")
            if not isinstance(surface.get("capability_artifacts"), list):
                errors.append(prefix + "capability_artifacts must be an array")
            if not _confidence_allowed_for_lane(surface.get("lane"), surface.get("confidence_label")):
                errors.append(prefix + "confidence_label cannot exceed evidence lane controls")

    artifacts = artifact.get("capability_artifacts")
    if not isinstance(artifacts, list):
        errors.append("capability_artifacts must be an array")
    else:
        for index, item in enumerate(artifacts):
            if not isinstance(item, dict):
                errors.append("capability_artifacts[%d] must be an object" % index)
                continue
            prefix = "capability_artifacts[%d]." % index
            _enum(item, "artifact_kind", CAPABILITY_ARTIFACT_POINTER_KINDS, errors, prefix=prefix)
            _enum(item, "surface", CAPABILITY_SURFACES, errors, prefix=prefix)
            _enum(item, "state", CAPABILITY_STATES, errors, prefix=prefix)
            _enum(item, "lane", EVIDENCE_LANES, errors, prefix=prefix)
            _enum(item, "confidence_label", ACCEPTED_CONFIDENCE_LABELS, errors, prefix=prefix)
            _require(item, "path", errors, prefix=prefix)
            if not _confidence_allowed_for_lane(item.get("lane"), item.get("confidence_label")):
                errors.append(prefix + "confidence_label cannot exceed evidence lane controls")

    next_action = artifact.get("next_recommended_benchmark_action")
    if not isinstance(next_action, dict):
        errors.append("next_recommended_benchmark_action must be an object")
    else:
        _require(next_action, "action", errors, prefix="next_recommended_benchmark_action.")
        _require(next_action, "reason", errors, prefix="next_recommended_benchmark_action.")

    unsupported = artifact.get("unsupported_claim_summary")
    if not isinstance(unsupported, list) or not all(isinstance(item, str) and item.strip() for item in unsupported):
        errors.append("unsupported_claim_summary must be a non-empty string array")

    return errors


def _require(payload: Dict[str, Any], key: str, errors: List[str], prefix: str = "") -> None:
    value = payload.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        errors.append(prefix + key + " is required")


def _enum(payload: Dict[str, Any], key: str, values: tuple, errors: List[str], prefix: str = "") -> None:
    if payload.get(key) not in values:
        errors.append(prefix + key + " must be one of: " + ", ".join(values))


def _optional_enum(payload: Dict[str, Any], key: str, values: tuple, errors: List[str], prefix: str = "") -> None:
    if payload.get(key) is not None and payload.get(key) not in values:
        errors.append(prefix + key + " must be one of: " + ", ".join(values))


def _confidence_allowed_for_lane(lane: Optional[str], confidence_label: Optional[str]) -> bool:
    if confidence_label is None:
        return True
    if lane is None:
        return confidence_label in ("single_smoke", "thin_local_sample")
    allowed = {
        "smoke": ("single_smoke",),
        "decision": ("single_smoke", "thin_local_sample", "repeated_local_sample", "repeated_local_run"),
        "reference": (
            "single_smoke",
            "thin_local_sample",
            "repeated_local_sample",
            "repeated_local_run",
            "sampled_reference",
            "reference_sample",
            "stronger_local_sample",
        ),
        "gold": ACCEPTED_CONFIDENCE_LABELS,
    }
    return confidence_label in allowed.get(lane, ())
