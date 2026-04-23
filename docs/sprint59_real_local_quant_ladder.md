# Sprint 59 Real Local Quant Ladder Dogfood

Date: 2026-04-23

## Local Readiness

- Machine: MacBookPro18,3, Apple M1 Pro, 16 GB unified memory
- Execution mode: `local_native`
- Runtime: system `llama.cpp`
- `llama-cli`: `/opt/homebrew/bin/llama-cli`
- `llama-server`: `/opt/homebrew/bin/llama-server`
- Free disk at start: about 62 GB
- Doctor result: ready for native local execution; only warning was missing artifact before the run

## Candidate Choice

Selected `TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF` because it is public, small, and has many same-family GGUF quant variants. This avoids gated/private artifacts and keeps the local run feasible on a 16 GB Apple Silicon machine.

The first dogfood ladder used two quants:

- `tinyllama-1.1b-chat-v1.0.Q2_K.gguf`
- `tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf`

Scope was intentionally deployment-only canary evidence:

- deployment profile: `interactive_chat_v1`
- capability: `none`
- fidelity: not selected

That means this evidence is real and comparable for local deployment telemetry, but it does not answer task capability or quant-fidelity quality.

## Results Produced

### Q2_K

- Bundle ID: `qb_20260423_022236_5ec24bee`
- Result ID: `qb_20260423_022236_5ec24bee_interactive_chat_v1`
- Output directory: `runs/sprint59_tinyllama_q2_k`
- Verification: `verified`
- Comparison grade: `comparable`
- Decode throughput: `124.67 tok/s`
- TTFT: `56.27 ms`
- Capability score: `n/a`

### Q4_K_M

- Bundle ID: `qb_20260423_022308_5ad5fd1c`
- Result ID: `qb_20260423_022308_5ad5fd1c_interactive_chat_v1`
- Output directory: `runs/sprint59_tinyllama_q4_k_m`
- Verification: `verified`
- Comparison grade: `comparable`
- Decode throughput: `126.18 tok/s`
- TTFT: `48.94 ms`
- Capability score: `n/a`

## Reproduction

```bash
./scripts/dogfood_tinyllama_ladder.sh
```

Or run one quant manually:

```bash
PYTHONPATH=python/runner-core/src python3 -m infergrade run \
  --model TinyLlama/TinyLlama-1.1B-Chat-v1.0 \
  --backend llama.cpp \
  --tier canary \
  --quant-artifact hf://TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf \
  --quant-artifact-filename tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf \
  --execution-mode local_native \
  --deployment-profile interactive_chat_v1 \
  --capability none \
  --output runs/sprint59_tinyllama_q4_k_m \
  --real-run
```

## Upload And Workbench Verification

Hosted upload was not completed in this sprint because the shell did not have a Hub/API token. A direct HTTPS `curl` upload attempt reached `https://api.infergrade.com/bundles` and returned:

```text
401 {"detail":"missing or invalid api token"}
```

The Python 3.8 upload command also hit a local certificate-store issue before auth:

```text
SSL: CERTIFICATE_VERIFY_FAILED
```

Because the bundles were not uploaded, Recommend/Explore/Compare were not verified against hosted evidence in this pass. The bundles are real local evidence and can be uploaded once a catalog-writer token or run-scoped upload token is available.

## Follow-Ups

- Upload both bundles through an authenticated Hub path and verify Recommend, Explore, and Compare render the two-point TinyLlama quant ladder.
- Add a capability check for at least one quant if we want quality evidence, not just deployment telemetry.
- Consider fixing Python certificate guidance for macOS framework Python, or route hosted uploads through a certifi-backed transport.
