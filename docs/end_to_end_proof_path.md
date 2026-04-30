# End-To-End Proof Path

The Runner proof path is intentionally narrow. It exists to protect the first outside-user promise:

> Which quantized model setup should I run on my hardware for this use case?

## Supported Proof Lane

- Hardware lane: Apple Silicon local workstation
- Runner mode: `local_native`
- Backend: `llama.cpp`
- Model family: TinyLlama
- Checkpoint: `TinyLlama-1.1B-Chat-v1.0`
- Artifact example: `hf://TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf`
- Benchmark scope: decision suite
- Benchmark check: `interactive_chat_v1`
- Expected Hub compare outcome: same-family quant ladder

Use containerized execution for Linux and cloud-like workers. Use `local_native` for Apple Silicon when the goal is realistic `llama.cpp` performance, because Docker Desktop does not expose Metal-backed inference in the same way.

## Expected Runner Artifacts

A successful proof-path run must write:

- `manifest.json`
- `summary.json`
- `validation.json`
- `progress.json`
- `results/interactive_chat_v1.json`
- `report.md`

The report is not decorative. It is the standalone human-readable artifact that keeps Runner output useful even when the Hub is unavailable.

## Local Test

The locally testable proof is covered by:

```bash
PYTHONPATH=python/runner-core/src python3 -m unittest python/runner-core/tests/test_end_to_end_proof_path.py
```

That test runs a simulated TinyLlama local-native decision-suite request and asserts that the result, summary, manifest, and report all preserve the same benchmark scope and selected check.

## Manual Verification

For a real local run:

1. Install `llama.cpp` with Metal support.
2. Pair the Runner from the Hub setup flow.
3. Start the Runner with `infergrade start --execution-mode local_native`.
4. Queue the TinyLlama demo config.
5. Confirm `report.md` names the model, `local_native`, `Decision suite`, and `interactive_chat_v1`.
6. Confirm the Hub upload participates in same-family quant-ladder comparison.
