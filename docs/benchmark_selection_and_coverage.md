# Benchmark Selection And Capability Coverage

Sprint 58 keeps benchmark expansion narrow and makes the existing selection model easier to trust.

## Decision Vs Reference

- Decision checks are the short local path. They are meant to answer whether a quantized setup is worth running on this hardware for this use case.
- Reference checks are deeper evidence. They are useful for quant ladders, close calls, and stronger comparison confidence, but they should be selected intentionally.

Runner-owned selection metadata now includes:

- scope guidance for decision/reference selections
- expected duration, token volume, effort, and metadata confidence
- selected decision and reference check IDs
- missing core evidence states for deployment, capability, and fidelity
- next actions that treat unselected evidence as a coverage gap, not as a failed or zero score

## Planned Benchmarks

The catalog includes planned candidates only as planning metadata. They are not executable checks and must not be shown as completed evidence:

- `arena_hard_local_reference_v1` for preference-style assistant quality
- `repo_edit_smoke_v1` for small repository editing tasks
- `multiturn_chat_memory_v1` for continuity and instruction retention

These should become executable only after fixture design, scoring policy, runtime cost, and provenance are reviewed.
