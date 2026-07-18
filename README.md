# InferGrade Runner

InferGrade Runner is the open execution engine for answering one practical local-model question:

> Which quantized model setup should I run on my hardware for this use case?

The Runner owns execution truth. It resolves quantized artifacts, runs benchmarks on the right local execution path, captures provenance, and writes normalized result bundles that InferGrade Hub can compare.

It is responsible for:

- resolving deployable model artifacts
- executing native or container-backed benchmark runs locally or in cloud-hosted worker environments
- capturing deployment telemetry and capability evidence
- writing reproducible run bundles that can be uploaded to InferGrade Hub

See [ARCHITECTURE.md](ARCHITECTURE.md) for the component map and design decisions, [CHANGELOG.md](CHANGELOG.md) for release history, and [docs/README.md](docs/README.md) for the full documentation index.

## Project Status

Treat the current code as preview software:

- **Working today:** Runner-owned schemas, benchmark catalog metadata, local/native and container-aware execution paths, Rust native first-run execution for selected `llama.cpp` GGUF runs, native-first-run Hub upload, result bundle generation, support export, signed macOS desktop release wiring, and explicit checksum-verified macOS Apple Silicon managed `llama.cpp` runtime install.
- **Being hardened:** macOS installer-and-go smoke, hosted Hub handoff, broader clean-machine install validation, and stronger runtime provenance/signature checks.
- **Planned or limited:** managed runtime lanes beyond macOS Apple Silicon Metal, Windows and Linux public desktop installers, fully managed cloud worker provisioning, and heavier reference/gold benchmark lanes that need stronger dataset, sandbox, or cost controls before becoming default local paths.

Security-sensitive release credentials, Apple signing materials, Hub tokens, local runner profiles, and `.env` files must never be committed. See [SECURITY.md](SECURITY.md) before reporting vulnerabilities or sharing security-sensitive logs.

## First Path

The clearest first path is:

1. pick a use case in the Hub
2. resolve a quantized GGUF artifact
3. generate a short decision-suite run config
4. pair this machine once
5. start the Runner in the correct local mode
6. let the Hub queue the run
7. inspect the normalized result and compare nearby quants

The broader Runner architecture remains available, but the default path is intentionally narrower than a general benchmark platform.

The Desktop Runner has a native first-run lane for macOS Apple Silicon with a local GGUF model and either an explicit selected `llama.cpp` runtime or the recommended managed Metal runtime installed through the app. Docker will not be required for the first local benchmark. Runtime install is intentional: the app does not silently download, upgrade, or switch runtimes, and the current managed runtime is checksum-verified rather than independently signed. Managed packages are stored as immutable content-addressed builds; evidence-producing native runs lock one exact build for the attempt and emit a path-free runtime receipt. Docker remains supported for advanced sandboxed benchmarks, code-execution checks, and container-friendly headless workers.

## Decision Suite vs Reference Suite

The Runner-owned catalog separates benchmark scope from tier names:

- `decision` checks are the default setup path: short, local-friendly evidence for choosing a quantized setup on the current hardware.
- `reference` checks are deeper follow-up evidence: broader throughput, long-context, fidelity, or breadth checks that take longer and should be selected intentionally.

Every catalog check also belongs to an evidence lane:

- `decision` evidence can answer "what should I try now?" for one local setup decision.
- `reference` evidence can support stronger comparisons across nearby variants or families.
- `gold` evidence is reserved for curated, high-legitimacy claims that need heavier datasets, runtime controls, or cloud/curated execution before becoming a default local path.

Every catalog check carries effort, duration-band, token-volume, execution-pattern, resumability, and claim-boundary metadata. Result bundles preserve the derived scope summary in `configuration.benchmark_selection.benchmark_scope` so the Hub can explain whether a recommendation is backed by first-pass decision evidence, deeper reference evidence, or a future curated lane.

## Standalone Runner Reports

Every finalized Runner bundle includes `report.md`, a human-readable Markdown artifact that is useful even without the Hub. It summarizes the model and quant artifact, hardware/backend, benchmark scope, deployment metrics, capability/fidelity status, trust/comparability status, and rerun metadata.

If a run fails before bundle finalization, the Runner still writes a truthful failure report where possible. That report includes the requested setup, failing stage/detail, error message, and progress snapshot instead of pretending the run produced comparable evidence.

## Capability-First Benchmark Selection

Benchmark scope is a capability-first contract:

- `capability_suite_ids` define the top-level user intent, such as chat/instruction following, coding/code editing, or quant fidelity
- `benchmark_group_ids` define the main benchmark groups inside those suites
- `benchmark_check_ids` define the concrete checks that will actually run
- `evidence_lane_id` on each catalog check defines the claim lane the check can support, such as `decision`, `reference`, or `gold`

The older `canary / standard / gold` language exists internally as a compatibility breadth hint, but it is not the main product abstraction. The Runner derives that breadth from the selected checks so older flows remain compatible without forcing new users to think in tier jargon first.

## Platform Execution Paths

InferGrade aims to benchmark the best realistic execution path on each platform, not to force every machine through the same runtime wrapper.

- `macOS Apple Silicon`: run `llama.cpp` natively so Metal acceleration is actually exercised
- `Linux + NVIDIA`: prefer containerized CUDA execution
- `Linux + AMD`: prefer containerized ROCm execution
- `CPU-only`: containerized or native CPU execution, clearly labeled as CPU-only

The most important implication is that Apple Silicon local benchmarking is a separate path. Dockerized local `llama.cpp` runs on macOS benchmark Docker Desktop's Linux VM and do not represent Metal performance.

The desktop app keeps this split user-visible: native runtime readiness can progress while Docker is missing, and Docker/Podman availability unlocks optional sandboxed capability lanes rather than blocking pairing or native first-run setup.

## Canonical Hub Handoff

The preferred hosted flow is:

1. sign in to InferGrade Hub and pair the machine once
2. start a local runner once
3. queue local runs from the Hub and let the Runner claim, execute, and upload them automatically

Lower-level commands like `run-job`, `doctor`, `run-config`, and `upload-bundle` exist as the manual fallback path.

## Pinned Container Release Path

For the containerized setup path, the Hub pins one released Runner artifact set instead of assuming a repo checkout or `:local` tags.

That released lane centers on the current `VERSION` plus the `-preview` channel, for example:

- `infergrade-runner-core:$(cat VERSION)`
- `infergrade-llama-cpp:$(cat VERSION)`
- the matching Runner contract bundle and release manifest

Development-only `:local` images exist as a clearly separate workflow.

## Repo Layout

- `python/runner-core`: Python execution core — CLI, bundle orchestration, adapters, transport, and tests
- `crates/runner-engine`: Rust engine library — pairing, credential storage, Hub client, worker protocol
- `apps/runner-cli`: Rust CLI exposing the managed-runtime and native first-run lanes
- `apps/desktop-runner`: Tauri desktop app and its Rust sidecar
- `containers`: runtime and capability benchmark images
- `schemas`: shared bundle, request, and result contracts (the contract authority)
- `runtime`: pinned `llama.cpp` release policy
- `docs`: architecture, benchmark, and operations docs ([index](docs/README.md))
- `scripts`: test, release, contract-export, and verification tooling
- `third_party`: vendored benchmark assets used in container builds, with license audit trail

## Quick Start

### Apple Silicon Local Benchmarking

If you are benchmarking locally on Apple Silicon, use the native `llama.cpp` path:

```bash
brew install llama.cpp
python3 -m pip install -e ./python/runner-core
python3 -c 'import getpass; print(getpass.getpass("InferGrade pairing code: "))' | infergrade pair \
  --api-url http://127.0.0.1:8000 \
  --pair-code-stdin
infergrade start
```

`infergrade doctor` fails fast if you try to run a real Apple Silicon `llama.cpp` benchmark with `execution_mode=local_container`, because that path does not use Metal.

Advanced users can point native execution at a specific `llama.cpp` build without making it look like an InferGrade-managed runtime:

```bash
infergrade doctor \
  --model Qwen/Qwen2.5-7B-Instruct \
  --backend llama.cpp \
  --tier canary \
  --execution-mode local_native \
  --llama-cpp-cli-path /path/to/llama-cli \
  --llama-cpp-server-path /path/to/llama-server
```

The same values can be supplied through `runtime.llama_cpp_cli_path`, `runtime.llama_cpp_server_path`, and `runtime.llama_cpp_perplexity_path` in a run config, or through the `INFERGRADE_LLAMA_CPP_*` environment variables. See [docs/llama_cpp_runtime_compatibility.md](docs/llama_cpp_runtime_compatibility.md) for the compatibility and provenance rules.

To inspect the pinned managed-runtime plan without changing the machine:

```bash
infergrade install-runtime --runtime llama.cpp --list
infergrade install-runtime --runtime llama.cpp
```

To explicitly select already-installed binaries as the managed runtime:

```bash
infergrade install-runtime --runtime llama.cpp --select-existing \
  --llama-cpp-cli-path /opt/homebrew/bin/llama-cli \
  --llama-cpp-server-path /opt/homebrew/bin/llama-server
```

The Rust runner and Desktop app expose the shared managed-runtime lane:

```bash
infergrade-runner runtime list
infergrade-runner runtime status
infergrade-runner runtime install
```

`infergrade-runner runtime install` is the explicit install action: it downloads the pinned macOS Apple Silicon Metal `llama.cpp` archive, verifies SHA-256, extracts it into the InferGrade runtime cache, checks expected binaries, runs a version smoke, and writes the selected-runtime record. The Desktop app exposes the same shared-engine behavior through its runtime install action.

InferGrade never silently installs or upgrades `llama.cpp`. The legacy Python command requires `--execute` before any manifest install command is run; the Rust `runtime install` command and Desktop install button are the explicit user consent path. The current managed runtime is checksum-verified, not independently signed.

