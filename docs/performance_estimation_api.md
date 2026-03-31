# Performance Estimation API

## Endpoint

`POST /performance/estimate`

Public read endpoint that estimates deployment performance for a target model/backend/hardware combination.

## Request Modes

### 1. Run-config based

Use this when the server already issued a run config and the caller wants a pre-run estimate for a specific machine.

```json
{
  "run_config_id": "rcfg_qwen_assistant_canary",
  "hardware": {
    "accelerator_type": "gpu",
    "accelerator_vendor": "nvidia",
    "accelerator_model": "RTX 4090",
    "accelerator_vram_gb": 24,
    "memory_gb": 64
  }
}
```

### 2. Explicit target

Use this when an agent or client wants to estimate performance without first creating a run config.

```json
{
  "target": {
    "backend_engine": "llama.cpp",
    "execution_mode": "local_container",
    "use_case": "general_assistant",
    "deployment_profile_id": "interactive_chat_v1",
    "ontology": {
      "family_name": "Qwen2.5",
      "checkpoint_name": "Qwen2.5-7B-Instruct",
      "parameter_scale": "7B",
      "training_stage": "instruction_tuned",
      "quantization_family": "k_quant",
      "quantization_scheme": "q4_k_m",
      "weight_precision_bits": 4
    },
    "hardware": {
      "accelerator_type": "gpu",
      "accelerator_vendor": "nvidia",
      "accelerator_model": "RTX 4090",
      "accelerator_vram_gb": 24,
      "memory_gb": 64
    }
  },
  "metrics": [
    "decode_tokens_per_second_p50",
    "ttft_p50_ms",
    "load_time_ms"
  ],
  "filters": {
    "require_real": true,
    "verification_levels": ["verified", "community", "experimental"]
  },
  "limit_neighbors": 6
}
```

## Supported Metrics

- `decode_tokens_per_second_p50`
- `ttft_p50_ms`
- `load_time_ms`

## Response Shape

```json
{
  "target": {
    "run_config_id": "rcfg_qwen_assistant_canary",
    "backend_engine": "llama.cpp",
    "execution_mode": "local_container",
    "use_case": "general_assistant",
    "deployment_profile_id": "interactive_chat_v1",
    "checkpoint_name": "Qwen2.5-7B-Instruct",
    "family_name": "Qwen2.5",
    "parameter_scale_b": 7.0,
    "training_stage": "instruction_tuned",
    "quantization_family": "k_quant",
    "quantization_scheme": "q4_k_m",
    "weight_precision_bits": 4.0,
    "accelerator_type": "gpu",
    "accelerator_vendor": "nvidia",
    "accelerator_model": "RTX 4090",
    "accelerator_vram_gb": 24.0,
    "memory_gb": 64.0,
    "machine_model": null
  },
  "filters": {
    "require_real": true,
    "verification_levels": ["verified", "community", "experimental"]
  },
  "summary": {
    "catalog_candidates": 123,
    "filtered_candidates": 18,
    "supporting_neighbors": 6,
    "estimator_version": "0.1.0"
  },
  "predictions": {
    "decode_tokens_per_second_p50": {
      "estimate": 22.4,
      "low": 19.1,
      "high": 24.7,
      "unit": "tok/s",
      "confidence": 0.74,
      "confidence_label": "medium",
      "evidence_count": 6,
      "reason_codes": ["same_backend", "same_checkpoint", "same_accelerator_model"],
      "warnings": []
    },
    "ttft_p50_ms": {
      "estimate": 910.0,
      "low": 830.0,
      "high": 1080.0,
      "unit": "ms",
      "confidence": 0.71,
      "confidence_label": "medium",
      "evidence_count": 5,
      "reason_codes": ["same_backend", "same_family"],
      "warnings": ["sparse_evidence"]
    }
  },
  "similar_results": [
    {
      "similarity_score": 0.91,
      "coverage": 0.88,
      "reason_codes": ["same_backend", "same_checkpoint", "same_accelerator_model"],
      "result": {
        "result_id": "qb_...",
        "checkpoint_name": "Qwen2.5-7B-Instruct",
        "comparison_grade": "official_eligible"
      }
    }
  ],
  "limitations": [
    "No exact accelerator-model matches were found, so hardware-specific performance could differ materially."
  ]
}
```

## Error Cases

### Missing target

If neither `run_config_id` nor `target` is provided:

```json
{
  "detail": "run_config_id or target is required"
}
```

### Unknown run config

If `run_config_id` does not exist:

```json
{
  "detail": "run config not found"
}
```

### Unsupported metrics

If a request includes unsupported metric names:

```json
{
  "detail": "unsupported metrics: ..."
}
```

## Design Notes

- This endpoint is public and read-only.
- It is intentionally machine-friendly.
- Similar results are first-class so agents can inspect evidence instead of treating the estimate as opaque truth.
- Confidence should be interpreted as evidence quality for this target, not as a universal model-accuracy guarantee.
