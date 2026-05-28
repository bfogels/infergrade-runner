# Calibration Budget v0.3.1

Status: T1 dogfood budget for a single all-day Apple Silicon pass.

## Goal

Generate real local Apple Silicon dogfood evidence that can replace static duration, token-volume, and failure-rate assumptions in Hub copy without implying official, gold, or leaderboard-grade validation.

This pass prioritizes evidence that changes Recommend, Result, and benchmark chooser behavior:

- a small sanity lane to prove the loop stays healthy;
- one common 7B assistant setup that is useful for public "fast assistant on Apple Silicon" questions;
- focused coding, reasoning, and quant-fidelity follow-ups only after the short lanes complete.

## Hardware Owner

- owner: agent dogfood session on Brian's MacBook Pro
- host label convention: `agent-dogfood-MacBookPro`
- detected hardware: Apple M1 Pro, 16 GB unified memory, Metal
- execution mode: `local_native`
- runtime: Homebrew `llama.cpp` (`llama-cli`, `llama-server`, `llama-perplexity`)

## Model And Quant Plan

| Priority | Slot | Model / checkpoint | Quant | Local artifact | Lanes |
| --- | --- | --- | --- | --- | --- |
| P0 | sanity | TinyLlama 1.1B Chat v1.0 | Q4_K_M | local cached GGUF | local core decision |
| P0 | assistant common | Qwen2.5 7B Instruct | Q4_K_M | local cached GGUF | local core decision |
| P1 | assistant reference | Qwen2.5 7B Instruct | Q4_K_M | local cached GGUF | MMLU-Pro sampled reference |
| P1 | coding reference | Qwen2.5 7B Instruct | Q4_K_M | local cached GGUF | HumanEval+ then MBPP+ |
| P2 | quant fidelity | Qwen2.5 7B family | Q4_K_M plus any same-family local quant discovered later | local cached GGUF or downloaded artifact | perplexity reference |

Local core decision means:

- `interactive_chat_v1`
- `multiturn_chat_memory_v1`
- `coding_static_repair_v1`
- `reasoning_exact_answer_v1`

Reference lanes stay intentionally selected and must not be described as default quick-start evidence.

## Wall-Clock Budget

| Lane | Repeat count | Expected wall clock | Stop rule |
| --- | ---: | ---: | --- |
| TinyLlama local core decision | 1 | 5-10 min | Stop after one clean upload or one classified failure. |
| Qwen2.5 7B local core decision | 1 | 20-45 min | Stop after one clean upload or one classified failure. |
| Qwen2.5 7B MMLU-Pro sampled reference | 1 | 45-90 min | Run only after a local core decision lane completes. |
| Qwen2.5 7B HumanEval+ | 1 | 60-120 min | Run only if the local core decision lane shows usable coding output. |
| Qwen2.5 7B MBPP+ | 1 | 90-180 min | Run after HumanEval+ if there is still all-day runway. |
| Quant fidelity reference | 1 per comparable quant | 20-60 min | Run only when same-family comparability is real. |

The all-day budget is 6-8 machine hours, with no more than two heavyweight reference lanes started before the first results are inspected. Repeats for v0.3.2 are not part of this initial budget unless T2 needs a synthetic-vs-real validation follow-up and the first pass finishes early.

## Storage And Output Budget

- request and command files: ignored `runs/local_evidence_dogfood/`
- local bundles: ignored `runs/local_evidence_dogfood/<matrix>/bundles/`
- expected bundle size excluding weights: 10-250 MB per lane, depending on raw scoring outputs
- expected cached weights: TinyLlama ~650 MB, Qwen2.5 7B Q4_K_M ~4.5 GB
- committed output: this budget only; no raw bundles, weights, pairing codes, runner tokens, upload tokens, or local command logs

## Upload And Evidence Source

Preferred production upload:

1. pair or reuse a runner labeled `agent-dogfood-MacBookPro`;
2. upload completed bundles to production Hub;
3. verify accepted bundles carry `evidence_source: agent_dogfood`;
4. record observed duration, token volume, and failure class in Hub follow-up copy PRs.

If the only available local profile is not agent-labeled, do not upload as founder evidence on behalf of the founder. Preserve local bundles and classify the upload as deferred until an agent-labeled production runner is paired.

## Failure Logging Plan

For each lane, record:

- bundle directory;
- start/end timestamp;
- observed duration;
- whether local execution, validation, upload, or Hub ingestion failed;
- error class, not just raw stderr;
- whether a secret-free support export exists;
- whether the failure should change Hub caveats or chooser estimates.

Failure classes:

- artifact missing or invalid;
- runtime missing or version smoke failed;
- generation timeout;
- malformed model output;
- benchmark scoring failure;
- upload rejected;
- runner token revoked or expired;
- evidence accepted but displayed with the wrong label.

## Copy Update Rules

Hub copy may be updated only from accepted evidence or preserved local bundles with explicit caveats:

- replace static duration estimates only when observed duration exists;
- replace token-volume estimates only when emitted bundle metrics include token counts;
- replace failure-rate copy only after more than one run or after a clear deterministic failure class;
- keep `dogfood`, `thin local sample`, `sampled reference`, `executable coding reference`, and `quant-fidelity reference` distinct.

Do not call this pass official validation, decision-grade proof, or a public benchmark result.

## Initial Local Launch Record

Initial P0 lanes were run locally on 2026-05-13 and preserved outside the git worktree under:

```text
/Users/brianfogelson/Desktop/Code/infergrade/.dogfood_runs/v0.3.1/apple_silicon_v0_3_1_20260513/
```

| Lane | Bundle | Duration | TTFT p50 | Decode p50 | Failure rate | Upload |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| TinyLlama Q4_K_M local core decision | `qb_20260513_200640_245a12f0` | 40s | 75.01 ms | 84.47 tok/s | 0.0 | deferred |
| Qwen2.5 7B Q4_K_M local core decision | `qb_20260513_200753_314ca873` | 116s | 398.08 ms | 15.21 tok/s | 0.0 | deferred |

Upload is deferred because the available production profile is not visibly labeled `agent-dogfood-*`. Do not upload these bundles through a founder or unlabeled runner identity just to satisfy the dogfood preference; pair an agent-labeled runner first, then upload or rerun as needed so Hub stores `evidence_source: agent_dogfood`.
