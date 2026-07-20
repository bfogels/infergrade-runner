# Changelog

Condensed release history for InferGrade Runner. Each entry lists the
user-visible changes; full evidence boundaries and validation details live in
the release PRs and tags. Versions without an entry shipped internal or
incremental changes only — see the git history.

## Unreleased (contract 0.3.23)

- Stores managed llama.cpp packages as immutable content-addressed builds, so
  installing different bytes never replaces a build already used by evidence.
- Resolves one exact native runtime lock per run attempt, preserves it across
  resume, verifies it before and after execution, and emits a path-free runtime
  receipt. Runtime preference changes and binary mutation cannot silently alter
  an in-progress run.
- Keeps content identity separate from executable-role and support assertions,
  bounds compact per-result receipts, and limits locally fingerprinted binary
  sets to community verification unless managed-package provenance is present.
- Identifies unlabeled local llama.cpp selections by the selected CLI's full
  SHA-256 digest instead of assigning the legacy Homebrew runtime identity.

## 0.3.37

- Publishes the audited Runner source and canonical container images for public use under Apache-2.0, with refreshed architecture, contribution, and release documentation.
- Hardens supply-chain maintenance with SHA-pinned Actions, read-only workflow permissions, Dependabot coverage, Ruff enforcement, CODEOWNERS, and one authoritative Rust lockfile.
- Updates vulnerable transitive dependencies and preserves explicit accepted-risk documentation for platform-scoped upstream advisories.
- Makes public releases fail closed on tag/version drift, missing signing inputs, invalid notarization credentials, or anonymously unreachable updater artifacts.
- Removes the pre-rebrand `QUANTBENCH_*` environment aliases and unused `run_quantbench` Python entrypoint; use the corresponding `INFERGRADE_*` variables and `run_infergrade`.

## 0.3.36

- Desktop assignments received while listening is paused now show one adjacent recovery action, readable model labels, and a clock that starts only when work is claimed.
- Update status begins unknown and reports `Current release` only after a successful signed-update check.
- Cold Tauri builds prepare the sidecar automatically, and bundled Python execution preserves the signed app seal after launch.
- Desktop publication fails closed until its manifest and archive are anonymously reachable from a public signed and notarized artifact origin.

## 0.3.35

- `infergrade start` fails fast when no pairing profile exists and points to the Hub pairing flow.
- `doctor`, `cache`, `install-runtime`, `pair`, `unpair`, and `start` print concise human summaries by default; complete payloads remain available via `--json`.
- Zero-config `doctor` checks the canonical native runtime on Apple Silicon or the container runtime elsewhere.
- `pair` defaults its label to the machine hostname.

## 0.3.34

- Interrupted paired runs are reported to the Hub as retryable failures instead of stranding in a running state.
- Completed capability cases are checkpointed append-only with fingerprints; exact `--resume` reuses completed cases and fails closed on protocol or integrity mismatches.

## 0.3.33 (contract 0.3.22)

- Qwen3.5 4B Q4_K_M and Ministral 3 8B Q4_K_M become reviewed-runnable Apple Silicon calibration targets after artifact, fit, runtime, and output-protocol canaries.

## 0.3.32 (contract 0.3.21)

- `execution.benchmark_job_runtime_seconds` now records the real start-to-completion interval; invalid timestamp pairs fail closed to zero.

## 0.3.31 (contract 0.3.21)

- Adds `infergrade start --autopilot` for paired `agent_dogfood` runners executing Hub-bounded benchmark grants; the grant's model, artifact, task, machine, expiry, job, and download bounds are immutable on the Runner side.
- Adds independent distribution-readiness policies for the Coding and Reasoning lanes.

## 0.3.30 (contract 0.3.20)

- Carries the MMLU-Pro malformed-output diagnostic into the compact capability component report consumed by the Hub.

## 0.3.29 (contract 0.3.20)

- Completed generations that violate the declared answer-letter format now score as incorrect under `exact_multiple_choice_letter_accuracy_v3`; generation and runtime failures stay unscored.
- Malformed-output counts are published as diagnostics with a strict completed-generation denominator.

## 0.3.28 (contract 0.3.20)

- Adds reviewed Qwen3.5-9B Apple Silicon coding (HumanEval+, MBPP+) and reasoning (exact-answer, sampled MMLU-Pro) campaign anchors; Qwen2.5 lanes become explicit historical controls.

## 0.3.27 (contract 0.3.20)

