# InferGrade Schema Draft

## Purpose

This document proposes the first concrete draft for:

- the portable run bundle produced by the InferGrade runner,
- the profile-level normalized result records used for filtering and recommendations,
- and the minimum metadata required for reproducibility, cost capture, and canonical analysis.

This is a draft, not a frozen spec.

## Design Goals

The schema should:

- support local and cloud execution,
- preserve raw evidence,
- distinguish exact deployable configurations,
- separate capability results from deployment telemetry,
- capture both inference cost and benchmark execution cost,
- and support automatic recommendation and Pareto-frontier computation.

## Proposed Run Bundle Layout

```text
infergrade-run/
  manifest.json
  results/
    interactive_chat_v1.json
    batch_generation_v1.json
  validation.json
  artifacts/
    environment.json
    backend_stdout.log
    backend_stderr.log
    deployment_metrics.json
    capability/
      suite_manifest.json
      raw_results.json
    receipts/
      run_facts.json
  provenance/
    model_artifact.json
    backend_config.json
    hardware_snapshot.json
```

## Bundle Rules

- `manifest.json` is required.
- `results/` is required.
- `validation.json` is optional during local execution, but required for uploaded bundles.
- `artifacts/environment.json` is required.
- one bundle may contain multiple profile-level result records.

## Manifest Draft

```json
{
  "bundle_spec_version": "0.1-draft",
  "result_spec_version": "0.1-draft",
  "bundle_id": "qb_2026_03_24_abc123",
  "created_at": "2026-03-24T20:12:00Z",
  "runner": {
    "name": "infergrade",
    "version": "0.1.0-draft"
  },
  "status": {
    "execution_status": "completed",
    "deployment_status": "completed",
    "capability_status": "completed",
    "validation_status": "warning"
  },
  "files": {
    "results": [
      "results/interactive_chat_v1.json",
      "results/batch_generation_v1.json"
    ],
    "validation": "validation.json",
    "environment": "artifacts/environment.json"
  }
}
```

## Result Record Draft

Each file in `results/` should be a normalized product-facing record.

## Proposed Top-Level Shape

```json
{
  "spec_version": "0.1-draft",
  "bundle_id": "qb_2026_03_24_abc123",
  "result_id": "qb_2026_03_24_abc123_interactive_chat_v1",
  "configuration": {},
  "hardware": {},
  "verification": {},
  "execution": {},
  "capability": {},
  "deployment": {},
  "cost": {},
  "derived": {},
  "provenance": {}
}
```

## Section Drafts

### `configuration`

Suggested fields:

- `configuration_id`
- `model_base`
- `model_variant`
- `model_instance_name`
- `model_source`
- `model_source_repo`
- `model_revision`
- `quant_label`
- `quant_format`
- `quant_artifact_sha256`
- `backend_engine`
- `backend_wrapper`
- `backend_version`
- `backend_execution`
- `backend_flags`
- `tokenizer_id`
- `chat_template_id`
- `generation_preset_id`

### `hardware`

Suggested fields:

- `hardware_id`
- `environment_class`
- `accelerator_type`
- `accelerator_vendor`
- `accelerator_model`
- `accelerator_vram_gb`
- `accelerator_count`
- `cpu_model`
- `memory_gb`
- `os`
- `driver_versions`
- `container_runtime`

### `verification`

Suggested fields:

- `verification_level`
- `local_comparison_grade_candidate`
- `artifact_pinned`
- `backend_version_pinned`
- `container_pinned`
- `hardware_captured`
- `repeated_runs`
- `variance_captured`
- `run_bundle_sha256`
- `missing_requirements`
- `validation_warnings`

Draft note:

- final `comparison_grade` should be server-confirmed rather than treated as final local truth.

### `execution`

Suggested fields:

- `execution_profile_id`
- `execution_mode`
- `launcher`
- `cloud_provider`
- `cloud_region`
- `cloud_instance_type`
- `started_at`
- `completed_at`
- `benchmark_job_runtime_seconds`
- `execution_cost_source`
- `benchmark_job_cost_usd`
- `cost_measurement_method`

### `capability`

Suggested fields:

- `use_case`
- `capability_suite_id`
- `benchmark_tier`
- `benchmark_components`
- `capability_score`
- `capability_score_method`
- `capability_component_scores`
- `capability_confidence`
- `capability_status`

Draft note:

- capability may be omitted for `canary` runs or when explicitly disabled.
- runnable local capability evidence should also emit a `capability_run` artifact when the runner owns the benchmark protocol.

## Capability Run Artifact

`result_record.schema.json` is the product-facing normalized result shape. `capability_run.schema.json` is the Runner-owned local benchmark artifact shape.

The capability artifact is distinct from `native_first_run`. It captures:

- evidence lane: `smoke`, `decision`, `reference`, or `gold`
- capability surface: `local_assistant_capability`, `local_coding_capability`, `local_reasoning_capability`, `quant_fidelity`, or `deployment_fitness`
- task family, prompt/task metadata, fixture or dataset revision, scorer type, scoring policy, and repetitions
- model, runtime, hardware, and generation-preset provenance
- task states: `scored`, `partial`, `failed`, `skipped`, `not_yet_benchmarked`, or `not_comparable`
- duration, TTFT, tokens/sec, input tokens, and output tokens when available
- raw output artifact paths, scoring output paths, and explicit supported/unsupported claims

This artifact should be useful before any Hub upload or import. Hub can summarize it, but Runner owns execution truth.

### `deployment`

Suggested fields:

- `deployment_profile_id`
- `prompt_profile_id`
- `context_length_bucket`
- `batch_size`
- `concurrency`
- `warmup_runs`
- `measured_runs`
- `ttft_p50_ms`
- `latency_p50_ms`
- `decode_tokens_per_second_p50`
- `peak_vram_mb`
- `load_time_ms`
- `deployment_confidence`
- `deployment_status`

### `cost`

Suggested fields:

- `cost_source`
- `hourly_rate_usd`
- `runtime_seconds`
- `usd_per_run`
- `usd_per_1m_output_tokens`
- `benchmark_job_cost_usd`

### `derived`

Suggested fields:

- `passes_capability_floor`
- `passes_verification_floor`
- `canonical_analysis_slice_ids`
- `frontier_group_id`
- `is_pareto_frontier_member`
- `comparison_grade`
- `recommendation_labels`
- `dominated_by`

Draft note:

- `comparison_grade` should be filled by the server or authoritative aggregator.

### `provenance`

Suggested fields:

- `submitter`
- `submission_channel`
- `source_bundle_origin`
- `normalized_at`
- `normalizer_version`

## Validation Draft

Suggested shape:

```json
{
  "valid": true,
  "errors": [],
  "warnings": [],
  "verification_level": "verified",
  "comparison_grade": "official_eligible"
}
```

## Draft Decisions Embedded Here

- one bundle may contain multiple profile-level result records
- each result record is the primary unit for analysis
- capability may be skipped for `canary`
- `standard` and `gold` should generally require explicit `use_case` unless capability is disabled
- `comparison_grade` should be server-confirmed

## Questions To Refine Together

1. Should benchmark execution cost exist only in `execution`, with `cost` reserved for deployment economics? For local v0.2.x work, record objective duration and token facts first rather than inventing local dollar-cost estimates.
2. Should one result record support exactly one `use_case`?
3. Should there be a bundle-level summary file in addition to per-profile results?
