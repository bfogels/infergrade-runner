# InferGrade Runner 0.3.25

Runner 0.3.25 publishes contract `0.3.19` and makes exact benchmark-protocol equivalence auditable for Capability protocol v3.1.

## Protocol identity

- records a SHA-256 identity for every scored capability check, binding its exact inputs, scoring implementation, generation contract, and capability registry version
- records an aggregate identity only when every scored check has an exact Runner-authored identity
- adds a fail-closed real-bundle release gate that recomputes component and aggregate fingerprints and requires complete selected-suite coverage

## Local capability execution

- reuses one managed `llama-server` process across native capability cases instead of reloading the model for every prompt
- applies the same server reuse to raw completion prompts used by container-backed capability checks
- preserves per-task generation status, timing, and token observations while substantially reducing repeated model-load overhead

## Evidence boundary

Exact protocol identity proves that two observations used the same benchmark protocol; it does not prove repeatability, benchmark quality, cross-hardware equivalence, or model capability. Existing bundles without Runner-authored identities remain usable as observations but cannot support an exact-repeat claim.
