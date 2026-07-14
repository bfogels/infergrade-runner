# InferGrade Runner 0.3.24

Runner 0.3.24 publishes contract `0.3.18` and makes the next Capability protocol v3.1 calibration wave explicitly distribution-seeking.

## Calibration coverage

- adds a reviewed Qwen3 0.6B Q8 priority for the missing under-3B parameter band
- adds reviewed Ministral 3B and Gemma 4 priorities to reduce Qwen-family concentration
- keeps every candidate on the same five-check assistant scope and leaves Hub to choose an explicit sample depth
- records exact model, checkpoint, size, and quant targets so an autonomous agent cannot substitute a nearby artifact

## Evidence boundary

These are run priorities, not benchmark results. This release does not alter Capability protocol v3.1 tasks, weights, scores, calibration gates, or claim boundaries. The protocol remains provisional until real publication-ready observations pass the declared distribution audit.
