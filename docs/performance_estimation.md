# Performance Estimation

## Why This Exists

InferGrade should not only tell people what happened in past benchmark runs. It should also help them answer a practical pre-run question:

> If I run this model, quant, and backend on my machine, what performance should I expect?

That is useful for both humans and agents:

- humans can decide whether a run is worth the time and cost
- agents can plan, compare, and schedule runs before they execute them
- the web app can preview likely throughput and latency before asking someone to contribute data

## Product Goal

The first estimator should be:

- useful before a run
- honest about uncertainty
- grounded in trusted historical InferGrade evidence
- interpretable enough that we can explain why it made a prediction

It should not pretend to be a perfect tok/s oracle.

## What We Predict

The first implementation predicts:

- `decode_tokens_per_second_p50`
- `ttft_p50_ms`
- `load_time_ms`

These are the most decision-relevant deployment metrics we already collect and normalize.

## Why Not Pure KNN

Plain nearest-neighbor lookup is a decent baseline, but it is not enough on its own.

Problems with pure KNN:

- it is too brittle when community data is sparse
- it does not generalize well across nearby model scales
- it treats all neighbors as equally trustworthy unless we add explicit weighting
- it does not naturally explain why a result was chosen beyond “it was close”

## Chosen Approach

The first estimator is a trust-aware hybrid:

1. Build a candidate pool from real historical InferGrade results.
2. Compute similarity across target features such as:
   - backend
   - execution mode
   - use case
   - deployment profile
   - model family and checkpoint
   - parameter scale
   - quantization family and scheme
   - weight precision
   - accelerator vendor, model, VRAM, and memory
3. Weight those neighbors by:
   - feature similarity
   - feature coverage
   - verification level
   - comparison grade
   - measured run count
4. Apply lightweight heuristic adjustments before aggregation:
   - parameter-scale adjustment
   - weight-precision adjustment
5. Aggregate into:
   - point estimate
   - low/high confidence band
   - confidence score
   - supporting similar runs

This gives us something more robust than plain KNN while staying interpretable and dependency-light.

## Why This Fits InferGrade

This approach matches our principles:

- it uses structured ontology and hardware metadata we already capture
- it rewards verified and comparable evidence more than weak evidence
- it can degrade gracefully when the catalog is sparse
- it exposes similar runs and reason codes instead of hiding behind a black box

## Current Feature Inputs

The first estimator uses these target dimensions when available:

- `backend_engine`
- `execution_mode`
- `use_case`
- `deployment_profile_id`
- `family_name`
- `checkpoint_name`
- `parameter_scale`
- `training_stage`
- `quantization_family`
- `quantization_scheme`
- `weight_precision_bits`
- `accelerator_type`
- `accelerator_vendor`
- `accelerator_model`
- `accelerator_vram_gb`
- `memory_gb`
- `machine_model`

## Trust Weighting

Neighbor importance is increased by:

- higher verification level
- higher comparison grade
- more measured runs

This means a verified, comparable, repeated run should influence estimates more than a single weak or experimental record.

## Returned Evidence

Every estimate should return:

- the normalized target
- per-metric estimates
- confidence bands
- confidence labels
- similar supporting results
- machine-readable reason codes
- limitations/caveats

This is important because we want agents and humans to be able to decide whether to trust the estimate.

## Current Limitations

- It is still a heuristic estimator, not a learned regression model.
- It depends heavily on telemetry completeness in the catalog.
- It is better when backend and hardware matches exist.
- Apple Silicon predictions still inherit our current unified-memory approximation.
- Cloud prices and provider plans remain separate from this estimator.

## Planned Evolution

If InferGrade gathers enough high-quality evidence, the next step should be:

1. keep this similarity model as an explanation layer
2. add a learned correction model on top
3. calibrate confidence empirically
4. optionally tighten estimates after a tiny calibration canary run

That path preserves interpretability while improving accuracy over time.
