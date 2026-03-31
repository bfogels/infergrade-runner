# InferGrade Runner

InferGrade Runner is the open execution engine for InferGrade.

It is responsible for:

- resolving deployable model artifacts
- executing container-backed benchmark runs locally or in cloud-hosted worker environments
- capturing deployment telemetry and capability evidence
- writing reproducible run bundles that can be uploaded to InferGrade Hub

## Canonical Hub Handoff

The current preferred hosted flow is:

1. generate a run in InferGrade Hub
2. start a local runner once in a container with the Hub-issued command
3. queue local runs from the Hub and let the Runner claim, execute, and upload them automatically

Lower-level commands like `run-job`, `doctor`, `run-config`, and `upload-bundle` still exist, but they are now the manual fallback path.

## Repo Layout

- `python/runner-core`: CLI, bundle orchestration, adapters, transport, and tests
- `containers`: runtime and capability benchmark images
- `schemas`: shared bundle, request, and result contracts
- `docs`: runner-facing architecture and benchmark docs
- `third_party`: vendored benchmark assets used in container builds

## Quick Start

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

For security and reproducibility, the recommended way to operate the Runner is inside the `infergrade-runner-core` container with a mounted Docker socket and explicit artifact/output mounts. Host-Python execution remains available for development and debugging, but it is no longer the preferred production path.

When that listener container talks to a Hub running on your Mac host, use `http://host.docker.internal:8000` inside the container rather than `http://localhost:8000`.

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
