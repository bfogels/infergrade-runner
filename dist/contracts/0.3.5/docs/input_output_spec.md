# InferGrade Input / Output Spec

## Purpose

This document defines the operator-facing inputs and runner-generated outputs for InferGrade Runner.

The core design rule is:

- humans provide a small run request
- the runner generates the full reproducible bundle

This keeps operator friction low while preserving strong metadata capture and analysis quality.

## Design Principles

### 1. Minimal Operator Burden

The operator should provide only the information the runner cannot safely infer.

### 2. Rich Machine Output

The runner should automatically capture as much metadata as possible.

### 3. Reproducibility by Default

Pinned versions, captured environment details, and normalized outputs should be produced automatically.

### 4. Graceful Degradation

If some metadata cannot be captured, the run should still complete when possible, but verification and comparison quality should degrade accordingly.

### 5. Ontology First

InferGrade should separate model lineage, quantization, artifact identity, runtime binding, and benchmark subject. The operator should not need to fill most of that out manually, but the runner output should always normalize onto that ontology.

## Product Contract

InferGrade has two contracts:

### Operator Input Contract

What a human or automation provides to request a run.

### Runner Output Contract

What InferGrade emits after executing the run.

## Operator Input Contract

There are two supported input modes:

1. CLI flags
2. `run_request.yaml`

The CLI is the primary UX. `run_request.yaml` exists for repeatable runs, automation, and batch jobs.

## Minimal CLI

```bash
infergrade run \
  --model Qwen/Qwen2.5-7B-Instruct \
  --backend llama.cpp \
  --tier canary
```

This should be the lowest-friction happy path.

## Extended CLI

```bash
infergrade run \
  --model Qwen/Qwen2.5-7B-Instruct \
  --quant-artifact hf://bartowski/Qwen2.5-7B-Instruct-GGUF/qwen2.5-7b-instruct-q4_k_m.gguf \
  --backend llama.cpp \
  --tier standard \
  --use-case general_assistant \
  --deployment-profile interactive_chat_v1 \
  --execution-mode local_container \
  --output ./runs/qwen25-chat
```

## Required Operator Inputs

The required operator-facing inputs should be:

- `model`
- `backend`
- `tier`

That is the intended minimum.

## Optional Operator Inputs

The operator may optionally provide:

- `quant_artifact`
- `quant_artifact_sha256`
- `quant_artifact_filename`
- `quant_artifact_revision`
- `ontology_hints`
- `use_case`
- `deployment_profile`
- `execution_mode`
- `output`
- `upload`
- `backend_flags`
- `generation_preset`
- `cloud_provider`
- `cloud_instance_type`
- `backend_image`
- `artifact_cache_dir`
- `cost_source`
- `capability`

If omitted, the runner should infer or default these where possible.

`ontology_hints` are intentionally optional. They exist primarily for server-issued run configs and curated benchmark programs that know more about lineage than the bare model string reveals.

## Self-Contained Artifact Contract

`run_request.yaml` and run configs may also include:

- `artifacts.quantized_weights.uri`
- `artifacts.quantized_weights.sha256`
- `artifacts.quantized_weights.filename`
- `artifacts.quantized_weights.revision`
- `runtime.backend_image`
- `runtime.artifact_cache_dir`

This is the highest-leverage path for low-friction execution. It lets InferGrade fetch and cache the artifact automatically rather than requiring the operator to stage a local file by hand.

One important rule:

- `use_case` may be omitted for `canary`
- `use_case` should be required for `standard` and `gold` unless capability execution is explicitly disabled

## CLI Field Specification

### `--model`

Required.

Meaning:

- base model reference or source identifier.

### `--backend`

Required.

Allowed draft values:

- `llama.cpp`
- `vllm`

Future values may include wrapper backends such as `ollama`.

### `--tier`

Required.

Allowed values:

- `canary`
- `standard`
- `gold`

### `--quant-artifact`

Optional.

Meaning:

- exact quantized artifact reference if the operator wants a specific artifact.

If omitted:

- the runner may resolve a default artifact based on backend compatibility and policy,
- but the run should degrade in comparison quality if the exact artifact cannot be pinned.

## Optional `ontology_hints`

`run_request.yaml` and server-issued run configs may include an `ontology_hints` object.

This is not intended to add operator burden. It exists so a trusted config issuer can clarify:

- family identity
- checkpoint identity
- training stage
- quantization family or scheme
- parameter scale

The runner should treat these as hints, not as a replacement for captured execution metadata.

### `--use-case`

Optional for `canary`. Required for `standard` and `gold` unless capability execution is explicitly disabled.

Allowed draft values:

- `agentic_coding`
- `general_assistant`

If omitted:

