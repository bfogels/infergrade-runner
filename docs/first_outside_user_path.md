# First Outside User Path

This path keeps the Runner useful for a first outside user who wants to compare quantized model setups on their own hardware.

## Apple Silicon Native Path

```bash
brew install llama.cpp
python3 -m pip install -e ./python/runner-core
infergrade pair --api-url http://127.0.0.1:8000 --pair-code 'igrp_example'
infergrade start --execution-mode local_native
```

Use this path for local Apple Silicon `llama.cpp` benchmarking. Dockerized `llama.cpp` on macOS measures Docker Desktop's Linux VM rather than Metal.

The proof lane uses this native path with TinyLlama, the public Q4_K_M GGUF artifact, and the short decision-suite `interactive_chat_v1` check. The expected output includes `report.md` in addition to the normalized bundle files. See [End-To-End Proof Path](end_to_end_proof_path.md).

## Container-Friendly Path

```bash
python3 -m pip install -e ./python/runner-core
infergrade install-images
infergrade pair --api-url http://127.0.0.1:8000 --pair-code 'igrp_example'
infergrade start --execution-mode local_container
```

Use this path for Linux, cloud-like workers, and container-friendly local hosts.

## What A First Run Should Produce

- a run directory under `runs/`
- `progress.json`
- normalized bundle JSON
- `report.md`
- deployment metrics when emitted by the backend
- capability and benchmark coverage metadata
- environment and hardware provenance
- truth-preserving failure/degraded states when something cannot run cleanly

## Known First-Path Boundaries

- `llama.cpp` + GGUF is the clearest path.
- Decision-suite checks are the default first run.
- Reference-suite style runs should be explicit because they are slower.
- The Hub provides the guided pairing, run queue, upload, and compare surface, but the Runner remains useful as an open execution engine.
