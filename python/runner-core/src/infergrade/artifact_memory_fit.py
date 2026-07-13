"""Runner-owned, artifact-only GGUF memory allocation policy."""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from infergrade.memory_fit import estimate_kv_cache_bytes
from infergrade.paths import runner_root


ARTIFACT_VERSION = "1.0"
POLICY_ID = "gguf_artifact_memory_fit_v1"


def load_artifact_memory_fit_policy(root: Optional[Path] = None) -> Dict[str, Any]:
    """Load the versioned Runner-owned GGUF artifact estimate policy."""
    base = Path(root) if root is not None else runner_root()
    policy = json.loads(
        (base / "schemas" / "policies" / "artifact_memory_fit_policy.v1.json").read_text(encoding="utf-8")
    )
    if policy.get("policy_id") != POLICY_ID:
        raise ValueError("Unsupported artifact memory fit policy")
    return policy


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("%s must be a positive integer" % name)
    return value


def build_gguf_artifact_memory_fit(
    artifact_size_bytes: int,
    architecture: Optional[Dict[str, Any]] = None,
    artifact_size_source: str = "local_file_stat",
    architecture_metadata_source: Optional[str] = None,
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build estimates from GGUF artifact facts only, without a runtime or machine claim."""
    selected_policy = dict(policy or load_artifact_memory_fit_policy())
    if selected_policy.get("policy_id") != POLICY_ID:
        raise ValueError("Unsupported artifact memory fit policy")
    size = _positive_int(artifact_size_bytes, "artifact_size_bytes")
    if artifact_size_source not in selected_policy["accepted_artifact_size_sources"]:
        raise ValueError("artifact_size_source is not allowed by %s" % POLICY_ID)
    element_bytes = _positive_int(selected_policy["kv_cache_policy"]["element_bytes"], "element_bytes")
    if architecture is None:
        if architecture_metadata_source not in (None, "unknown"):
            raise ValueError("architecture_metadata_source requires architecture metadata")
        normalized_architecture = None
        estimator_architecture = None
        resolved_architecture_source = "unknown"
    else:
        if not isinstance(architecture, dict):
            raise ValueError("architecture must be an object when provided")
        resolved_architecture_source = architecture_metadata_source or "gguf_metadata"
        if resolved_architecture_source not in selected_policy["accepted_architecture_metadata_sources"]:
            raise ValueError("architecture_metadata_source is not allowed by %s" % POLICY_ID)
        normalized_architecture = {
            name: _positive_int(architecture.get(name), name)
            for name in selected_policy["required_gguf_architecture_fields"]
        }
        if normalized_architecture["embedding_length"] % normalized_architecture["attention_head_count"]:
            raise ValueError("embedding_length must be divisible by attention_head_count")
        if normalized_architecture["attention_head_count_kv"] > normalized_architecture["attention_head_count"]:
            raise ValueError("attention_head_count_kv must not exceed attention_head_count")
        if normalized_architecture["attention_head_count"] % normalized_architecture["attention_head_count_kv"]:
            raise ValueError("attention_head_count must be divisible by attention_head_count_kv")
        estimator_architecture = {**normalized_architecture, "kv_element_bytes": element_bytes}

    overhead_policy = selected_policy["runtime_overhead_policy"]
    overhead_low = max(
        _positive_int(overhead_policy["low_floor_bytes"], "low_floor_bytes"),
        int(size * float(overhead_policy["low_ratio_of_artifact_size"])),
    )
    overhead_high = max(
        _positive_int(overhead_policy["high_floor_bytes"], "high_floor_bytes"),
        int(size * float(overhead_policy["high_ratio_of_artifact_size"])),
    )
    if overhead_high < overhead_low:
        raise ValueError("runtime overhead high estimate must not be below low estimate")

    context_estimates: Dict[str, Dict[str, Any]] = {}
    previous_low = 0
    previous_high = 0
    for context_tokens in selected_policy["context_buckets_tokens"]:
        tokens = _positive_int(context_tokens, "context_tokens")
        if estimator_architecture is not None:
            kv_cache = estimate_kv_cache_bytes(tokens, estimator_architecture)
            if kv_cache is None:
                raise ValueError("GGUF architecture metadata is insufficient for KV estimation")
            kv_low = kv_high = kv_cache
            method = "architecture_formula"
            estimate_source = "architecture_formula_estimated"
        else:
            fallback = selected_policy["fallback_context_ranges"][str(tokens)]
            kv_low = max(
                _positive_int(fallback["low_floor_bytes"], "fallback low_floor_bytes"),
                int(size * float(fallback["low_ratio_of_artifact_size"])),
            )
            kv_high = max(
                _positive_int(fallback["high_floor_bytes"], "fallback high_floor_bytes"),
                int(size * float(fallback["high_ratio_of_artifact_size"])),
            )
            if kv_high < kv_low:
                raise ValueError("fallback context high estimate must not be below low estimate")
            kv_cache = None
            method = "artifact_size_fallback_range"
            estimate_source = "artifact_size_fallback_estimated"
        low = size + kv_low + overhead_low
        high = size + kv_high + overhead_high
        if low > high or low < previous_low or high < previous_high:
            raise ValueError("artifact memory estimates must be ordered and monotonic")
        previous_low = low
        previous_high = high
        context_estimates[str(tokens)] = {
            "context_tokens": tokens,
            "estimate_range_low_bytes": low,
            "estimate_range_high_bytes": high,
            "lower_bound_bytes": None,
            "upper_bound_bytes": None,
            "components": {
                "artifact_size_proxy_bytes": size,
                "kv_cache_estimate_bytes": kv_cache,
                "kv_cache_range_low_bytes": kv_low,
                "kv_cache_range_high_bytes": kv_high,
                "runtime_overhead_range_low_bytes": overhead_low,
                "runtime_overhead_range_high_bytes": overhead_high,
            },
            "method": method,
            "source": estimate_source,
            "memory_domain": selected_policy["aggregation_policy"]["memory_domain"],
            "fit_verdict": "not_evaluated",
        }

    policy_boundary = selected_policy["claim_boundary"]
    return {
        "artifact_type": "gguf_artifact_memory_fit",
        "artifact_version": ARTIFACT_VERSION,
        "policy_id": POLICY_ID,
        "estimator_version": selected_policy["estimator_version"],
        "status": "estimated",
        "source": {
            "artifact_format": "gguf",
            "artifact_size_bytes": size,
            "artifact_size_source": artifact_size_source,
            "architecture_metadata_source": resolved_architecture_source,
            "runtime_measurements_used": False,
        },
        "architecture_metadata": (
            {**normalized_architecture, "kv_cache_element_bytes": element_bytes}
            if normalized_architecture is not None else None
        ),
        "context_estimates": context_estimates,
        "assumptions": list(selected_policy["assumptions"]),
        "claim_boundary": {
            **policy_boundary,
            "memory_domain": selected_policy["aggregation_policy"]["memory_domain"],
            "offload_policy": selected_policy["aggregation_policy"]["offload_policy"],
            "guaranteed_bounds": False,
        },
    }


def export_gguf_artifact_memory_fit(
    output_path: Path,
    artifact_size_bytes: int,
    architecture: Optional[Dict[str, Any]] = None,
    artifact_size_source: str = "local_file_stat",
    architecture_metadata_source: Optional[str] = None,
    policy: Optional[Dict[str, Any]] = None,
) -> Path:
    """Write one deterministic artifact estimate for contract consumers."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = build_gguf_artifact_memory_fit(
        artifact_size_bytes=artifact_size_bytes,
        architecture=architecture,
        artifact_size_source=artifact_size_source,
        architecture_metadata_source=architecture_metadata_source,
        policy=policy,
    )
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination
