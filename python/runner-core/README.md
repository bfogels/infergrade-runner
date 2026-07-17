# InferGrade Runner Core

This package contains the Python benchmark runner core for InferGrade.

The current product focus is narrow on purpose: benchmark a quantized model setup on the user's hardware for a concrete use case, then produce normalized evidence that can be compared honestly.

## Responsibilities

- CLI entrypoints
- run request parsing and defaults
- deployment profile resolution
- backend adapter contract
- bundle generation
- result record normalization
- local bundle validation

## Decision Workflow

For the first outside-user path, prefer:

- `llama.cpp`
- GGUF quantized artifacts
- `local_native` on Apple Silicon
- `local_container` on container-friendly hosts
- short decision-suite benchmark selections before deeper reference-style runs

## Current State

The runner still defaults to simulated execution, but it now has a first real backend path for `llama.cpp`:

- local Docker-based execution for container-friendly platforms
- local native `llama.cpp` execution for Apple Silicon benchmarking
- automatic resolution of local paths, `file://`, `http(s)://`, and `hf://` GGUF artifact references
- real deployment timings parsed from `llama-cli`
- first real capability evaluation via containerized `IFEval` and `EvalPlus` runners
- explicit capability states and benchmark-coverage metadata so missing capability does not collapse into `N/A`
- first-pass `llama.cpp` perplexity support as a quantization-fidelity signal when the fidelity check is selected
- backend-image overrides and artifact-cache overrides through the request contract
- Hub-token-aware fetch and upload flow for hosted deployments, with `INFERGRADE_HUB_TOKEN` preferred over `INFERGRADE_API_TOKEN`
- paired local runner profiles so `infergrade start` and `infergrade run-job` can reuse saved Hub credentials after a one-time `infergrade pair`

## Capability Catalog

Runner now publishes a machine-readable capability catalog through the pinned contract bundle. That catalog defines:

- capability suites
- benchmark groups
- benchmark checks
- legacy shortcut mappings so older `use_case` and `tier` inputs still normalize into the same explicit selection model

New request payloads should prefer:

- `capability_suite_ids`
- `benchmark_group_ids`
- `benchmark_check_ids`

The Runner will still derive compatibility metadata like `tier`, `use_case`, deployment profiles, and capability enablement from that explicit selection when needed.

The catalog also labels each concrete check with both a benchmark scope and an evidence lane. Decision-scope checks are the short first path for choosing a quantized setup locally. Reference-scope checks are heavier follow-up evidence for stronger comparison. Evidence lanes (`decision`, `reference`, `gold`) describe the strength and boundary of claims that a check can support. The normalized result metadata includes `benchmark_scope`, per-check lane metadata, effort, expected duration, token-volume, execution-pattern, and resumability hints so downstream tools do not infer those claims from old tier names.

## Standalone Report Artifact

Each completed bundle includes `report.md`, a compact Markdown report for users who run the open-source Runner without the Hub. Failed runs also write a best-effort failure report with the failing stage and requested setup when enough local state exists.

## Development

### Apple Silicon Native Path

For realistic local benchmarks on Apple Silicon, install `llama.cpp` natively and use `execution_mode=local_native`:

```bash
brew install llama.cpp
PYTHONPATH=python/runner-core/src python3 -m unittest discover -s python/runner-core/tests
PYTHONPATH=python/runner-core/src python3 -m infergrade pair --api-url http://127.0.0.1:8000 --pair-code 'igrp_example'
PYTHONPATH=python/runner-core/src python3 -m infergrade start
```

`infergrade doctor` now raises an explicit error if you try to benchmark Apple Silicon locally with `execution_mode=local_container`, because that path runs inside Docker Desktop's Linux VM and does not exercise Metal.

### Containerized Path

```bash
PYTHONPATH=python/runner-core/src python3 -m unittest discover -s python/runner-core/tests
PYTHONPATH=python/runner-core/src python3 -m infergrade install-images --image infergrade-llama-cpp:local
PYTHONPATH=python/runner-core/src python3 -m infergrade doctor --model Qwen/Qwen2.5-7B-Instruct --backend llama.cpp --capability-suite-ids chat_instruction_following --benchmark-check-ids interactive_chat_v1 --quant-artifact hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf
PYTHONPATH=python/runner-core/src python3 -m infergrade run --model Qwen/Qwen2.5-7B-Instruct --backend llama.cpp --capability-suite-ids chat_instruction_following --benchmark-check-ids interactive_chat_v1 --output runs/qwen_quick_default --resume
docker build -t infergrade-llama-cpp:local -f containers/llama-cpp/Dockerfile .
docker build -t infergrade-ifeval:local -f containers/capability-ifeval/Dockerfile .
docker build -t infergrade-evalplus:local -f containers/capability-evalplus/Dockerfile .
PYTHONPATH=python/runner-core/src python3 -m infergrade run --model Qwen/Qwen2.5-7B-Instruct --quant-artifact /absolute/path/to/model.gguf --backend llama.cpp --capability-suite-ids chat_instruction_following --benchmark-check-ids interactive_chat_v1 --output runs/local_real_run --resume --real-run
PYTHONPATH=python/runner-core/src python3 -m infergrade run --model Qwen/Qwen2.5-7B-Instruct --quant-artifact hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf --quant-artifact-filename Qwen2.5-7B-Instruct-Q4_K_M.gguf --backend llama.cpp --backend-image infergrade-llama-cpp:local --capability-suite-ids chat_instruction_following --benchmark-check-ids interactive_chat_v1 --output runs/hf_real_run --resume --real-run
```

