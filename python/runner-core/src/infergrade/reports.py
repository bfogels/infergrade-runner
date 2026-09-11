"""Human-readable Runner report artifacts."""

import os
import posixpath
from typing import Any, Dict, List, Optional

from infergrade.models import CapabilityExecution, RunRequest
from infergrade.reasoning_constraint_stress_v2_qualification import (
    BENCHMARK_ID as REASONING_V2_QUALIFICATION_BENCHMARK_ID,
    GENERATION_POLICY_ID as REASONING_V2_QUALIFICATION_GENERATION_POLICY_ID,
    POLICY_ENFORCEMENT_REQUESTED_UNVERIFIED,
    POLICY_ENFORCEMENT_VERIFIED,
)
from infergrade.utils import ensure_dir


_REASONING_V2_QUALIFICATION_DISPLAY_NAME = "Reasoning constraint stress v2 qualification"
_REASONING_V2_QUALIFICATION_ENFORCEMENT_STATES = frozenset(
    (POLICY_ENFORCEMENT_REQUESTED_UNVERIFIED, POLICY_ENFORCEMENT_VERIFIED)
)


def write_bundle_report(
    output_dir: str,
    manifest: Dict[str, Any],
    summary: Dict[str, Any],
    validation: Dict[str, Any],
    results: List[Dict[str, Any]],
    capability_execution: Optional[CapabilityExecution] = None,
) -> str:
    """Write a standalone Markdown report for a completed bundle."""
    report_path = os.path.join(output_dir, "report.md")
    _write_text(
        report_path,
        render_bundle_report(
            manifest,
            summary,
            validation,
            results,
            capability_execution=capability_execution,
            output_dir=output_dir,
        ),
    )
    return report_path


def write_failure_report(
    output_dir: str,
    request: RunRequest,
    progress: Dict[str, Any],
    error: str,
    stage: Optional[str] = None,
    detail: Optional[str] = None,
) -> str:
    """Write a truthful Markdown report for a run that failed before finalization."""
    report_path = os.path.join(output_dir, "report.md")
    selected_checks = list(getattr(request, "benchmark_check_ids", None) or [])
    lines = [
        "# InferGrade Runner Report",
        "",
        "## Status",
        "",
        "- Outcome: failed before a complete bundle was finalized.",
        "- Stage: %s" % _dash(stage),
        "- Detail: %s" % _dash(detail),
        "- Error: %s" % _dash(error),
        "",
        "## Requested Setup",
        "",
        "- Model: %s" % _dash(request.model),
        "- Quant artifact: %s" % _dash(request.quant_artifact),
        "- Backend: %s" % _dash(request.backend),
        "- Execution mode: %s" % _dash(request.execution_mode),
        "- Use case: %s" % _dash(request.use_case),
        "- Selected checks: %s" % _dash(", ".join(selected_checks)),
        "",
        "## Progress Snapshot",
        "",
        "- Bundle id: %s" % _dash(progress.get("bundle_id")),
        "- Progress status: %s" % _dash(progress.get("status")),
        "- Started at: %s" % _dash(progress.get("started_at")),
        "",
        "This report is intentionally incomplete because the run did not reach bundle finalization.",
    ]
    _write_text(report_path, "\n".join(lines).rstrip() + "\n")
    return report_path


