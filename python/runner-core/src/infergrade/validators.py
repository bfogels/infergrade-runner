import os
from typing import List

from infergrade.benchmark_catalog import check_index, group_index, normalize_request_selection, suite_index
from infergrade.constants import (
    SUPPORTED_BACKENDS,
    SUPPORTED_CAPABILITY_MODES,
    SUPPORTED_COST_SOURCES,
    SUPPORTED_DEPLOYMENT_PROFILES,
    SUPPORTED_EXECUTION_MODES,
    SUPPORTED_TIERS,
    SUPPORTED_USE_CASES,
)
from infergrade.models import RunRequest, ValidationResult
from infergrade.utils import read_json


class RequestValidationError(ValueError):
    pass


def validate_request(request: RunRequest) -> None:
    normalize_request_selection(request)
    errors: List[str] = []
    if request.backend not in SUPPORTED_BACKENDS:
        errors.append("Unsupported backend: %s" % request.backend)
    if request.tier not in SUPPORTED_TIERS:
        errors.append("Unsupported tier: %s" % request.tier)
    if request.execution_mode not in SUPPORTED_EXECUTION_MODES:
        errors.append("Unsupported execution mode: %s" % request.execution_mode)
    if request.capability not in SUPPORTED_CAPABILITY_MODES:
        errors.append("Unsupported capability mode: %s" % request.capability)
    if request.cost_source and request.cost_source not in SUPPORTED_COST_SOURCES:
        errors.append("Unsupported cost source: %s" % request.cost_source)
    if request.evidence_source and request.evidence_source not in (
        "founder_dogfood",
        "agent_dogfood",
        "external_user",
    ):
        errors.append("Unsupported evidence source: %s" % request.evidence_source)
    if request.use_case and request.use_case not in SUPPORTED_USE_CASES:
        errors.append("Unsupported use case: %s" % request.use_case)
    suites = suite_index()
    groups = group_index()
    checks = check_index()
    bad_suite_ids = [item for item in request.capability_suite_ids if item not in suites]
    if bad_suite_ids:
        errors.append("Unsupported capability suites: %s" % ", ".join(sorted(set(bad_suite_ids))))
    bad_group_ids = [item for item in request.benchmark_group_ids if item not in groups]
    if bad_group_ids:
        errors.append("Unsupported benchmark groups: %s" % ", ".join(sorted(set(bad_group_ids))))
    bad_check_ids = [item for item in request.benchmark_check_ids if item not in checks]
    if bad_check_ids:
        errors.append("Unsupported benchmark checks: %s" % ", ".join(sorted(set(bad_check_ids))))
    incompatible_check_ids = [
        item
        for item in request.benchmark_check_ids
        if item in checks and checks[item].get("supported_backends") and request.backend not in checks[item].get("supported_backends")
    ]
    if incompatible_check_ids:
        errors.append(
            "Selected benchmark checks are not supported for backend %s: %s"
            % (request.backend, ", ".join(sorted(set(incompatible_check_ids))))
        )
    bad_profiles = [p for p in request.deployment_profiles if p not in SUPPORTED_DEPLOYMENT_PROFILES]
    if bad_profiles:
        errors.append("Unsupported deployment profiles: %s" % ", ".join(sorted(bad_profiles)))
    if request.tier in ("standard", "gold") and not request.use_case and request.capability != "none":
        errors.append("standard and gold runs require --use-case unless capability is disabled.")
    if errors:
        raise RequestValidationError("\n".join(errors))


def validate_bundle(bundle_dir: str) -> ValidationResult:
    errors = []
    warnings = []
    manifest_path = os.path.join(bundle_dir, "manifest.json")
    results_dir = os.path.join(bundle_dir, "results")
    environment_path = os.path.join(bundle_dir, "artifacts", "environment.json")
    ontology_path = os.path.join(bundle_dir, "artifacts", "ontology.json")
    validation_path = os.path.join(bundle_dir, "validation.json")
    if not os.path.exists(manifest_path):
        errors.append("Missing manifest.json")
    if not os.path.isdir(results_dir):
        errors.append("Missing results directory")
    if not os.path.exists(environment_path):
        errors.append("Missing artifacts/environment.json")
    if not os.path.exists(ontology_path):
        errors.append("Missing artifacts/ontology.json")
    result_files = []
    if os.path.isdir(results_dir):
        result_files = sorted(
            filename
            for filename in os.listdir(results_dir)
            if filename.endswith(".json") and os.path.isfile(os.path.join(results_dir, filename))
        )
        if not result_files:
            errors.append("results directory is empty")
    verification_level = "experimental"
    comparison_grade = "informational_only"
    eligibility = {}
    if result_files:
        first = read_json(os.path.join(results_dir, result_files[0]))
        if "ontology" not in first:
            errors.append("Result records must include ontology")
        verification = first.get("verification", {})
        derived = first.get("derived", {})
        verification_level = verification.get("verification_level", verification_level)
        comparison_grade = derived.get("comparison_grade") or verification.get(
            "local_comparison_grade_candidate", comparison_grade
        )
        for slice_id in derived.get("canonical_analysis_slice_ids", []):
            eligibility[slice_id] = True
    if not os.path.exists(validation_path):
        warnings.append("Missing validation.json")
    return ValidationResult(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        verification_level=verification_level,
        comparison_grade=comparison_grade,
        canonical_analysis_eligibility=eligibility,
    )
