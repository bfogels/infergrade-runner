# InferGrade Runner 0.3.26

Runner 0.3.26 publishes contract `0.3.20` and makes the Capability protocol v3.1 calibration campaign recent-model-first and resistant to repeat farming.

## Current-model campaign

- leads zero-demand work with exact Qwen3.5 9B, Gemma 4 E4B, Ministral 3 3B, Qwen3 8B, and Qwen3 0.6B repeat anchors
- records Qwen3.6 27B, Gemma 4 12B, Ministral 3 8B, and Qwen3.5 4B as gated expansion targets without claiming they are runnable before artifact, fit, runtime, and protocol canaries pass
- retains Qwen2.5 only as demand-driven historical control evidence rather than a default calibration target

## Calibration composition

- still requires 20 observations, five families, three parameter bands, six distinct scores, and bounded ceiling/family concentration
- additionally requires eight exact model-plus-quant setups, four independently replicated setups, and at least 75% current/recent campaign evidence
- prevents any single exact setup from exceeding 25% of the calibration corpus
- lets the audit CLI read both full result records and compact normalized result briefs

## Evidence boundary

These gates evaluate distribution breadth, repeat coverage, model recency, and suite headroom. They do not rescale raw attainment, prove psychometric calibration, certify every listed model/runtime combination, or turn a suite-ceiling result into a claim of model perfection.