- for `canary`, the runner may skip capability benchmarks and collect deployment telemetry only
- for `standard` and `gold`, the runner should fail validation unless `--capability none` is supplied

### `--deployment-profile`

Optional.

Allowed draft values:

- `interactive_chat_v1`
- `batch_generation_v1`
- `long_context_v1`

If omitted:

- the runner should choose defaults based on the selected use case and tier.

Multiple deployment profiles may be requested in one run request.

### `--execution-mode`

Optional.

Allowed draft values:

- `local_container`
- `cloud_container`
- `manual_external`

Default:

- `local_container`

### `--output`

Optional.

Meaning:

- target directory for the run bundle.

### `--upload`

Optional boolean.

Meaning:

- request upload after local validation succeeds.

Default:

- false

### `--backend-flags`

Optional repeatable flag or structured string.

Meaning:

- explicit backend runtime overrides.

If omitted:

- InferGrade should use backend-specific safe defaults for the chosen profile.

### `--generation-preset`

Optional.

Meaning:

- named decoding preset for reproducible runs.

Default:

- InferGrade default preset for the selected benchmark type.

### `--cloud-provider`

Optional.

Used mainly for `cloud_container`.

### `--cloud-instance-type`

Optional.

Used mainly for `cloud_container`.

### `--cost-source`

Optional.

Allowed draft values:

- `observed`
- `billing_import`
- `user_provided`
- `estimated`
- `none`

### `--capability`

Optional.

Allowed draft values:

- `auto`
- `none`

Default behavior:

- `canary`: `auto`, which may resolve to deployment-only if `use_case` is omitted
- `standard` and `gold`: `auto`, but requires `use_case` unless explicitly set to `none`

## `run_request.yaml` Specification

This is the structured equivalent of the CLI.

## Minimal Example

```yaml
spec_version: "0.1-draft"

run:
  model: Qwen/Qwen2.5-7B-Instruct
  backend: llama.cpp
  tier: canary
```

## Full Example

```yaml
spec_version: "0.1-draft"

run:
  model: Qwen/Qwen2.5-7B-Instruct
  quant_artifact: hf://bartowski/Qwen2.5-7B-Instruct-GGUF/qwen2.5-7b-instruct-q4_k_m.gguf
  backend: llama.cpp
  tier: standard
  use_case: general_assistant
  deployment_profiles:
    - interactive_chat_v1
    - batch_generation_v1
  execution_mode: local_container
  upload: false

overrides:
  backend_flags:
    - --n-gpu-layers=99
  generation_preset: deterministic_v1

cost:
  source: estimated

metadata:
  submitter: github:example-user
```

## `run_request.yaml` Fields

### Top Level

- `spec_version`
- `run`
- `overrides` optional
- `cost` optional
- `metadata` optional

### `run`

Required fields:

- `model`
- `backend`
- `tier`

Optional fields:

- `quant_artifact`
- `use_case`
- `deployment_profiles`
- `execution_mode`
- `output_dir`
- `upload`
- `capability`

### `overrides`

Optional.

Allowed fields:

- `backend_flags`
- `generation_preset`
- `chat_template_id`
- `tokenizer_id`
- `warmup_runs`
- `measured_runs`

Rule:

- overrides should be used sparingly and should reduce comparison quality if they materially diverge from canonical defaults.

### `cost`

Optional.

Allowed fields:

- `source`
- `hourly_rate_usd`
- `job_cost_usd`
- `notes`

### `metadata`

Optional.

Allowed fields:

- `submitter`
- `notes`
- `tags`

## Runner Defaulting Rules

The runner should fill in the following automatically when missing:

- hardware snapshot
- OS, driver, and container metadata
- backend version
- container image and digest when available
- tokenizer and chat template if inferable
- generation preset default
- deployment profile defaults from `use_case` and `tier`
- bundle id
- validation outputs
- profile-level result records

## Runner Resolution Rules

### Model Resolution

If the operator provides `model` but not `quant_artifact`:

- the runner may resolve a compatible artifact,
- must record exactly how that resolution occurred,
- and must store the final pinned artifact identity in outputs.

### Profile Resolution

If no deployment profile is supplied:

- `general_assistant` should default to `interactive_chat_v1`
- `agentic_coding` should default to `interactive_chat_v1` and `long_context_v1`
- no use case should default to a minimal deployment telemetry profile only

### Capability Resolution

If no use case is supplied:

- `canary` may skip capability benchmarks and proceed with deployment telemetry only
- `standard` and `gold` should fail validation unless capability is explicitly disabled

If `capability` is `none`:

- the runner should skip capability benchmarks
- the run should remain valid
- comparison quality should degrade accordingly

## Runner Output Contract

The runner should always emit a run bundle directory.

## Output Bundle Layout

