# InferGrade Runner v0.3.14 Release Notes

## Summary

Runner v0.3.14 makes bounded autonomous user-contributed benchmarking safe enough for the private-beta contribution loop. It does not release v1.0.0, broaden public-launch claims, or turn fixed-budget generation into capability evidence.

## Contract Changes

- Contract `0.3.10` lets an authorized Hub declare the exact expected artifact download size. Runner enforces that size for local files, cache hits, concurrent cache winners, and streamed remote downloads.
- Deployment results record output-token percentiles, natural-stop rate, token-budget-exhaustion rate, and an explicit boundary that these metrics do not prove semantic task completion.
- Run requests may specify bounded deployment warmup and measured iteration counts independently of evidence breadth.
- The catalog adds an explicit deployment-only evidence lane for repeatable performance measurements without rerunning capability or perplexity work.

## Evidence Boundaries

- Visible output that reaches a token budget remains usable as throughput evidence, but `semantic_task_completion_proof` stays false.
- Capability task-time remains the scored task-completion surface.
- Sampled MMLU-Pro direct answers use a strict denominator and preserve partial/invalid states.
- Existing requests remain compatible, including legacy resume fingerprints when new optional fields are unset.

## Validation

- 455 Python tests passed on the release candidate.
- Six real M1 Pro deployment bundles completed two warmups and five measured iterations and validated successfully.
- Independent review confirmed exact artifact authority, early bounds validation, simulated/real repeat consistency, and legacy resume compatibility.
