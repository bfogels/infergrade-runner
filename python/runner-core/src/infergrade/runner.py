"""Bundle orchestration for InferGrade runner executions."""

from copy import deepcopy
import os
from typing import Any, Callable, Dict, List, Optional

from infergrade import __version__
from infergrade.adapters import get_adapter
from infergrade.artifacts import resolve_quant_artifact
from infergrade.benchmark_catalog import normalize_request_selection, selection_metadata_for_request
from infergrade.cuda import WINDOWS_CUDA_BINARY_SET, windows_cuda_preflight
from infergrade.environment import capture_environment
from infergrade.capabilities import attach_quant_fidelity_capability_artifact, summarize_capability_execution
from infergrade.models import CapabilityExecution, FidelityExecution, RunRequest
from infergrade.memory_fit import estimate_memory_fit, standard_context_estimates
from infergrade.ontology import build_ontology, resolve_artifact_sha256, resolve_quant_format
from infergrade.progress import (
    initialize_progress,
    load_progress,
    mark_completed,
    mark_capability_benchmark_completed,
    mark_capability_benchmark_started,
    mark_failed,
    mark_profile_completed,
    update_capability_benchmark_progress,
    update_profile_progress,
    mark_profile_started,
    mark_stage_completed,
    mark_stage_started,
    progress_path,
    request_fingerprint,
    save_progress,
)
from infergrade.profiles import resolve_capability_behavior, resolve_deployment_profiles, resolve_generation_preset
from infergrade.reports import write_bundle_report, write_failure_report
from infergrade.request import request_to_dict
from infergrade.utils import ensure_dir, read_json, slugify, stable_hash, utcnow_iso, write_json
from infergrade.validators import validate_bundle, validate_request


def _bundle_id(request: RunRequest) -> str:
    """Create a time-scoped bundle identifier for a run request."""
    return "qb_%s_%s" % (utcnow_iso().replace("-", "").replace(":", "").replace("T", "_").replace("Z", ""), stable_hash(request_to_dict(request), length=8))


def _canonical_slice_ids(result: Dict[str, Any], request: RunRequest) -> List[str]:
    """Assign official analysis slices for runs that match the curated hardware wedge."""
    hardware = result["hardware"]
    if hardware.get("accelerator_type") != "gpu":
        return []
    if hardware.get("accelerator_count") != 1:
        return []
    vram = hardware.get("accelerator_vram_gb")
    if not vram or not (23 <= float(vram) <= 25):
        return []
    if request.use_case == "agentic_coding":
        return ["coding_24gb_single_gpu_v1"]
    if request.use_case == "general_assistant":
        return ["assistant_24gb_single_gpu_v1"]
    return []


def _local_comparison_grade_candidate(request: RunRequest, verification_level: str, has_capability: bool) -> str:
    """Infer the local comparison grade before the server applies final policy."""
    if request.simulate:
        return "informational_only"
    if verification_level == "experimental":
        return "informational_only"
    if request.tier == "canary":
        return "comparable"
    # Official eligibility requires explicit provenance. Paired Hub ingestion may
    # derive this field from runner identity, but a standalone bundle must not
    # silently promote unattributed or dogfood evidence.
    if request.evidence_source != "external_user":
        return "comparable"
    if has_capability:
        return "official_eligible"
    return "comparable"


def _verification_level(request: RunRequest, hardware: Dict[str, Any], backend_version: str) -> str:
    """Estimate the trust level implied by the current run metadata."""
    if request.simulate:
        return "experimental"
    pinned_artifact = bool(request.quant_artifact and request.quant_artifact_sha256)
    hardware_captured = bool(hardware.get("accelerator_type"))
    if pinned_artifact and backend_version and hardware_captured:
        return "verified"
    if backend_version and hardware_captured:
        return "community"
    return "experimental"


