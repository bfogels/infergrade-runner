# Benchmark integrity note — 2026-08-19

This note records a bounded local diagnostic and the resulting evidence boundary. It does not promote a benchmark, change a score version, or establish a release claim.

## Observed local evidence

- Five cached local models completed the six-case fixture at `0/6` each before quarantine.
- One 48-case fixture run completed at `0/48` before quarantine.
- These are aggregate observations only. They do not establish a reasoning capability floor, benchmark difficulty, or model ranking.

The runs used `deterministic_direct_answer_v1` with `enable_thinking=false`, `thinking_budget_tokens=0`, and a 64-token output budget. That generation policy is a validity confound for a reasoning lane: a zero score can reflect a direct-answer protocol failure rather than lack of reasoning capability.

## Quarantine and artifact boundary

`reasoning_constraint_stress_v1` is retained as a pinned fixture and scorer for forensic and unit-test artifacts, labeled `legacy_direct_no_think_v1`. It is quarantined from runnable selection, readiness, recommendation, and release evidence. Explicit selection fails closed with the stable reason code `legacy_direct_no_think_v1_no_capability_validity_evidence`.

Completed model-authored exact-answer format misses remain scored zero in the denominator and are recorded with `format_valid=false`, an `error_class`, and a model-output diagnostic count. Unscored transport/runtime failures remain partial evidence with a null task score. Terminal-stop and output-budget metadata is carried into private prediction rows and public task/summary diagnostics without prompts or outputs.

## v2 blocker

Before any successor reasoning evidence is considered, run a reasoning-capable protocol with thinking enabled and a bounded larger output budget. First require a one- or two-case proof on the exact tasks under comparison, preserving request/response metadata locally; only then run a new canary and replicated tiers. No v1 direct-no-think result is evidence for the successor protocol.
