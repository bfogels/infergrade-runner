# Release Gate

InferGrade is releasable for outside users only when the focused first-user promise works:

> Which quantized model setup should I run on this hardware for this use case?

## Gate Checklist

1. Pair a local Runner from the Hub setup flow.
2. Generate or publish a decision-suite TinyLlama config.
3. Execute locally on the supported local lane.
4. Produce `manifest.json`, `summary.json`, `validation.json`, result JSON, `progress.json`, and `report.md`.
5. Confirm the result carries benchmark scope metadata with explicit metadata confidence/source fields.
6. Upload the bundle to the Hub.
7. Confirm Compare produces a same-family quant decision summary with exact or clearly similar evidence.
8. Confirm demo evidence, if imported, stays labeled as fixture evidence and informational only.

## Suite Metadata Calibration

Current decision/reference labels are marked with:

- duration: `estimated`
- token volume: `estimated`
- failure rate: `unknown`
- calibration status: `estimated_static_catalog_v1`

That is intentionally conservative. A future calibration pass may promote specific checks to `observed` only after a reviewed real run captures wall-clock duration, token volume, and failure/degraded behavior.

## Pass/Fail Rule

The gate fails if:

- the Runner cannot emit `report.md`
- benchmark scope metadata is missing from `summary.json` or result records
- metadata source/confidence is missing or falsely presented as observed
- upload succeeds but Compare cannot form a same-family quant decision summary
- demo evidence appears indistinguishable from real uploaded evidence