`infergrade install-images` is the preferred local setup path now. Preparing a local runtime image like `infergrade-llama-cpp:local` also prepares `infergrade-runner-core:local`, because the recommended Hub-backed flow uses the runner-core container as the long-lived local listener.

The `llama.cpp` adapter and capability containers will also try to build missing `:local` images automatically when the checked-out Runner repo is available, so the common “image not found” path should degrade into a local build instead of an unhelpful Docker auth error.

If `infergrade-runner-core:local` already exists but is stale, you can force a rebuild with:

```bash
PYTHONPATH=python/runner-core/src python3 -m infergrade install-images --image infergrade-runner-core:local --rebuild
```

The runner repo also includes a helper script that refreshes the listener image and starts the Dockerized local listener in one step:

```bash
./scripts/start_local_listener.sh --api-url http://host.docker.internal:8000
```

That helper is intended for the containerized path. On Apple Silicon, prefer the native `infergrade start --execution-mode local_native` flow instead.

## Reliability Tools

Two CLI surfaces now exist specifically for support and operator debugging:

```bash
PYTHONPATH=python/runner-core/src python3 -m infergrade doctor ...
PYTHONPATH=python/runner-core/src python3 -m infergrade export-support --run-dir runs/example
```

`doctor` remains the fast dependency/readiness check. `export-support` produces a secret-free JSON payload with the current machine snapshot plus any run-local progress, summary, validation, environment, and artifact-resolution receipts that are present in the supplied run directory.

When a worker-reported run failure reaches the Hub, the runner now classifies common first-user-path issues into actionable categories such as:

- missing runtime image
- artifact download failure
- auth mismatch
- insufficient disk
- output path conflict
- contract mismatch

Those structured failures are what power the Hub’s recovery guidance and support export views.

## Recommended Flow

For Hub-generated local runs, the preferred operator flow is now:

```bash
PYTHONPATH=python/runner-core/src python3 -m infergrade pair \
  --api-url http://127.0.0.1:8000 \
  --pair-code 'igrp_example'

PYTHONPATH=python/runner-core/src python3 -m infergrade start
```

After a one-time pair, `infergrade start` and `infergrade run-job` can omit `--api-url` and `--api-token`; the Runner will fall back to the saved local profile and choose the clearest local execution mode for the machine by default.

The first-run commands print short human summaries by default. Use `--json` with `doctor`, `cache`, `install-runtime`, `pair`, `unpair`, or `start` when a script needs the complete structured payload. `infergrade pair` uses the machine hostname as its label unless `--label` is supplied. Running `infergrade start` before pairing exits with the exact pairing command instead of entering an idle polling loop.

For the containerized listener path, the helper script remains the easiest option:

```bash
./scripts/start_local_listener.sh --api-url http://host.docker.internal:8000
```

For the pinned first-user release path, the equivalent no-repo listener bootstrap is:

```bash
docker run --rm \
  -e INFERGRADE_HUB_TOKEN="$INFERGRADE_HUB_TOKEN" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD/runs:/app/runs" \
  -v "$HOME/.cache/infergrade/artifacts:/root/.cache/infergrade/artifacts" \
  "infergrade-runner-core:$(cat VERSION)-preview" start --api-url http://host.docker.internal:8000
```

That is the containerized golden path the Hub should prefer when it has pinned a released Runner snapshot. The repo-based helper script remains the development convenience path.

Running the runner in its own container is the recommended production path because it isolates the Python environment, makes image/runtime versions explicit, and keeps the benchmark orchestration surface closer to what will run in cloud environments.

Apple Silicon is the deliberate exception: when the goal is to benchmark local `llama.cpp` performance, the native path is the production path because it is the only path that can use Metal.

