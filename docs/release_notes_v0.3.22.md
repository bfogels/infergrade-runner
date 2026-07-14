# InferGrade Runner 0.3.22

Runner 0.3.22 introduced the saturation-resistant assistant scoring contract that is now publicly named Capability protocol v3.1. Its internal compatibility identifier remains `local_assistant_score_v4`, and this historical release published contract `0.3.16`.

## Capability headroom

- replaces the 12-case compositional fixture with 24 pinned strict-JSON tasks spanning dependency, reconciliation, allocation, interval, policy, and state-machine operations
- retains raw benchmark attainment and labels a suite ceiling as a benchmark limit, never model perfection
- adds a corpus-level calibration audit with minimum diversity and explicit ceiling-rate and family-concentration gates
- keeps component calibration separate from full composite-score calibration

## Request correctness

- preserves an explicitly requested benchmark tier when a request names concrete checks
- prevents `tier: standard` single-check calibration requests from silently shrinking to canary depth

## Evidence boundary

The v4 assistant index remains provisional until publication-ready IFEval plus compositional results pass the declared cross-model distribution gate. Existing legacy and v1 scores are not comparable with v4.