def render_bundle_report(
    manifest: Dict[str, Any],
    summary: Dict[str, Any],
    validation: Dict[str, Any],
    results: List[Dict[str, Any]],
    capability_execution: Optional[CapabilityExecution] = None,
    output_dir: Optional[str] = None,
) -> str:
    """Render a completed bundle into a compact Markdown report."""
    representative = results[0] if results else {}
    ontology = representative.get("ontology") or {}
    configuration = representative.get("configuration") or {}
    benchmark_selection = configuration.get("benchmark_selection") or {}
    benchmark_scope = benchmark_selection.get("benchmark_scope") or {}
    hardware = representative.get("hardware") or {}
    capability = representative.get("capability") or {}
    fidelity = representative.get("fidelity") or {}
    verification = representative.get("verification") or {}

    lines = [
        "# InferGrade Runner Report",
        "",
        "## Summary",
        "",
        "- Bundle id: %s" % _dash(summary.get("bundle_id") or manifest.get("bundle_id")),
        "- Result count: %s" % _dash(summary.get("result_count")),
        "- Validation: %s" % ("valid" if validation.get("valid") else "invalid"),
        "- Simulated: %s" % _dash(summary.get("simulated")),
        "",
        "## Model And Quant",
        "",
        "- Family: %s" % _dash((ontology.get("model_family") or {}).get("family_name") or summary.get("model_family")),
        "- Checkpoint: %s" % _dash((ontology.get("checkpoint") or {}).get("checkpoint_name") or summary.get("checkpoint_name")),
        "- Quant label: %s" % _dash((ontology.get("quantization") or {}).get("quantization_label") or configuration.get("quant_label")),
        "- Quant artifact: %s" % _dash(summary.get("artifact_uri") or configuration.get("quant_artifact_sha256")),
        "- Artifact sha256: %s" % _dash(summary.get("artifact_sha256") or configuration.get("quant_artifact_sha256")),
        "",
        "## Runtime And Hardware",
        "",
        "- Backend: %s" % _dash(configuration.get("backend_engine")),
        "- Backend version: %s" % _dash(configuration.get("backend_version")),
        "- Execution mode: %s" % _dash((representative.get("execution") or {}).get("execution_mode")),
        "- Accelerator: %s" % _dash(hardware.get("accelerator_model") or hardware.get("accelerator_vendor") or hardware.get("hardware_class")),
        "- VRAM: %s" % _format_gb(hardware.get("accelerator_vram_gb")),
        "- RAM: %s" % _format_gb(hardware.get("system_ram_gb")),
        "- CPU: %s" % _dash(hardware.get("cpu_model")),
        "",
        "## Benchmark Scope",
        "",
        "- Scope: %s" % _dash(benchmark_scope.get("scope_label") or benchmark_scope.get("scope")),
        "- Effort: %s" % _dash(benchmark_scope.get("effort_level")),
        "- Expected duration: %s" % _dash(benchmark_scope.get("expected_duration_band")),
        "- Token volume: %s" % _dash(benchmark_scope.get("token_volume_band")),
        "- Metadata confidence: %s" % _dash(benchmark_scope.get("metadata_confidence")),
        "- Checks: %s" % _dash(", ".join(benchmark_selection.get("benchmark_check_ids") or [])),
        "",
        "## Deployment Metrics",
        "",
        "| Profile | TTFT p50 | Decode tok/s | Load time | Peak VRAM | Failure rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(_deployment_rows(results))
    lines.extend(
        [
            "",
            "## Capability And Fidelity",
            "",
            "- Capability state: %s" % _dash(capability.get("capability_state")),
            "- Capability score: %s" % _dash(capability.get("capability_score")),
            "- Capability status: %s" % _dash(capability.get("capability_status")),
            "- Capability summary artifact: %s" % _dash((manifest.get("files") or {}).get("capability_summary")),
            "- Capability run artifacts: %s" % _dash(_capability_run_artifact_paths(capability)),
            "- Fidelity state: %s" % _dash(fidelity.get("fidelity_state")),
            "- Perplexity: %s" % _dash(((fidelity.get("perplexity") or {}).get("value"))),
            "",
            "## Trust And Comparability",
            "",
            "- Verification level: %s" % _dash(verification.get("verification_level")),
            "- Local comparison grade candidate: %s" % _dash(verification.get("local_comparison_grade_candidate")),
            "- Validation errors: %s" % _dash("; ".join(validation.get("errors") or [])),
            "- Validation warnings: %s" % _dash("; ".join(validation.get("warnings") or [])),
            "",
            "## Rerun Metadata",
            "",
            "- Run config id: %s" % _dash(summary.get("run_config_id")),
            "- Run config name: %s" % _dash(summary.get("run_config_name")),
            "- Created at: %s" % _dash(manifest.get("created_at")),
        ]
    )
    qualification_lines = _qualification_diagnostics_lines(output_dir, capability_execution)
    if qualification_lines:
        lines.extend([""] + qualification_lines)
    return "\n".join(lines).rstrip() + "\n"


def _qualification_diagnostics_lines(
    output_dir: Optional[str],
    execution: Optional[CapabilityExecution],
) -> List[str]:
    """Render the excluded reasoning qualification sidecar without changing the result contract."""
    if not _qualification_execution_requested(execution):
        return []

    benchmark_results = getattr(execution, "benchmark_results", None)
    result = (
        benchmark_results.get(REASONING_V2_QUALIFICATION_BENCHMARK_ID)
        if isinstance(benchmark_results, dict)
        else None
    )
    links = _qualification_artifact_links(output_dir)
    if not isinstance(result, dict) or not result:
        return [
            "## Qualification Diagnostics",
            "",
            "- Diagnostic result: unavailable; the qualification execution did not record a benchmark result.",
            "- Strict result (diagnostic only): n/a",
            "- Cases completed: n/a",
            "- Format-invalid outputs: n/a",
            "- Token-budget exhaustions: n/a",
            "- Generation failures: n/a",
            "- Generation policy: n/a",
            "- Frozen policy fingerprint: `n/a`",
            "- Enforcement truth: n/a",
            "- Evidence role: diagnostic only; excluded from headline capability evidence and canonical promotion.",
            "- Claim boundary: not headline capability evidence, a readiness signal, a recommendation, a release gate, or canonical promotion.",
            "- Artifact links: %s" % links,
        ]

    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    task_performance = result.get("task_performance") if isinstance(result.get("task_performance"), dict) else {}
    selection = result.get("selection") if isinstance(result.get("selection"), dict) else {}
    protocol = result.get("protocol") if isinstance(result.get("protocol"), dict) else {}
    total_cases = _consistent_valid_count(
        result.get("total_cases"),
        metrics.get("total_count"),
        selection.get("case_count"),
    )
    completed_cases = _bounded_count(
        _consistent_valid_count(result.get("completed_cases"), metrics.get("completed_case_count")),
        total_cases,
    )
    completed_bound = completed_cases if completed_cases is not None else total_cases
    strict_correct = _bounded_count(metrics.get("correct_count"), completed_bound)
    format_invalid = _bounded_count(metrics.get("format_invalid_count"), completed_bound)
    budget_exhaustions = _bounded_count(
        _consistent_valid_count(
            metrics.get("token_budget_exhaustion_count"),
            task_performance.get("token_budget_exhaustion_count"),
        ),
        completed_bound,
    )
    generation_failures = _bounded_count(
        _consistent_valid_count(
            result.get("generation_failure_count"),
            metrics.get("generation_failure_count"),
        ),
        total_cases,
    )
    unscored_failures = _bounded_count(
        _consistent_valid_count(
            result.get("unscored_generation_failure_count"),
            metrics.get("unscored_generation_failure_count"),
        ),
        total_cases,
    )
    if (
        generation_failures is not None
        and unscored_failures is not None
        and unscored_failures > generation_failures
    ):
        unscored_failures = None
    diagnostic_candidates = _bounded_count(
        metrics.get("diagnostic_semantic_candidate_count"), total_cases
    )
    diagnostic_correct = (
        _bounded_count(metrics.get("diagnostic_semantic_correct_count"), diagnostic_candidates)
        if diagnostic_candidates is not None
        else None
    )
    diagnostic_unavailable = _bounded_count(
        metrics.get("diagnostic_semantic_unavailable_count"), total_cases
    )
    failure_classes = metrics.get("diagnostic_failure_class_counts")
    format_only = _bounded_count(
        failure_classes.get("format_only") if isinstance(failure_classes, dict) else None,
        total_cases,
    )
    substantive_wrong = _bounded_count(
        failure_classes.get("substantive_wrong") if isinstance(failure_classes, dict) else None,
        total_cases,
    )
    unavailable = _bounded_count(
        failure_classes.get("unavailable") if isinstance(failure_classes, dict) else None,
        total_cases,
    )
    failure_class_counts = (format_only, substantive_wrong, unavailable)
    if (
        total_cases is not None
        and all(count is not None for count in failure_class_counts)
        and sum(failure_class_counts) > total_cases
    ):
        format_only = substantive_wrong = unavailable = None
    generation_policy = (
        REASONING_V2_QUALIFICATION_GENERATION_POLICY_ID
        if result.get("generation_policy_id")
        == REASONING_V2_QUALIFICATION_GENERATION_POLICY_ID
        or protocol.get("generation_policy_id")
        == REASONING_V2_QUALIFICATION_GENERATION_POLICY_ID
        else None
    )
    fingerprint = _sha256_fingerprint(
        result.get("generation_policy_fingerprint")
        or protocol.get("generation_policy_fingerprint")
    )

    return [
        "## Qualification Diagnostics",
        "",
        "- Benchmark: %s" % _REASONING_V2_QUALIFICATION_DISPLAY_NAME,
        "- Strict result (diagnostic only): %s correct"
        % _report_fraction(strict_correct, total_cases),
        "- Cases completed: %s" % _report_fraction(completed_cases, total_cases),
        "- Format-invalid outputs: %s" % _report_count(format_invalid),
        "- Token-budget exhaustions: %s" % _report_count(budget_exhaustions),
        "- Generation failures: %s (unscored: %s)"
        % (_report_count(generation_failures), _report_count(unscored_failures)),
        "- Diagnostic semantic candidates: %s (correct: %s; unavailable: %s)"
        % (
            _report_count(diagnostic_candidates),
            _report_count(diagnostic_correct),
            _report_count(diagnostic_unavailable),
        ),
        "- Diagnostic failure classes: format-only %s; substantive wrong %s; unavailable %s"
        % (
            _report_count(format_only),
            _report_count(substantive_wrong),
            _report_count(unavailable),
        ),
        "- Generation policy: %s" % (generation_policy or "n/a"),
        "- Frozen policy fingerprint: `%s`" % (fingerprint or "n/a"),
        "- Enforcement truth: %s"
        % _format_policy_enforcement(result, metrics, protocol, total_cases),
        "- Evidence role: diagnostic only; excluded from headline capability evidence and canonical promotion.",
        "- Claim boundary: not headline capability evidence, a readiness signal, a recommendation, a release gate, or canonical promotion.",
        "- Artifact links: %s" % links,
    ]


def _qualification_execution_requested(execution: Optional[CapabilityExecution]) -> bool:
    if execution is None:
        return False
    check_ids = getattr(execution, "benchmark_check_ids", ())
    if isinstance(check_ids, str):
        check_ids = (check_ids,)
    if REASONING_V2_QUALIFICATION_BENCHMARK_ID in check_ids:
        return True
    for attribute in ("benchmark_results", "artifacts"):
        payload = getattr(execution, attribute, None)
        if isinstance(payload, dict) and REASONING_V2_QUALIFICATION_BENCHMARK_ID in payload:
            return True
    return False


def _consistent_valid_count(*payload_keys: Any) -> Optional[int]:
    values = []
    for value in payload_keys:
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return None
        values.append(value)
    if not values or len(set(values)) != 1:
        return None
    return values[0]


def _bounded_count(value: Any, total: Optional[int]) -> Optional[int]:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    if total is not None and value > total:
        return None
    return value


def _report_count(value: Optional[int]) -> str:
    return "n/a" if value is None else str(value)


def _report_fraction(numerator: Optional[int], denominator: Optional[int]) -> str:
    if numerator is None or denominator is None:
        return "n/a"
    return "%s/%s" % (numerator, denominator)


def _format_policy_enforcement(
    result: Dict[str, Any],
    metrics: Dict[str, Any],
    protocol: Dict[str, Any],
    total_cases: Optional[int],
) -> str:
    raw_states = metrics.get("policy_enforcement_states")
    if raw_states is None:
        raw_states = protocol.get("generation_policy_enforcement")
    states: Dict[str, int] = {}
    if isinstance(raw_states, dict):
        for state, count in raw_states.items():
            safe_state = _allowed_enforcement_state(state)
            if safe_state is None:
                return "n/a"
            valid_count = _bounded_count(count, total_cases)
            if valid_count is None:
                return "n/a"
            states[safe_state] = valid_count
    elif isinstance(raw_states, list):
        for state in raw_states:
            safe_state = _allowed_enforcement_state(state)
            if safe_state is None:
                return "n/a"
            states[safe_state] = states.get(safe_state, 0) + 1
        if total_cases is not None and len(raw_states) > total_cases:
            return "n/a"
    else:
        state = _allowed_enforcement_state(result.get("generation_policy_enforcement"))
        if state:
            return "%s (case count unavailable)" % state
    if not states:
        return "n/a"
    if total_cases is not None and sum(states.values()) > total_cases:
        return "n/a"
    return "; ".join(
        "%s (%s/%s cases)" % (state, count, _report_count(total_cases))
        for state, count in sorted(states.items())[:8]
    )


def _allowed_enforcement_state(value: Any) -> Optional[str]:
    if isinstance(value, str) and value in _REASONING_V2_QUALIFICATION_ENFORCEMENT_STATES:
        return value
    return None


def _qualification_artifact_links(output_dir: Optional[str]) -> str:
    relative_dir = posixpath.join(
        "artifacts",
        "capability",
        REASONING_V2_QUALIFICATION_BENCHMARK_ID,
    )
    links = []
    for filename in ("summary.json", "capability_run.json"):
        relative_path = posixpath.join(relative_dir, filename)
        if output_dir is None or os.path.isfile(os.path.join(output_dir, *relative_path.split("/"))):
            links.append("[%s](%s)" % (filename, relative_path))
    return "; ".join(links) if links else "n/a (qualification artifacts not materialized)"


def _sha256_fingerprint(value: Any) -> Optional[str]:
    if not isinstance(value, str) or len(value) != 64:
        return None
    if any(character not in "0123456789abcdefABCDEF" for character in value):
        return None
    return value


def _deployment_rows(results: List[Dict[str, Any]]) -> List[str]:
    if not results:
        return ["| n/a | n/a | n/a | n/a | n/a | n/a |"]
    rows = []
    for result in results:
        deployment = result.get("deployment") or {}
        rows.append(
            "| %s | %s | %s | %s | %s | %s |"
            % (
                _dash(deployment.get("deployment_profile_id")),
                _format_ms(deployment.get("ttft_p50_ms")),
                _format_number(deployment.get("decode_tokens_per_second_p50")),
                _format_ms(deployment.get("load_time_ms")),
                _format_mb(deployment.get("peak_vram_mb")),
                _format_percent(deployment.get("oom_or_failure_rate")),
            )
        )
    return rows


def _capability_run_artifact_paths(capability: Dict[str, Any]) -> str:
    artifacts = capability.get("capability_artifacts") or {}
    paths = []
    if isinstance(artifacts, dict):
        for benchmark_id, payload in sorted(artifacts.items()):
            if benchmark_id == "_summary" or not isinstance(payload, dict):
                continue
            path = payload.get("capability_run_path")
            if path:
                paths.append("%s=%s" % (benchmark_id, path))
    return ", ".join(paths)


def _write_text(path: str, content: str) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def _dash(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    return str(value)


def _format_number(value: Any) -> str:
    if isinstance(value, (int, float)):
        return "%.2f" % float(value)
    return _dash(value)


def _format_ms(value: Any) -> str:
    if isinstance(value, (int, float)):
        return "%.0f ms" % float(value)
    return _dash(value)


def _format_mb(value: Any) -> str:
    if isinstance(value, (int, float)):
        return "%.0f MB" % float(value)
    return _dash(value)


def _format_gb(value: Any) -> str:
    if isinstance(value, (int, float)):
        return "%.1f GB" % float(value)
    return _dash(value)


def _format_percent(value: Any) -> str:
    if isinstance(value, (int, float)):
        return "%.1f%%" % (float(value) * 100.0)
    return _dash(value)
