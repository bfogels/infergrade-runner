# V0 Decision Workflow

InferGrade Runner is the open execution engine for one focused first-user question:

> Which quantized model setup should I run on my hardware for this use case?

The Runner answers the execution side of that question. It resolves artifacts, checks readiness, runs benchmarks, captures environment provenance, and writes normalized bundles the Hub can compare.

## Runner Responsibilities In V0

- resolve a pinned quantized artifact
- choose the correct local execution path for the hardware
- run short decision-suite checks first
- capture deployment telemetry, capability state, hardware, runtime, and artifact identity
- preserve failed, skipped, partial, and degraded states instead of flattening them into missing data
- emit portable run output that remains useful without a hosted Hub

## Supported First Path

- Backend: `llama.cpp`
- Artifact: GGUF quantized weights
- Apple Silicon: `local_native` so Metal-backed inference is measured
- Container-friendly hosts: `local_container` with explicit runtime images
- Hub-assisted workflow: pair once, start the runner, then let the Hub queue local work

## Deferred In V0

- treating every backend as equally supported
- making cloud required for first value
- broad reference-suite validation as the default
- hiding unsupported or degraded execution paths behind optimistic labels

The Hub guides setup and comparison. The Runner owns execution truth.
