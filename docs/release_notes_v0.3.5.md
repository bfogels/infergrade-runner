# InferGrade Runner v0.3.5 Release Notes

## Summary

Runner v0.3.5 closes the v0.3 capability beta with an explicit coverage-expansion map and known-gaps document. It does not add broad benchmark claims or mark Windows/NVIDIA as proven.

## Contract Changes

- The capability catalog now includes `coverage_expansion_priorities`, a machine-readable list of the highest-leverage model, quant, hardware, use-case, and benchmark gaps for the answer loop.
- The contract bundle includes `docs/coverage_expansion_v0_3_5.md` so Hub can explain missing evidence without inventing Runner semantics.

## Evidence Boundaries

- Apple Silicon remains the calibrated reference path, but the dogfood corpus is still partial.
- Coding, reasoning, and quant-fidelity lanes stay separate; no global score is introduced.
- Windows/NVIDIA CUDA remains hardware-blocked and preflight-only until one full loop is proven on real hardware.

## Validation

The coverage priorities are validated against declared benchmark checks by the benchmark catalog tests.