```text
infergrade-run/
  manifest.json
  results/
    interactive_chat_v1.json
    batch_generation_v1.json
  validation.json
  artifacts/
    environment.json
    ontology.json
    deployment_metrics.json
    capability/
      raw_results.json
    receipts/
      cost_evidence.json
  provenance/
    model_artifact.json
    backend_config.json
    hardware_snapshot.json
```

Rule:

- one run request may produce multiple result records
- each result record should correspond to one deployment profile and one comparison unit

## Required Output Files

- `manifest.json`
- `results/`
- `artifacts/environment.json`
- `artifacts/ontology.json`
- `artifacts/receipts/artifact_resolution.json` when artifact resolution occurred

## Conditionally Required Output Files

- `artifacts/deployment_metrics.json`
  Required if any deployment profile was executed.

- `artifacts/capability/raw_results.json`
  Required if any capability suite was executed.

- `artifacts/receipts/cost_evidence.json`
  Required only when direct or imported cost evidence exists.

- `artifacts/receipts/artifact_resolution.json`
  Required when the runner resolved a non-local artifact reference or verified a local artifact for real execution.

## `manifest.json` Required Fields

- `bundle_spec_version`
- `result_spec_version`
- `bundle_id`
- `created_at`
- `runner.name`
- `runner.version`
- `status.execution_status`
- `files.results`
- `files.environment`
- `files.ontology`

## Result Record Contract

Each file in `results/` should be a profile-specific normalized result record.

Top-level required fields:

- `spec_version`
- `bundle_id`
- `result_id`
- `ontology`
- `configuration`
- `hardware`
- `verification`
- `execution`
- `cost`
- `provenance`

Conditionally required:

- `deployment`
  Required if a deployment profile ran.

- `capability`
  Required if a capability suite ran.

- `derived`
  Required after normalization; may be partial before upload.

## Required Result Fields By Section

### `ontology`

Required:

- `ontology_version`
- `model_family`
- `checkpoint`
- `quantization`
- `artifact`
- `runtime_binding`
- `benchmark_subject`

This is the normative identity layer for InferGrade outputs. Other sections may repeat convenience fields, but ontology should be treated as the authoritative semantic model of what was benchmarked.

### `configuration`

Required:

- `configuration_id`
- `model_base`
- `model_source`
- `backend_engine`
- `backend_version`

### `hardware`

Required:

- `hardware_id`
- `environment_class`
- `accelerator_type`
- `accelerator_count`
- `os`

### `verification`

Required:

- `verification_level`
- `artifact_pinned`
- `backend_version_pinned`
- `hardware_captured`
- `missing_requirements`

Recommended:

- `local_comparison_grade_candidate`

### `execution`

Required:

- `execution_profile_id`
- `execution_mode`
- `started_at`
- `completed_at`
- `benchmark_job_runtime_seconds`
- `execution_cost_source`

### `capability`

Required if present:

- `use_case`
- `capability_suite_id`
- `benchmark_tier`
- `benchmark_components`
- `capability_status`

### `deployment`

Required if present:

- `deployment_profile_id`
- `deployment_status`
- `warmup_runs`
- `measured_runs`

### `cost`

Required:

- `cost_source`
- `benchmark_job_cost_included`

### `derived`

Required after normalization:

- `passes_verification_floor`

Server-confirmed when uploaded:

- `comparison_grade`

### `provenance`

Required:

- `source_bundle_origin`
- `normalized_at`
- `normalizer_version`

## Comparison Grade Authority

`comparison_grade` should be server-confirmed, not treated as final local truth.

Recommended behavior:

- runner emits `local_comparison_grade_candidate`
- server validates the uploaded bundle
- server assigns final `comparison_grade`

## Reproducibility Guarantees

### Strong Reproducibility

Possible when:

- exact quant artifact is pinned
- backend version is pinned
- container image is pinned
- deployment profile is canonical
- generation preset is canonical
- repeated runs are performed

### Moderate Reproducibility

Possible when:

- some environment fields are missing
- cost is estimated rather than observed
- capability harness versions are pinned but cloud hardware may vary

### Informational Only

Applies when:

- artifact identity is incomplete
- backend or environment capture is incomplete
- operator overrides materially weaken comparability

## Friction-Minimizing Rules

To keep operator burden low, the runner should:

- never require the full schema as input
- auto-capture hardware and environment data
- auto-generate ids
- auto-write all output files
- auto-run validation
- auto-estimate cost when direct cost evidence is unavailable
- auto-select defaults from `use_case` and `tier`

## Open Refinement Questions

1. Should `benchmark_job_cost_usd` live only in `execution`, with `cost` reserved for deployment economics?
2. Should one result record support multiple use cases, or exactly one?
3. Should a bundle-level summary file exist in addition to per-profile results?