Memory evidence follows the execution boundary instead of pretending every platform exposes VRAM. Native runs record the peak RSS of the `llama-server` process. Container runs prefer the container's monotonic kernel cgroup peak counter, read once after the benchmark; only hosts without a peak counter poll current usage at a bounded 250 ms interval. This is container-accounted memory usage (including memory charged by that cgroup), not host-wide memory, process RSS, or GPU-only VRAM. NVIDIA runs additionally retain the separately labeled `nvidia-smi` total-used delta. On Docker Desktop for macOS, container memory describes the Linux VM container and does not prove Metal/unified-memory use; use `local_native` for representative Apple Silicon measurements.

On Apple Silicon, Runner uses native macOS hardware signals to identify the host even when the invoking Python process is translated by Rosetta 2. `cpu_architecture` describes the host (`arm64`), while `process_architecture` and `process_translation` preserve the actual process context rather than silently treating a translated process as an Intel Mac.

## Capability And Fidelity Signals

Runner-produced result payloads now carry:

- explicit capability states such as `scored`, `partial`, `failed`, `skipped`, `not_yet_benchmarked`, and `not_comparable`
- a versioned task-scoped local assistant or coding score only after the selected evidence clears the Runner-owned coverage gate
- inspectable score weights, coverage, missing checks, score version, and claim boundary under `capability_score_details`
- backend-reported time per task, output tokens per task, and decode throughput under `task_performance` when the backend exposes those measurements
- benchmark coverage metadata including planned, executed, and scored benchmark components
- component-level capability reports for suites like `IFEval`, `EvalPlus HumanEval+`, and `EvalPlus MBPP+`
- first-pass perplexity metadata under `fidelity` for `llama.cpp` when that measurement is available

The important truthfulness rule is that benchmark execution failure stays distinct from missing data:

- `failed`: InferGrade attempted the benchmark lane and the suite or component execution failed.
- `partial`: some planned benchmark components scored, but the full lane did not complete cleanly.
- `not_yet_benchmarked`: the requested capability slice exists, but no benchmark execution has happened yet.
- `skipped`: the operator explicitly disabled capability execution for that run.

Perplexity is intentionally treated as a supporting quantization-fidelity signal, not a substitute for task-level capability or deployment telemetry.

The benchmark-selection portion of the result now preserves the actual suites, groups, and checks that were selected so Hub surfaces can explain exactly what evidence produced a recommendation or comparison.

When the Hub is running on your host machine, `host.docker.internal` is the correct API hostname from inside the runner container. `localhost` inside that container points back to the container itself.

If you want to run one specific Hub job immediately without keeping a local runner alive, you can still use:

```bash
PYTHONPATH=python/runner-core/src python3 -m infergrade run-job \
  --run-id run_example
```

If you need the lower-level manual execution path, the Runner still supports:

```bash
PYTHONPATH=python/runner-core/src python3 -m infergrade doctor --api-url http://localhost:8000 --run-config-id rcfg_example
PYTHONPATH=python/runner-core/src python3 -m infergrade run-config --api-url http://localhost:8000 --run-config-id rcfg_example --output runs/rcfg_example --resume --real-run
```

For Hub-queued work, start the paired Runner to perform the owned run-scoped upload: `infergrade start`. A paired Runner token cannot import an arbitrary standalone bundle into the catalog. The advanced `upload-bundle` command remains available for local development and explicitly authorized service-token imports. If you are talking to a legacy or development API that still expects a shared bearer token, `INFERGRADE_API_TOKEN` remains supported.

## Release Prep

When you want to prepare the pinned release path instead of a repo-local development flow:

```bash
./scripts/build_release_bundle.sh
```

That release bundle is what the Hub should import and pin. See [docs/release_process.md](../../docs/release_process.md).

Each run directory now includes `progress.json`. InferGrade will refuse to overwrite a non-empty output directory unless you explicitly opt into resuming with `--resume`.

`infergrade start` is just the friendly local alias for the lower-level worker loop. The lower-level form is still available when you need it:

```bash
PYTHONPATH=python/runner-core/src python3 -m infergrade worker \
  --execution-mode local_container \
  --once
```

That same worker contract is what lets InferGrade support both locally hosted and cloud runs. A self-hosted worker claims `local_container` jobs. A cloud-side worker claims `cloud_container` jobs with matching provider metadata.

You can also scope a worker down to one specific run or run config:

```bash
PYTHONPATH=python/runner-core/src python3 -m infergrade worker \
  --api-url http://localhost:8000 \
  --api-token "$INFERGRADE_API_TOKEN" \
  --execution-mode local_container \
  --run-id run_example \
  --once
```

For the known-good first-user path, use:

- [docs/first_user_quickstart.md](../../docs/first_user_quickstart.md)
- [docs/apple_silicon_private_beta_runbook.md](../../docs/apple_silicon_private_beta_runbook.md)
- [docs/release_process.md](../../docs/release_process.md)
- [schemas/examples/run_config.tinyllama_preview_demo.json](../../schemas/examples/run_config.tinyllama_preview_demo.json)