### Containerized Local And Cloud Paths

For Linux, cloud workers, and the common containerized development path:

```bash
python3 -m pip install -e ./python/runner-core
infergrade install-images --image infergrade-llama-cpp:local
infergrade --help
```

That setup command also prepares `infergrade-runner-core:local`, because the recommended Hub-backed local flow runs the long-lived listener inside the runner-core container while the listener launches benchmark runtime images like `infergrade-llama-cpp:local` through Docker.

If a local runtime image like `infergrade-llama-cpp:local` is missing, the Runner tries to build it automatically from the checked-out repo before falling back to a Docker pull, so local development does not depend on a manual `docker login` or hand-built image step in the common case.

If you change the runner container dependencies and want to refresh an existing local image, use:

```bash
infergrade install-images --image infergrade-runner-core:local --rebuild
```

For the common local-listener path during development, the simplest entrypoint is:

```bash
./scripts/start_local_listener.sh --api-url http://host.docker.internal:8000
```

If you paired the machine already, native start commands can omit `--api-url` because the Runner reads the saved local profile:

```bash
infergrade start
```

If you are following the released containerized lane rather than a repo-based development flow, the canonical listener bootstrap is:

```bash
docker run --rm \
  -e INFERGRADE_HUB_TOKEN="$INFERGRADE_HUB_TOKEN" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD/runs:/app/runs" \
  -v "$HOME/.cache/infergrade/artifacts:/root/.cache/infergrade/artifacts" \
  infergrade-runner-core:$(cat VERSION) start --api-url http://host.docker.internal:8000
```

For security and reproducibility on container-friendly hosts, the recommended container path runs the Runner inside the `infergrade-runner-core` container with a mounted Docker socket and explicit artifact/output mounts. The desktop first-run path is intentionally different: it runs native local benchmarks without making Docker, a globally installed CLI, or a local repo checkout part of onboarding.

When that listener container talks to a Hub running on your Mac host, use `http://host.docker.internal:8000` inside the container rather than `http://localhost:8000`.

## Pairing A Local Runner

The preferred local workflow is:

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

## Support Export

When a local run fails or a maintainer needs a compact machine snapshot, the Runner can emit a secret-free support export:

```bash
infergrade export-support --run-dir runs/example --output infergrade-runner-support.json
```

Without `--output`, the same command prints the JSON payload to stdout. Support exports intentionally omit bearer tokens while still including:

- the paired runner profile shape
- current environment and execution mode
- local progress, summary, validation, and captured environment artifacts when a run directory is supplied
- a simple file-presence checklist for first-user-path debugging

This is designed to pair with the Hub-side support export so operator debugging does not depend on screenshots or ad hoc terminal copy/paste.

For pairing, runtime, artifact-path, upload-retry, and support-export recovery details, see [Runner Recovery](docs/recovery.md).

## Testing

Run the Python test suite:

```bash
./scripts/test_all.sh
```

Run the Rust workspace checks:

```bash
cargo fmt --all -- --check
cargo test --workspace --exclude infergrade_desktop_runner --locked
```

## License

InferGrade Runner is licensed under the [Apache License 2.0](LICENSE). Vendored third-party benchmark assets are audited in [docs/third_party_license_audit.md](docs/third_party_license_audit.md).

## Key Docs

- [Architecture](ARCHITECTURE.md)
- [Documentation Index](docs/README.md)
- [Decision Workflow](docs/decision_workflow.md)
- [First Outside User Path](docs/first_outside_user_path.md)
- [Runner vs Hub](docs/runner_vs_hub.md)
- [Contract Ownership](docs/contract_ownership.md)
- [Release Process](docs/release_process.md)
- [Input/Output Spec](docs/input_output_spec.md)
- [Capability Benchmarks](docs/capability_benchmarks.md)
- [Public Release Checklist](docs/public_release_checklist.md)

## Relationship To InferGrade Hub

InferGrade Runner is designed to work with the hosted InferGrade Hub, but it remains the open, portable execution surface for the project.

The Runner repository is the trust-sensitive source of execution truth: schemas, ontology, benchmark-selection metadata, and standalone reports originate here. The Hub repository consumes that output to guide setup, store evidence, and compare same-family quant ladders against exact or similar hardware slices.

The Hub owns identity, recommendations, community evidence, publishing, and hosted run planning.
The Runner owns the ontology, schemas, and emitted bundle contract.

## Contract Export

Runner publishes the InferGrade execution contract.

Export a versioned contract bundle with:

```bash
python ./scripts/export_contract_bundle.py
```

That bundle is the artifact the Hub pins to over time.

For the current setup path, the stronger maintainer workflow is the release bundle:

```bash
./scripts/build_release_bundle.sh
```

See [Release Process](docs/release_process.md) for the full pinned-release workflow, including the matching Hub import step.