def _build_result_record(
    bundle_id: str,
    request: RunRequest,
    ontology: Dict[str, Any],
    environment: Dict[str, Any],
    adapter_version: str,
    runtime_metadata: Dict[str, Any],
    capability: CapabilityExecution,
    fidelity: FidelityExecution,
    deployment: Dict[str, Any],
    deployment_profile: str,
    started_at: str,
    completed_at: str,
) -> Dict[str, Any]:
    """Normalize one deployment-profile run into the shared result-record contract."""
    selection_metadata = selection_metadata_for_request(request)
    quant_format = resolve_quant_format(
        request.quant_artifact_filename or request.quant_artifact or request.quant_artifact_resolved_path or "",
        request.backend,
    ) or "unknown"
    config_payload = {
        "model": request.model,
        "quant_artifact": request.quant_artifact,
        "quant_artifact_sha256": request.quant_artifact_sha256,
        "backend": request.backend,
        "backend_image": request.backend_image,
        "generation_preset": request.generation_preset,
        "backend_flags": request.backend_flags,
    }
    configuration_id = "cfg_%s" % stable_hash(config_payload)
    verification_level = _verification_level(request, environment, adapter_version)
    has_capability = capability.status in ("completed", "partial")
    comparison_grade_candidate = _local_comparison_grade_candidate(request, verification_level, has_capability)
    result_id = "%s_%s" % (bundle_id, slugify(deployment_profile))
    execution_runtime = max(1, int((len(request.backend_flags) + 1) * 30))
    artifact_sha256 = (
        request.quant_artifact_sha256
        or resolve_artifact_sha256(request.quant_artifact_resolved_path)
        or resolve_artifact_sha256(request.quant_artifact)
    )
    benchmark_job_cost_usd = None
    if request.hourly_rate_usd:
        benchmark_job_cost_usd = round(request.hourly_rate_usd * (execution_runtime / 3600.0), 4)
    runtime_selector = deepcopy(request.runtime_selector or {})
    record = {
        "spec_version": "0.1-draft",
        "bundle_id": bundle_id,
        "result_id": result_id,
        "ontology": ontology,
        "configuration": {
            "configuration_id": configuration_id,
            "model_base": request.model.split("/")[-1].lower(),
            "model_variant": request.use_case or "unspecified",
            "model_instance_name": request.model.split("/")[-1],
            "model_source": "user_input",
            "model_source_repo": request.model,
            "model_revision": "unspecified",
            "quant_label": request.quant_artifact_filename or (os.path.basename(request.quant_artifact) if request.quant_artifact else "auto_resolved"),
            "quant_format": quant_format,
            "quant_artifact_sha256": artifact_sha256,
            "backend_engine": request.backend,
            "backend_wrapper": None,
            "backend_version": adapter_version,
            "backend_execution": "native" if request.execution_mode == "local_native" else "container",
            "backend_flags": request.backend_flags,
            "tokenizer_id": "%s_default" % slugify(request.model.split("/")[-1]),
            "chat_template_id": request.use_case or "default",
            "generation_preset_id": request.generation_preset,
            "benchmark_selection": selection_metadata,
        },
        "hardware": environment,
        "verification": {
            "verification_level": verification_level,
            "artifact_pinned": bool(request.quant_artifact and artifact_sha256),
            "backend_version_pinned": bool(adapter_version),
            "container_pinned": request.execution_mode in ("local_container", "cloud_container"),
            "hardware_captured": True,
            "repeated_runs": 5 if request.tier != "canary" else 1,
            "variance_captured": request.tier != "canary",
            "run_bundle_sha256": stable_hash({"bundle_id": bundle_id, "result_id": result_id}),
            "missing_requirements": _missing_requirements(request, artifact_sha256),
            "validation_warnings": [],
            "local_comparison_grade_candidate": comparison_grade_candidate,
        },
        "execution": {
            "execution_profile_id": "%s_v1" % request.execution_mode,
            "execution_mode": request.execution_mode,
            "launcher": "infergrade-cli",
            "container_image": runtime_metadata.get("container_image"),
            "container_runtime": runtime_metadata.get("container_runtime"),
            "artifact_cache_dir": request.quant_artifact_cache_dir,
            "cloud_provider": request.cloud_provider,
            "cloud_region": None,
            "cloud_instance_type": request.cloud_instance_type,
            "started_at": started_at,
            "completed_at": completed_at,
            "benchmark_job_runtime_seconds": execution_runtime,
            "execution_cost_source": request.cost_source or ("estimated" if request.hourly_rate_usd else "none"),
            "benchmark_job_cost_usd": benchmark_job_cost_usd,
            "cost_measurement_method": request.cost_source or ("estimated" if request.hourly_rate_usd else "none"),
            "cost_measurement_confidence": 0.25 if benchmark_job_cost_usd is None else 0.75,
            "simulated": request.simulate,
        },
        "cost": {
            "cost_source": request.cost_source or ("estimated" if request.hourly_rate_usd else "none"),
            "hourly_rate_usd": request.hourly_rate_usd,
            "runtime_seconds": execution_runtime,
            "usd_per_run": None,
            "usd_per_1m_output_tokens": None,
            "benchmark_job_cost_usd": benchmark_job_cost_usd,
            "benchmark_job_cost_included": benchmark_job_cost_usd is not None,
            "cost_notes": "Simulated cost capture." if request.simulate else None,
        },
        "derived": {
            "passes_capability_floor": bool(has_capability and capability.score is not None and capability.score >= 0.5),
            "passes_verification_floor": verification_level in ("verified", "community"),
            "canonical_analysis_slice_ids": [],
            "frontier_group_id": None,
            "is_pareto_frontier_member": False,
            "recommendation_labels": [],
            "dominated_by": [],
        },
        "provenance": {
            "submitter": request.submitter,
            "submission_channel": "infergrade_cli",
            "source_bundle_origin": "infergrade_simulated_runner" if request.simulate else "infergrade_runner",
            "normalized_at": completed_at,
            "normalizer_version": __version__,
            "notes": request.notes,
            "run_config_id": request.run_config_id,
            "run_config_name": request.run_config_name,
            "run_config_source": request.run_config_source,
        },
    }
    if request.evidence_source:
        record["provenance"]["evidence_source"] = request.evidence_source
    if runtime_selector:
        record["execution"]["runtime_selector"] = runtime_selector
    record["capability"] = summarize_capability_execution(request, capability, completed_at=completed_at)
    record["capability"]["task_performance"] = deepcopy(capability.task_performance or {})
    record["fidelity"] = {
        "fidelity_state": fidelity.state,
        "fidelity_reason_codes": list(fidelity.reason_codes or []),
        "context": dict(fidelity.context or {}),
        "metrics": dict(fidelity.metrics or {}),
        "artifacts": dict(fidelity.artifacts or {}),
        "perplexity": dict((fidelity.metrics or {}).get("perplexity") or {}),
    }
    record["deployment"] = {
        "deployment_profile_id": deployment_profile,
        "prompt_profile_id": "%s_prompt_v1" % deployment_profile,
        "context_length_bucket": "2k_to_8k" if deployment_profile != "long_context_v1" else "8k_to_32k",
        "batch_size": 1 if deployment_profile != "batch_generation_v1" else 8,
        "concurrency": 1 if deployment_profile != "batch_generation_v1" else 4,
        "warmup_runs": 1 if request.tier == "canary" else 2,
        "measured_runs": 1 if request.tier == "canary" else 5,
        "ttft_p50_ms": deployment["ttft_p50_ms"],
        "ttft_p95_ms": deployment["ttft_p95_ms"],
        "latency_p50_ms": deployment["latency_p50_ms"],
        "latency_p95_ms": deployment["latency_p95_ms"],
        "prompt_tokens_per_second_p50": deployment.get("prompt_tokens_per_second_p50"),
        "prompt_tokens_per_second_p95": deployment.get("prompt_tokens_per_second_p95"),
        "decode_tokens_per_second_p50": deployment["decode_tokens_per_second_p50"],
        "decode_tokens_per_second_p95": deployment["decode_tokens_per_second_p95"],
        "output_tokens_p50": deployment.get("output_tokens_p50"),
        "output_tokens_p95": deployment.get("output_tokens_p95"),
        "natural_stop_rate": deployment.get("natural_stop_rate"),
        "token_budget_exhaustion_rate": deployment.get("token_budget_exhaustion_rate"),
        "semantic_task_completion_proof": bool(deployment.get("semantic_task_completion_proof", False)),
        "completion_semantics": deployment.get("completion_semantics"),
        "request_throughput_per_minute": deployment["request_throughput_per_minute"],
        "peak_vram_mb": deployment["peak_vram_mb"],
        "peak_memory_mb": deployment.get("peak_memory_mb"),
        "peak_memory_measurement_method": deployment.get("peak_memory_measurement_method"),
        "model_weights_bytes": deployment.get("model_weights_bytes"),
        "model_buffer_bytes": deployment.get("model_buffer_bytes"),
        "kv_cache_bytes": deployment.get("kv_cache_bytes"),
        "kv_cache_context_tokens": deployment.get("kv_cache_context_tokens"),
        "load_time_ms": deployment["load_time_ms"],
        "oom_or_failure_rate": deployment["oom_or_failure_rate"],
        "deployment_confidence": deployment["deployment_confidence"],
        "deployment_status": "simulated" if request.simulate else "completed",
    }
    model_weights_bytes = deployment.get("model_weights_bytes")
    if model_weights_bytes is None and request.quant_artifact_resolved_path and os.path.isfile(request.quant_artifact_resolved_path):
        model_weights_bytes = os.path.getsize(request.quant_artifact_resolved_path)
    record["deployment"]["model_weights_bytes"] = model_weights_bytes
    record["deployment"]["memory_fit"] = _memory_fit_payload(
        deployment, deployment_profile, model_weights_bytes
    )
    slices = _canonical_slice_ids(record, request)
    record["derived"]["canonical_analysis_slice_ids"] = slices
    record["derived"]["frontier_group_id"] = (
        "%s_%s" % (slices[0], deployment_profile) if slices else None
    )
    if slices and record["derived"]["passes_capability_floor"]:
        record["derived"]["is_pareto_frontier_member"] = True
        record["derived"]["recommendation_labels"] = ["candidate_frontier_member"]
    return record