- Sampled EvalPlus runs now score the exact pinned subset they generated; missing, duplicate, or unexpected prediction IDs are rejected before scoring.
- Native `llama.cpp` fails fast when the selected model cannot load.

## 0.3.26 (contract 0.3.20)

- Calibration campaign becomes recent-model-first with anti-repeat-farming composition gates: minimum exact setups, replicated setups, recency share, and a per-setup concentration cap.

## 0.3.25 (contract 0.3.19)

- Records a SHA-256 protocol identity for every scored capability check, plus an aggregate identity and a fail-closed release gate that recomputes fingerprints.
- Reuses one managed `llama-server` process across native capability cases, removing repeated model-load overhead.

## 0.3.24 (contract 0.3.18)

- Adds reviewed calibration priorities for the under-3B band (Qwen3 0.6B Q8) and non-Qwen families (Ministral 3B, Gemma 4) with exact artifact pinning.

## 0.3.23 (contract 0.3.17)

- Names the saturation-resistant assistant methodology **Capability protocol v3.1** and emits `protocol_version` / `protocol_label` in score metadata.

## 0.3.22 (contract 0.3.16)

- Introduces the saturation-resistant assistant scoring contract (now Capability protocol v3.1): 24 pinned strict-JSON compositional tasks, corpus-level calibration audit with diversity and ceiling gates.
- Explicitly requested benchmark tiers are preserved; `tier: standard` no longer silently shrinks to canary depth for single-check requests.

## 0.3.21 (contract 0.3.15)

- Assistant score v3 becomes a benchmark-attainment index; the saturated multi-turn memory microcheck drops to zero-weight diagnostic status, replaced by a compositional instruction-following fixture.
- Suite maximums are labeled `Suite ceiling reached`, never model perfection.

## 0.3.20 (contract 0.3.14)

- Adds a proof-gated `llama.cpp` candidate intake lane: daily upstream release discovery, immutable digest pinning, and an explicit `reviewed_candidate` channel that never silently promotes.
- Supports Gemma 4 direct-answer tasks via llama-server structured chat with thinking disabled.

## 0.3.19 (contract 0.3.14)

- Qwen3.5 direct-answer capability checks use llama-server's structured chat protocol with `enable_thinking=false`, fixing budget exhaustion inside unfinished thinking blocks.

## 0.3.18 (contract 0.3.14)

- Adds a reviewed Qwen3.5-9B Q4_K_M assistant priority after exact artifact verification and an Apple Silicon compatibility canary.

## 0.3.17 (contract 0.3.13)

- Declares `deterministic_direct_answer_v1` on the Qwen3-8B assistant priority and validates coverage-priority generation presets against Runner-supported policies.

## 0.3.16 (contract 0.3.12)

- Adds a Qwen3-8B Q4_K_M assistant coverage priority and fixes GGUF quant-identity parsing for filenames that start with model-family names (e.g. `Qwen` vs `Q4_K_M`).

## 0.3.14 (contract 0.3.10)

- Enforces Hub-declared exact artifact download sizes across local files, cache hits, and streamed downloads.
- Deployment results record output-token percentiles, natural-stop rate, and token-budget-exhaustion rate with an explicit non-semantic-completion boundary.
- Adds a deployment-only evidence lane and bounded warmup/measured iteration counts.

## 0.3.5 (contract 0.3.5)

- Capability catalog gains `coverage_expansion_priorities`, a machine-readable map of the highest-leverage model, quant, hardware, and benchmark gaps.

## 0.3.4

- Adds Windows/NVIDIA CUDA beta preflight: driver/VRAM/compute-capability checks, `nvidia-smi` parsing, binary smoke, and explicit fallback refusal. CUDA evidence stays blocked until a full loop is proven on real hardware.

## 0.3.2 (contract 0.3.2)

- Capability confidence labels adopt `repeated_local_sample` and `sampled_reference`; older labels remain accepted as aliases.
- Capability summaries gain per-artifact repeatability metadata: repetition count, latency percentiles, TTFT/throughput/pass-rate variance, and instability reasons.

## 0.3.0 (contract 0.3.0)

- Runtime-selector contract cutover: `runtime_selector.schema.json` joins the contract bundle with Apple Silicon managed Metal and Windows CUDA preview fixtures.

## 0.2.21

- Pair codes can be supplied via environment variable or stdin so they stay out of shell history.
- Support exports recursively redact prompts, model outputs, pair codes, tokens, signed URLs, and secret-shaped fields.
