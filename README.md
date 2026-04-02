# InferGrade Runner

InferGrade Runner is the open execution engine for InferGrade.

It is responsible for:

- resolving deployable model artifacts
- executing container-backed benchmark runs locally or in cloud-hosted worker environments
- capturing deployment telemetry and capability evidence
- writing reproducible run bundles that can be uploaded to InferGrade Hub

## Platform Execution Paths

InferGrade aims to benchmark the best realistic execution path on each platform, not to force every machine through the same runtime wrapper.

- `macOS Apple Silicon`: run `llama.cpp` natively so Metal acceleration is actually exercised
- `Linux + NVIDIA`: prefer containerized CUDA execution
- `Linux + AMD`: prefer containerized ROCm execution
- `CPU-only`: containerized or native CPU execution, clearly labeled as CPU-only

The most important implication is that Apple Silicon local benchmarking is a separate path. Dockerized local `llama.cpp` runs on macOS benchmark Docker Desktop's Linux VM and do not represent Metal performance.

## Canonical Hub Handoff

The current preferred hosted flow is:

1. sign in to InferGrade Hub and pair the machine once
2. start a local runner once
3. queue local runs from the Hub and let the Runner claim, execute, and upload them automatically

Lower-level commands like `run-job`, `doctor`, `run-config`, and `upload-bundle` still exist, but they are now the manual fallback path.

## Repo Layout

- `python/runner-core`: CLI, bundle orchestration, adapters, transport, and tests
- `containers`: runtime and capability benchmark images
- `schemas`: shared bundle, request, and result contracts
- `docs`: runner-facing architecture and benchmark docs
- `third_party`: vendored benchmark assets used in container builds

## Quick Start

### Apple Silicon Local Benchmarking

If you are benchmarking locally on Apple Silicon, use the native `llama.cpp` path:

```bash
brew install llama.cpp
python3 -m pip install -e ./python/runner-core
infergrade pair --api-url http://127.0.0.1:8000 --pair-code 'igrp_example'
infergrade start --execution-mode local_native
```

`infergrade doctor` will now fail fast if you try to run a real Apple Silicon `llama.cpp` benchmark with `execution_mode=local_container`, because that path does not use Metal.

### Containerized Local And Cloud Paths

For Linux, cloud workers, and the common containerized development path:

```bash
python3 -m pip install -e ./python/runner-core
infergrade install-images --image infergrade-llama-cpp:local
infergrade --help
```

That setup command now also prepares `infergrade-runner-core:local`, because the recommended Hub-backed local flow runs the long-lived listener inside the runner-core container while the listener launches benchmark runtime images like `infergrade-llama-cpp:local` through Docker.

If a local runtime image like `infergrade-llama-cpp:local` is missing, the Runner will now try to build it automatically from the checked-out repo before falling back to a Docker pull. That means local development no longer depends on a manual `docker login` or hand-built image step in the common case.

If you change the runner container dependencies and want to refresh an existing local image, use:

```bash
infergrade install-images --image infergrade-runner-core:local --rebuild
```

For the common local-listener path during development, the simplest entrypoint is now:

```bash
./scripts/start_local_listener.sh --api-url http://host.docker.internal:8000
```

If you paired the machine already, native start commands can omit `--api-url` because the Runner will read the saved local profile:

```bash
infergrade start --execution-mode local_native
```

For security and reproducibility, the recommended way to operate the Runner is inside the `infergrade-runner-core` container with a mounted Docker socket and explicit artifact/output mounts. The main exception is Apple Silicon local `llama.cpp` benchmarking, where host-native execution is the correct path because that is what enables Metal acceleration.

When that listener container talks to a Hub running on your Mac host, use `http://host.docker.internal:8000` inside the container rather than `http://localhost:8000`.

## Pairing A Local Runner

The preferred local workflow is now:

1. sign in to InferGrade Hub
2. click `Pair Local Runner`
3. run the emitted `infergrade pair ...` command once on the machine
4. start the listener natively or in a container
5. queue runs from the Hub

Pairing redeems a short-lived one-time code into a durable local runner profile stored under `~/.config/infergrade/runner_profile.json` by default. After pairing:

- `infergrade start` can reuse the saved Hub URL and runner token
- `infergrade run-job` can reuse the saved Hub URL and runner token
- you do not need to keep exporting `INFERGRADE_HUB_TOKEN` for the common local path

If you ever want to remove that local profile:

```bash
infergrade unpair
```

Run the runner test suite:

```bash
./scripts/test_all.sh
```

## Key Docs

- [Runner vs Hub](docs/runner_vs_hub.md)
- [Contract Ownership](docs/contract_ownership.md)
- [Input/Output Spec](docs/input_output_spec_v0.1.md)
- [Schema Draft](docs/schema_draft.md)
- [Capability Benchmarks](docs/capability_benchmarks.md)

## Relationship To InferGrade Hub

InferGrade Runner is designed to work with the hosted InferGrade Hub, but it remains the open, portable execution surface for the project.

The Hub owns identity, recommendations, community evidence, publishing, and hosted run planning.
The Runner owns the ontology, schemas, and emitted bundle contract.

## Contract Export

Runner publishes the InferGrade execution contract.

Export a versioned contract bundle with:

```bash
python ./scripts/export_contract_bundle.py
```

That bundle is the artifact the Hub should pin to over time.
