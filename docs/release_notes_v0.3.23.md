# InferGrade Runner 0.3.23

Runner 0.3.23 publishes contract `0.3.17` and gives the saturation-resistant assistant methodology its public name: **Capability protocol v3.1**.

## Protocol naming

- emits `protocol_version: 3.1` and `protocol_label: Capability protocol v3.1` in Runner-owned score metadata
- carries the protocol name into capability summaries and the exported contract
- keeps `local_assistant_score_v4` as an internal compatibility identifier so equivalent 0.3.22 evidence remains in the same comparable cohort

## Evidence boundary

This release does not alter tasks, weights, raw benchmark attainment, ceiling behavior, or calibration gates. Existing bundles are not rewritten. Capability protocol v3.1 remains provisional until its declared cross-model distribution audit passes.
