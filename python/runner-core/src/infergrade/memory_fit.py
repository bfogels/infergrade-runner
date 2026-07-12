"""Versioned, evidence-honest memory allocation estimates."""

from typing import Any, Dict, Optional


ESTIMATOR_VERSION = "memory_fit_v1"
MIB = 1024 * 1024
GIB = 1024 * MIB
CONTEXT_BUCKET_TOKENS = (2048, 8192, 32768)


def _positive_optional(value: Optional[int], name: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s must be a positive integer when provided" % name)
    if value <= 0:
        raise ValueError("%s must be a positive integer when provided" % name)
    return value


def _component(
    estimate: Optional[int], source: str, residency_group: str, memory_domain: str,
    lower: Optional[int] = None, upper: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "estimate_bytes": estimate,
        "lower_bound_bytes": lower,
        "upper_bound_bytes": upper,
        "source": source,
        "residency_group": residency_group,
        "memory_domain": memory_domain,
        "offload_semantics": "unknown",
    }


def _peak_domain(method: Optional[str]) -> str:
    if method == "process_rss":
        return "process_memory"
    if method and method.startswith("container_cgroup"):
        return "container_memory"
    if method == "nvidia_smi_total_used_delta":
        return "device_vram"
    return "unknown"


def estimate_kv_cache_bytes(context_tokens: int, architecture: Optional[Dict[str, Any]]) -> Optional[int]:
    """Estimate dense-transformer KV allocation only with complete metadata."""
    tokens = _positive_optional(context_tokens, "context_tokens")
    metadata = architecture or {}
    if not isinstance(metadata, dict):
        raise ValueError("architecture must be an object when provided")
    required = ("layer_count", "embedding_length", "attention_head_count", "attention_head_count_kv", "kv_element_bytes")
    if any(metadata.get(key) is None for key in required):
        return None
    values = {key: _positive_optional(metadata[key], key) for key in required}
    if values["embedding_length"] % values["attention_head_count"]:
        return None
    return (
        tokens * values["layer_count"] * 2 * values["attention_head_count_kv"]
        * (values["embedding_length"] // values["attention_head_count"])
        * values["kv_element_bytes"]
    )


def estimate_memory_fit(
    context_tokens: int,
    model_weights_bytes: Optional[int] = None,
    model_buffer_bytes: Optional[int] = None,
    runtime_reported_kv_cache_bytes: Optional[int] = None,
    peak_memory_bytes: Optional[int] = None,
    peak_memory_measurement_method: Optional[str] = None,
    architecture: Optional[Dict[str, Any]] = None,
    support_proof: bool = False,
) -> Dict[str, Any]:
    """Describe allocation estimates; this function never returns a positive fit verdict."""
    tokens = _positive_optional(context_tokens, "context_tokens")
    weights = _positive_optional(model_weights_bytes, "model_weights_bytes")
    model_buffer = _positive_optional(model_buffer_bytes, "model_buffer_bytes")
    peak = _positive_optional(peak_memory_bytes, "peak_memory_bytes")
    runtime_kv = _positive_optional(runtime_reported_kv_cache_bytes, "runtime_reported_kv_cache_bytes")
    if runtime_kv is not None:
        kv_cache, kv_source = runtime_kv, "runtime_reported"
    else:
        kv_cache = estimate_kv_cache_bytes(tokens, architecture)
        kv_source = "formula_estimated" if kv_cache is not None else "unknown"

    resident_model = max(item for item in (weights, model_buffer) if item is not None) if any(
        item is not None for item in (weights, model_buffer)
    ) else None
    overhead_low = max(256 * MIB, int(resident_model * 0.05)) if resident_model is not None else None
    overhead_high = max(1 * GIB, int(resident_model * 0.20)) if resident_model is not None else None
    allocation_estimate_low = resident_model + kv_cache + overhead_low if resident_model and kv_cache else None
    allocation_estimate_high = resident_model + kv_cache + overhead_high if resident_model and kv_cache else None
    status = "estimated" if allocation_estimate_low is not None else "unknown"
    peak_domain = _peak_domain(peak_memory_measurement_method)
    prohibited_reason = (
        "device_vram_is_not_combined_system_memory" if peak_domain == "device_vram"
        else "no_compatible_capacity_or_calibrated_upper_bound"
    )

    return {
        "estimator_version": ESTIMATOR_VERSION,
        "status": status,
        "context_tokens": tokens,
        "support_proof": bool(support_proof),
        "fit_verdict": "not_evaluated",
        "fit_verdict_reason": prohibited_reason,
        "components": {
            "model_weights": _component(weights, "artifact_exact" if weights else "unknown", "model_resident", "artifact_storage"),
            "model_buffer": _component(model_buffer, "runtime_reported" if model_buffer else "unknown", "model_resident", "runtime_allocation"),
            "kv_cache": _component(kv_cache, kv_source, "context_resident", "runtime_allocation"),
            "runtime_overhead": {
                **_component(None, "formula_estimated" if overhead_low else "unknown", "runtime_resident", "runtime_allocation"),
                "estimate_range_low_bytes": overhead_low,
                "estimate_range_high_bytes": overhead_high,
            },
            "observed_peak": _component(peak, "measured" if peak else "unknown", "whole_domain_observation", peak_domain, lower=peak),
        },
        "required_memory": {
            "estimate_range_low_bytes": allocation_estimate_low,
            "estimate_range_high_bytes": allocation_estimate_high,
            "lower_bound_bytes": None,
            "upper_bound_bytes": None,
            "source": "mixed_estimate" if status == "estimated" else "unknown",
            "memory_domain": "unified_or_combined_memory",
        },
        "residency_semantics": {
            "aggregation": "max_overlapping_model_representations_then_add_context_and_overhead_estimates",
            "non_additive_component_groups": [["model_weights", "model_buffer"]],
            "observed_peak_aggregated": False,
            "offload_policy": "unknown",
            "domain_compatibility_required": True,
            "applicable_memory_domains": ["unified_memory", "combined_system_memory"],
            "device_vram_fit_prohibited": True,
            "notes": "Artifact mappings, runtime buffers, process memory, container memory, device VRAM, and unified memory are distinct domains. This estimate is not proof that a setup fits.",
        },
    }


def standard_context_estimates(**kwargs: Any) -> Dict[str, Dict[str, Any]]:
    """Return allocation-only estimates; standard contexts are never support proof."""
    kwargs = {**kwargs, "support_proof": False, "runtime_reported_kv_cache_bytes": None, "peak_memory_bytes": None, "peak_memory_measurement_method": None}
    return {str(tokens): estimate_memory_fit(context_tokens=tokens, **kwargs) for tokens in CONTEXT_BUCKET_TOKENS}
