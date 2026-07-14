# Coverage Expansion v0.3.5

Status: capstone metadata for the v0.3 capability beta. This document records what coverage should expand next and what remains blocked.

## Expansion Rule

Expand coverage only where it improves a setup answer:

- compare nearby quants for the same family and hardware;
- replace static estimates with observed local duration, token volume, failure rate, and repeatability;
- add missing assistant, coding, reasoning, or quant-fidelity evidence when it changes the recommended next benchmark;
- keep unsupported Windows/NVIDIA claims blocked until hardware proves the full loop.

## Current Priorities

The machine-readable priorities live in `schemas/capability_catalog.json` under `coverage_expansion_priorities`.

1. Apple Silicon assistant quant ladder for Qwen2.5 Q4/Q5/Q6 with deployment, chat-memory, and quant-fidelity evidence.
2. Apple Silicon Qwen3 Q4 assistant baseline with the explicit deterministic direct-answer preset, deployment, chat-memory, and same-family quant-fidelity evidence.
3. Apple Silicon coding ladder for Qwen2.5-Coder with deployment, HumanEval+, and MBPP+ evidence.
4. Apple Silicon reasoning sample for Qwen2.5 with exact-answer and sampled MMLU-Pro evidence.
5. Windows/NVIDIA CUDA beta gate for one known-good Qwen2.5 Q4 path after hardware is available.

## Known Gaps

- The v0.3.1 dogfood run yielded only partial local bundles and did not create a complete production `agent_dogfood` corpus import.
- Static catalog duration and token-volume estimates still need observed replacement for most reference lanes.
- Coding evidence has executable HumanEval+/MBPP+ lanes, but no repo-edit, SWE-bench, LiveCodeBench, or gold evidence.
- Reasoning evidence has exact-answer and sampled MMLU-Pro lanes, but no GPQA or gold reasoning proof.
- Quant fidelity is same-family only; it must not be used as a cross-family quality ranking.
- Windows/NVIDIA remains hardware-blocked until one install or selection, pair, GGUF run, upload, Result review, and support export loop is proven.

## v0.4 Consumption

v0.4 should consume this map in Hub by showing which setup questions have decision-grade evidence, which have thin or missing evidence, and which benchmark would most improve the answer. Do not convert `coverage_expansion_priorities` into public support claims without real corpus evidence.
