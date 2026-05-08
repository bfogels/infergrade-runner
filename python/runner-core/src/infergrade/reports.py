"""Human-readable Runner report artifacts."""

import os
from typing import Any, Dict, List, Optional

from infergrade.models import RunRequest
from infergrade.utils import ensure_dir


def write_bundle_report(
    output_dir: str,
    manifest: Dict[str, Any],
    summary: Dict[str, Any],
    validation: Dict[str, Any],
    results: List[Dict[str, Any]],
) -> str:
    """Write a standalone Markdown report for a completed bundle."""
    report_path = os.path.join(output_dir, "report.md")
    _write_text(report_path, render_bundle_report(manifest, summary, validation, results))
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
    return "\n".join(lines).rstrip() + "\n"


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