def _memory_fit_payload(
    deployment: Dict[str, Any], deployment_profile: str, model_weights_bytes: Optional[int]
) -> Dict[str, Any]:
    """Propagate only context-matched runtime allocations into an estimate."""
    def positive_int_or_none(value: Any, name: str) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("%s must be a positive integer when provided" % name)
        if value == 0:
            return None
        if value < 0:
            raise ValueError("%s must be a positive integer when provided" % name)
        return value

    def peak_bytes_or_none(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("peak_memory_mb must be a positive number when provided")
        if value == 0:
            return None
        if value < 0:
            raise ValueError("peak_memory_mb must be a positive number when provided")
        return int(value * 1024 * 1024)

    reported_kv_context = positive_int_or_none(deployment.get("kv_cache_context_tokens"), "kv_cache_context_tokens")
    weights = positive_int_or_none(model_weights_bytes, "model_weights_bytes")
    model_buffer = positive_int_or_none(deployment.get("model_buffer_bytes"), "model_buffer_bytes")
    kv_cache = positive_int_or_none(deployment.get("kv_cache_bytes"), "kv_cache_bytes")
    peak_bytes = peak_bytes_or_none(deployment.get("peak_memory_mb"))
    memory_inputs = {
        "model_weights_bytes": weights,
        "model_buffer_bytes": model_buffer,
        "runtime_reported_kv_cache_bytes": (
            kv_cache if reported_kv_context is not None else None
        ),
        "peak_memory_bytes": peak_bytes,
        "peak_memory_measurement_method": deployment.get("peak_memory_measurement_method"),
        "architecture": deployment.get("model_architecture"),
    }
    return {
        "current_context_status": "runtime_reported" if reported_kv_context is not None else "unknown",
        "current_context": (
            estimate_memory_fit(context_tokens=reported_kv_context, **memory_inputs)
            if reported_kv_context is not None else None
        ),
        "standard_contexts": standard_context_estimates(
            **{
                **memory_inputs,
                "runtime_reported_kv_cache_bytes": None,
                "peak_memory_bytes": None,
                "peak_memory_measurement_method": None,
            }
        ),
    }


def _request_selects_cuda_runtime(request: RunRequest) -> bool:
    selector = request.runtime_selector or {}
    accelerator = selector.get("accelerator") if isinstance(selector, dict) else {}
    delivery = selector.get("delivery") if isinstance(selector, dict) else {}
    return (
        isinstance(accelerator, dict)
        and accelerator.get("api") == "cuda"
        and accelerator.get("vendor") in (None, "nvidia", "unknown")
    ) or (
        isinstance(delivery, dict)
        and str(delivery.get("binary_set") or "").startswith("llama_cpp_windows_cuda")
    )


def _enforce_runtime_selector_before_execution(request: RunRequest) -> None:
    """Reject blocked CUDA selectors before any backend can run or upload evidence."""
    if not _request_selects_cuda_runtime(request):
        return
    selector = request.runtime_selector or {}
    driver = selector.get("driver") if isinstance(selector, dict) else {}
    delivery = selector.get("delivery") if isinstance(selector, dict) else {}
    preflight = windows_cuda_preflight(
        runtime_binary_path=request.llama_cpp_cli_path,
        cuda_major=str((driver or {}).get("cuda_major") or "12"),
        selected_binary_set=(delivery or {}).get("binary_set") or WINDOWS_CUDA_BINARY_SET,
    )
    request.runtime_selector = preflight["selector"]
    compatibility = request.runtime_selector["compatibility"]
    if compatibility.get("status") != "ready":
        reason_codes = ", ".join(compatibility.get("reason_codes") or ["unknown"])
        raise ValueError(
            "CUDA runtime selector is not ready for evidence-producing execution; "
            "refusing silent fallback. reason_codes=%s" % reason_codes
        )


def _missing_requirements(request: RunRequest, artifact_sha256: Any) -> List[str]:
    """List missing provenance fields that reduce result trust."""
    missing = []
    if not request.quant_artifact:
        missing.append("quant_artifact")
    if request.quant_artifact and not artifact_sha256:
        missing.append("quant_artifact_sha256")
    return missing


def _emit_progress(callback: Optional[Callable[[str], None]], message: str) -> None:
    """Forward progress updates only when a caller supplied a callback."""
    if callback:
        callback(message)


def _output_dir_has_existing_state(output_dir: str) -> bool:
    """Return whether an output directory already contains InferGrade state."""
    if not os.path.isdir(output_dir):
        return False
    with os.scandir(output_dir) as entries:
        return any(True for _entry in entries)


def _validate_resume_progress(progress: Dict[str, Any], request: RunRequest) -> None:
    """Reject resume attempts that point at a bundle from a different request."""
    if progress.get("request_fingerprint") != request_fingerprint(request):
        raise ValueError(
            "Existing progress.json does not match this request. Use a new --output directory or adjust the request."
        )


def _completed_bundle_result(output_dir: str, bundle_id: str) -> Dict[str, Any]:
    """Return the minimal response payload for a previously completed bundle."""
    summary = read_json(os.path.join(output_dir, "summary.json"))
    validation = read_json(os.path.join(output_dir, "validation.json"))
    report_path = os.path.join(output_dir, "report.md")
    return {
        "bundle_id": bundle_id,
        "output_dir": output_dir,
        "result_count": summary.get("result_count", 0),
        "summary_path": os.path.join(output_dir, "summary.json"),
        "progress_path": progress_path(output_dir),
        "report_path": report_path if os.path.exists(report_path) else None,
        "validation": validation,
    }


def _deployment_metrics_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the deployment-metric subset needed for resumable artifacts."""
    deployment = record["deployment"]
    return {
        "ttft_p50_ms": deployment["ttft_p50_ms"],
        "ttft_p95_ms": deployment["ttft_p95_ms"],
        "latency_p50_ms": deployment["latency_p50_ms"],
        "latency_p95_ms": deployment["latency_p95_ms"],
        "prompt_tokens_per_second_p50": deployment.get("prompt_tokens_per_second_p50"),
        "prompt_tokens_per_second_p95": deployment.get("prompt_tokens_per_second_p95"),
        "decode_tokens_per_second_p50": deployment["decode_tokens_per_second_p50"],
        "decode_tokens_per_second_p95": deployment["decode_tokens_per_second_p95"],
        "output_tokens_p50": deployment.get("output_tokens_p50"),
        "output_tokens_p95": deployment.get("output_tokens_p95"),
        "natural_stop_rate": deployment.get("natural_stop_rate"),
        "token_budget_exhaustion_rate": deployment.get("token_budget_exhaustion_rate"),
        "semantic_task_completion_proof": bool(deployment.get("semantic_task_completion_proof", False)),
        "completion_semantics": deployment.get("completion_semantics"),
        "request_throughput_per_minute": deployment["request_throughput_per_minute"],
        "peak_vram_mb": deployment["peak_vram_mb"],
        "peak_memory_mb": deployment.get("peak_memory_mb"),
        "peak_memory_measurement_method": deployment.get("peak_memory_measurement_method"),
        "model_weights_bytes": deployment.get("model_weights_bytes"),
        "model_buffer_bytes": deployment.get("model_buffer_bytes"),
        "kv_cache_bytes": deployment.get("kv_cache_bytes"),
        "kv_cache_context_tokens": deployment.get("kv_cache_context_tokens"),
        "load_time_ms": deployment["load_time_ms"],
        "oom_or_failure_rate": deployment["oom_or_failure_rate"],
        "deployment_confidence": deployment["deployment_confidence"],
    }


def _run_fidelity(adapter, request: RunRequest) -> FidelityExecution:
    """Collect optional fidelity signals without requiring every adapter to implement them."""
    if hasattr(adapter, "run_fidelity"):
        return adapter.run_fidelity(request)
    if request.simulate:
        return FidelityExecution(state="not_yet_measured", reason_codes=["simulated_run_skips_fidelity"])
    return FidelityExecution(state="not_yet_measured", reason_codes=["backend_fidelity_not_implemented"])


def _load_resumable_result(output_dir: str, progress: Dict[str, Any], profile_id: str) -> Optional[Dict[str, Any]]:
    """Load a completed per-profile result when resume state says it is reusable."""
    profile_progress = progress.get("deployment_profiles", {}).get(profile_id, {})
    if profile_progress.get("status") != "completed":
        return None
    result_path = profile_progress.get("result_path")
    if not result_path:
        return None
    absolute_path = os.path.join(output_dir, result_path)
    if not os.path.exists(absolute_path):
        return None
    return read_json(absolute_path)


def run_infergrade(request: RunRequest, emit_progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Execute an InferGrade request and write a reproducible bundle to disk.

    The runner owns default resolution, artifact handling, progress tracking, and
    final bundle normalization so callers do not need to assemble result records
    by hand.
    """
    request.generation_preset = resolve_generation_preset(request.generation_preset)
    normalize_request_selection(request)
    request.deployment_profiles = resolve_deployment_profiles(request.use_case, request.deployment_profiles)
    request.capability = resolve_capability_behavior(request.tier, request.use_case, request.capability)
    _enforce_runtime_selector_before_execution(request)
    adapter = get_adapter(request.backend)
    if not request.backend_flags:
        request.backend_flags = adapter.default_backend_flags()
    validate_request(request)

    if request.resume and not request.output_dir:
        raise ValueError("Resume requires an explicit output directory.")

    provisional_bundle_id = _bundle_id(request)
    output_dir = request.output_dir or os.path.join("runs", provisional_bundle_id)
    existing_progress = load_progress(output_dir) if request.resume else None
    if existing_progress:
        _validate_resume_progress(existing_progress, request)
        bundle_id = existing_progress["bundle_id"]
    else:
        bundle_id = provisional_bundle_id

    request.output_dir = output_dir

    if not request.resume and _output_dir_has_existing_state(output_dir):
        raise ValueError(
            "Output directory already contains InferGrade state. Re-run with --resume or choose a new --output path."
        )
    if request.resume and _output_dir_has_existing_state(output_dir) and existing_progress is None:
        raise ValueError("Cannot resume: existing output directory has no progress.json to continue from.")

    ensure_dir(output_dir)
    ensure_dir(os.path.join(output_dir, "results"))
    ensure_dir(os.path.join(output_dir, "artifacts", "capability"))
    ensure_dir(os.path.join(output_dir, "artifacts", "receipts"))
    ensure_dir(os.path.join(output_dir, "provenance"))

    if existing_progress and existing_progress.get("status") == "completed":
        if os.path.exists(os.path.join(output_dir, "summary.json")) and os.path.exists(os.path.join(output_dir, "validation.json")):
            _emit_progress(emit_progress, "Reused completed bundle from %s" % progress_path(output_dir))
            return _completed_bundle_result(output_dir, bundle_id)

    started_at = existing_progress.get("started_at") if existing_progress else utcnow_iso()
    progress = existing_progress or initialize_progress(bundle_id, request, started_at)
    save_progress(output_dir, progress)

    current_stage = "initializing"
    current_detail = None

    try:
        current_stage = "environment_capture"
        mark_stage_started(output_dir, progress, current_stage)
        _emit_progress(emit_progress, "Capturing environment...")
        environment = capture_environment(request.execution_mode)
        mark_stage_completed(output_dir, progress, current_stage, metadata={"path": "artifacts/environment.json"})

        resolved_artifact = None
        current_stage = "artifact_resolution"
        mark_stage_started(output_dir, progress, current_stage)
        if request.quant_artifact and not request.simulate:
            _emit_progress(emit_progress, "Resolving model artifact...")
            resolved_artifact = resolve_quant_artifact(request)
            request.quant_artifact_resolved_path = resolved_artifact.resolved_path
            request.quant_artifact_sha256 = request.quant_artifact_sha256 or resolved_artifact.sha256
            request.quant_artifact_filename = request.quant_artifact_filename or resolved_artifact.filename
        mark_stage_completed(
            output_dir,
            progress,
            current_stage,
            metadata={"resolved": bool(resolved_artifact), "artifact": request.quant_artifact},
        )

        current_stage = "backend_resolution"
        mark_stage_started(output_dir, progress, current_stage)
        _emit_progress(emit_progress, "Resolving backend runtime...")
        adapter_version = adapter.resolve_version(simulate=request.simulate, request=request)
        runtime_metadata = adapter.runtime_metadata(request)
        mark_stage_completed(output_dir, progress, current_stage, metadata={"backend_version": adapter_version})

        current_stage = "ontology_build"
        mark_stage_started(output_dir, progress, current_stage)
        ontology = build_ontology(request, adapter_version)
        mark_stage_completed(output_dir, progress, current_stage, metadata={"subject_id": ontology["benchmark_subject"]["subject_id"]})

        current_stage = "capability"
        mark_stage_started(output_dir, progress, current_stage)
        if request.capability != "none":
            _emit_progress(emit_progress, "Running capability suite...")
        def _on_capability_progress(payload: Dict[str, Any]) -> None:
            event = payload.get("event")
            benchmark_id = payload.get("benchmark_id")
            if event == "benchmark_started" and benchmark_id:
                mark_capability_benchmark_started(
                    output_dir,
                    progress,
                    benchmark_id=benchmark_id,
                    display_name=str(payload.get("display_name") or benchmark_id),
                    total_cases=payload.get("total_cases"),
                )
            elif event == "case_progress" and benchmark_id:
                update_capability_benchmark_progress(
                    output_dir,
                    progress,
                    benchmark_id=benchmark_id,
                    completed_cases=payload.get("completed_cases"),
                    total_cases=payload.get("total_cases"),
                    current_case=payload.get("current_case"),
                    progress_detail="%s/%s" % (
                        payload.get("completed_cases") or 0,
                        payload.get("total_cases") or "?",
                    ),
                )
            elif event == "benchmark_completed" and benchmark_id:
                update_capability_benchmark_progress(
                    output_dir,
                    progress,
                    benchmark_id=benchmark_id,
                    completed_cases=payload.get("completed_cases"),
                    total_cases=payload.get("total_cases"),
                    progress_detail="completed" if payload.get("status") == "completed" else "failed",
                )
                mark_capability_benchmark_completed(
                    output_dir,
                    progress,
                    benchmark_id=benchmark_id,
                    status=str(payload.get("status") or "completed"),
                    metadata={
                        key: payload[key]
                        for key in ("primary_metric", "error")
                        if payload.get(key) is not None
                    },
                )
            if payload.get("message"):
                _emit_progress(emit_progress, str(payload["message"]))

        capability_execution = adapter.run_capability(request, progress_callback=_on_capability_progress)
        mark_stage_completed(output_dir, progress, current_stage, metadata={"status": capability_execution.status})

        current_stage = "fidelity"
        mark_stage_started(output_dir, progress, current_stage)
        _emit_progress(emit_progress, "Measuring quantization fidelity...")
        fidelity_execution = _run_fidelity(adapter, request)
        attach_quant_fidelity_capability_artifact(
            request=request,
            execution=capability_execution,
            fidelity=fidelity_execution,
            output_dir=output_dir,
            ontology=ontology,
            environment=environment,
            runtime_metadata=runtime_metadata,
            backend_version=adapter_version,
        )
        mark_stage_completed(output_dir, progress, current_stage, metadata={"state": fidelity_execution.state})

        deployment_artifacts: Dict[str, Any] = {}
        existing_metrics_path = os.path.join(output_dir, "artifacts", "deployment_metrics.json")
        if request.resume and os.path.exists(existing_metrics_path):
            deployment_artifacts = read_json(existing_metrics_path)
        result_paths: List[str] = []
        result_records: List[Dict[str, Any]] = []

        for profile_id in request.deployment_profiles:
            existing_record = _load_resumable_result(output_dir, progress, profile_id) if request.resume else None
            if existing_record is not None:
                _emit_progress(emit_progress, "Skipping completed deployment profile %s" % profile_id)
                result_records.append(existing_record)
                result_paths.append(os.path.join("results", "%s.json" % profile_id))
                if profile_id not in deployment_artifacts:
                    deployment_artifacts[profile_id] = _deployment_metrics_from_record(existing_record)
                continue

            current_stage = "deployment"
            current_detail = profile_id
            mark_profile_started(output_dir, progress, profile_id)
            _emit_progress(emit_progress, "Running deployment profile %s..." % profile_id)
            def _on_deployment_progress(payload: Dict[str, Any]) -> None:
                event = payload.get("event")
                if event in ("profile_started", "iteration_started", "iteration_completed"):
                    update_profile_progress(
                        output_dir,
                        progress,
                        profile_id=profile_id,
                        total_iterations=payload.get("total_iterations"),
                        completed_iterations=payload.get("completed_iterations"),
                        warmup_runs=payload.get("warmup_runs"),
                        measured_runs=payload.get("measured_runs"),
                        current_iteration=payload.get("current_iteration"),
                        current_phase=payload.get("phase"),
                        progress_detail=(
                            "%s %s/%s"
                            % (
                                payload.get("phase") or "iteration",
                                payload.get("current_iteration") or payload.get("completed_iterations") or 0,
                                payload.get("total_iterations") or "?",
                            )
                        ),
                    )
                if payload.get("message"):
                    _emit_progress(emit_progress, str(payload["message"]))

            execution = adapter.run_deployment_profile(request, profile_id, progress_callback=_on_deployment_progress)
            record = _build_result_record(
                bundle_id=bundle_id,
                request=request,
                ontology=ontology,
                environment=environment,
                adapter_version=adapter_version,
                runtime_metadata=runtime_metadata,
                capability=capability_execution,
                fidelity=fidelity_execution,
                deployment=execution.metrics,
                deployment_profile=profile_id,
                started_at=started_at,
                completed_at=utcnow_iso(),
            )
            result_records.append(record)
            result_path = os.path.join(output_dir, "results", "%s.json" % profile_id)
            write_json(result_path, record)
            relative_result_path = os.path.relpath(result_path, output_dir)
            result_paths.append(relative_result_path)
            mark_profile_completed(output_dir, progress, profile_id, relative_result_path, record["result_id"])
            if execution.artifacts:
                deployment_artifacts[profile_id] = {
                    "metrics": execution.metrics,
                    "artifacts": execution.artifacts,
                }
            else:
                deployment_artifacts[profile_id] = execution.metrics

        _emit_progress(emit_progress, "Writing bundle artifacts...")
        write_json(os.path.join(output_dir, "artifacts", "environment.json"), environment)
        write_json(os.path.join(output_dir, "artifacts", "ontology.json"), ontology)
        write_json(os.path.join(output_dir, "artifacts", "deployment_metrics.json"), deployment_artifacts)
        if resolved_artifact is not None:
            write_json(
                os.path.join(output_dir, "artifacts", "receipts", "artifact_resolution.json"),
                resolved_artifact.to_dict(),
            )
        if capability_execution.status != "skipped":
            write_json(
                os.path.join(output_dir, "artifacts", "capability", "raw_results.json"),
                {
                    "use_case": capability_execution.use_case,
                    "suite_id": capability_execution.suite_id,
                    "benchmark_tier": capability_execution.benchmark_tier,
                    "components": capability_execution.components,
                    "score": capability_execution.score,
                    "component_scores": capability_execution.component_scores,
                    "benchmark_results": capability_execution.benchmark_results,
                    "artifacts": capability_execution.artifacts,
                    "status": capability_execution.status,
                },
            )
        if fidelity_execution.metrics or fidelity_execution.context or fidelity_execution.reason_codes:
            write_json(
                os.path.join(output_dir, "artifacts", "fidelity.json"),
                {
                    "state": fidelity_execution.state,
                    "reason_codes": list(fidelity_execution.reason_codes or []),
                    "context": dict(fidelity_execution.context or {}),
                    "metrics": dict(fidelity_execution.metrics or {}),
                    "artifacts": dict(fidelity_execution.artifacts or {}),
                },
            )
        write_json(
            os.path.join(output_dir, "provenance", "model_artifact.json"),
            {
                "model": request.model,
                "quant_artifact": request.quant_artifact,
                "quant_artifact_sha256": request.quant_artifact_sha256,
                "quant_artifact_filename": request.quant_artifact_filename,
                "quant_artifact_resolved_path": request.quant_artifact_resolved_path,
                "artifact_resolution": resolved_artifact.to_dict() if resolved_artifact else None,
            },
        )
        write_json(
            os.path.join(output_dir, "provenance", "backend_config.json"),
            {
                "backend": request.backend,
                "backend_version": adapter_version,
                "backend_flags": request.backend_flags,
                "generation_preset": request.generation_preset,
                "simulate": request.simulate,
                "runtime_metadata": runtime_metadata,
            },
        )
        write_json(os.path.join(output_dir, "provenance", "hardware_snapshot.json"), environment)
        if request.run_config_id or request.run_config_source:
            write_json(
                os.path.join(output_dir, "provenance", "run_config.json"),
                {
                    "run_config_id": request.run_config_id,
                    "run_config_name": request.run_config_name,
                    "run_config_source": request.run_config_source,
                },
            )

        current_stage = "finalization"
        current_detail = None
        mark_stage_started(output_dir, progress, current_stage)

        manifest_files = {
            "results": result_paths,
            "environment": "artifacts/environment.json",
            "ontology": "artifacts/ontology.json",
            "deployment_metrics": "artifacts/deployment_metrics.json",
            "validation": "validation.json",
            "summary": "summary.json",
            "progress": "progress.json",
        }
        if resolved_artifact:
            manifest_files["artifact_resolution"] = "artifacts/receipts/artifact_resolution.json"
        if fidelity_execution.metrics or fidelity_execution.context or fidelity_execution.reason_codes:
            manifest_files["fidelity"] = "artifacts/fidelity.json"
        capability_summary_path = ((capability_execution.artifacts or {}).get("_summary") or {}).get("capability_summary_path")
        if capability_summary_path:
            manifest_files["capability_summary"] = os.path.relpath(capability_summary_path, output_dir)
        manifest = {
            "bundle_spec_version": "0.1-draft",
            "result_spec_version": "0.1-draft",
            "bundle_id": bundle_id,
            "created_at": utcnow_iso(),
            "runner": {"name": "infergrade", "version": __version__},
            "status": {
                "execution_status": "simulated" if request.simulate else "completed",
                "deployment_status": "simulated" if request.simulate else "completed",
                "capability_status": capability_execution.status,
                "fidelity_status": fidelity_execution.state,
                "validation_status": "pending",
            },
            "files": manifest_files,
        }
        write_json(os.path.join(output_dir, "manifest.json"), manifest)
        validation = validate_bundle(output_dir)
        write_json(os.path.join(output_dir, "validation.json"), validation.to_dict())
        final_validation = validate_bundle(output_dir)
        write_json(os.path.join(output_dir, "validation.json"), final_validation.to_dict())
        selection_metadata = selection_metadata_for_request(request)
        summary = {
            "bundle_id": bundle_id,
            "result_count": len(result_records),
            "result_ids": [record["result_id"] for record in result_records],
            "deployment_profiles": [record["deployment"]["deployment_profile_id"] for record in result_records],
            "benchmark_selection": selection_metadata,
            "benchmark_scope": dict(selection_metadata.get("benchmark_scope") or {}),
            "benchmark_check_ids": list(selection_metadata.get("benchmark_check_ids") or []),
            "benchmark_subject_id": ontology["benchmark_subject"]["subject_id"],
            "checkpoint_name": ontology["checkpoint"]["checkpoint_name"],
            "model_family": ontology["model_family"]["family_name"],
            "artifact_uri": request.quant_artifact,
            "artifact_sha256": request.quant_artifact_sha256,
            "artifact_cache_hit": resolved_artifact.cache_hit if resolved_artifact else None,
            "use_cases": sorted(
                {
                    record.get("capability", {}).get("use_case")
                    for record in result_records
                    if record.get("capability", {}).get("use_case")
                }
            ),
            "verification_levels": sorted(
                {
                    record["verification"]["verification_level"]
                    for record in result_records
                }
            ),
            "local_comparison_grade_candidates": sorted(
                {
                    record["verification"]["local_comparison_grade_candidate"]
                    for record in result_records
                    if record["verification"].get("local_comparison_grade_candidate")
                }
            ),
            "fidelity_states": sorted(
                {
                    record.get("fidelity", {}).get("fidelity_state")
                    for record in result_records
                    if record.get("fidelity", {}).get("fidelity_state")
                }
            ),
            "run_config_id": request.run_config_id,
            "run_config_name": request.run_config_name,
            "simulated": request.simulate,
            "validation": final_validation.to_dict(),
        }
        if capability_summary_path:
            summary["capability_summary"] = os.path.relpath(capability_summary_path, output_dir)
        write_json(os.path.join(output_dir, "summary.json"), summary)
        manifest["status"]["validation_status"] = "valid" if final_validation.valid else "invalid"
        manifest["files"]["report"] = "report.md"
        write_json(os.path.join(output_dir, "manifest.json"), manifest)
        report_path = write_bundle_report(output_dir, manifest, summary, final_validation.to_dict(), result_records)
        mark_stage_completed(output_dir, progress, current_stage, metadata={"result_count": len(result_records)})
        mark_completed(output_dir, progress, len(result_records))
        _emit_progress(emit_progress, "Completed bundle %s" % bundle_id)
        return {
            "bundle_id": bundle_id,
            "output_dir": output_dir,
            "result_count": len(result_records),
            "summary_path": os.path.join(output_dir, "summary.json"),
            "progress_path": progress_path(output_dir),
            "report_path": report_path,
            "validation": final_validation.to_dict(),
        }
    except Exception as exc:
        mark_failed(output_dir, progress, current_stage, current_detail, str(exc))
        write_failure_report(output_dir, request, progress, str(exc), stage=current_stage, detail=current_detail)
        raise


def run_quantbench(request: RunRequest, emit_progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Legacy compatibility alias for the pre-rebrand runner entrypoint."""
    return run_infergrade(request, emit_progress=emit_progress)
