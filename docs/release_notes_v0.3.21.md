# InferGrade Runner 0.3.21

Runner 0.3.21 replaces a saturated assistant-score component and publishes contract `0.3.15`.

## Capability benchmark changes

- Assistant score v3 is a benchmark-attainment index, not a model grade or global intelligence score.
- The saturated multi-turn memory microcheck remains visible as zero-weight diagnostic evidence.
- A 12-case compositional instruction-following fixture replaces memory in the weighted assistant surface.
- Assistant headline publication requires standard-tier depth, complete weighted coverage, two scored components, and two score dimensions.
- A maximum must be presented as `Suite ceiling reached`, never as model perfection.

## Calibration boundary

The new compositional fixture produced different strict scores for the three locally sampled models, while the previous memory check remained at its ceiling for the two larger models. This is useful early discrimination evidence, not broad calibration proof. The fixture remains provisional until a wider cross-family and cross-quant distribution is collected and reviewed.

This release does not claim that one model is globally better than another, does not promote the benchmark to gold evidence, and does not expand supported hardware or runtime tiers.
