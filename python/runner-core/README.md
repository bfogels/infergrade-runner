# InferGrade Runner Core

This package contains the Python benchmark runner core for InferGrade.

## Responsibilities

- CLI entrypoints
- run request parsing and defaults
- deployment profile resolution
- backend adapter contract
- bundle generation
- result record normalization
- local bundle validation

## Current State

The runner still defaults to simulated execution, but it now has a first real backend path for `llama.cpp`:

- local Docker-based execution
- automatic resolution of local paths, `file://`, `http(s)://`, and `hf://` GGUF artifact references
- real deployment timings parsed from `llama-cli`
- first real capability evaluation via containerized `IFEval` and `EvalPlus` runners
- backend-image overrides and artifact-cache overrides through the request contract
- Hub-token-aware fetch and upload flow for hosted deployments, with `INFERGRADE_HUB_TOKEN` preferred over `INFERGRADE_API_TOKEN`

## Development

```bash
PYTHONPATH=python/runner-core/src python3 -m unittest discover -s python/runner-core/tests
PYTHONPATH=python/runner-core/src python3 -m infergrade install-images --image infergrade-llama-cpp:local
PYTHONPATH=python/runner-core/src python3 -m infergrade doctor --model Qwen/Qwen2.5-7B-Instruct --backend llama.cpp --tier canary --quant-artifact hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf
PYTHONPATH=python/runner-core/src python3 -m infergrade run --model Qwen/Qwen2.5-7B-Instruct --backend llama.cpp --tier canary --output runs/qwen_canary --resume
docker build -t infergrade-llama-cpp:local -f containers/llama-cpp/Dockerfile .
docker build -t infergrade-ifeval:local -f containers/capability-ifeval/Dockerfile .
docker build -t infergrade-evalplus:local -f containers/capability-evalplus/Dockerfile .
PYTHONPATH=python/runner-core/src python3 -m infergrade run --model Qwen/Qwen2.5-7B-Instruct --quant-artifact /absolute/path/to/model.gguf --backend llama.cpp --tier canary --output runs/local_real_run --resume --real-run
PYTHONPATH=python/runner-core/src python3 -m infergrade run --model Qwen/Qwen2.5-7B-Instruct --quant-artifact hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf --quant-artifact-filename Qwen2.5-7B-Instruct-Q4_K_M.gguf --backend llama.cpp --backend-image infergrade-llama-cpp:local --tier canary --output runs/hf_real_run --resume --real-run
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

## Recommended Flow

For Hub-generated local runs, the preferred operator flow is now:

```bash
export INFERGRADE_HUB_TOKEN="qbhr_example"
docker run --rm \
  -e INFERGRADE_HUB_TOKEN="$INFERGRADE_HUB_TOKEN" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD/runs:/app/runs" \
  -v "$HOME/.cache/infergrade/artifacts:/root/.cache/infergrade/artifacts" \
  infergrade-runner-core:local start \
  --api-url http://host.docker.internal:8000
```

That starts a local runner loop that listens for queued `local_container` jobs from the Hub, claims them automatically, performs preflight checks, executes the benchmark, and uploads the finished bundle.

Running the runner in its own container is the recommended production path because it isolates the Python environment, makes image/runtime versions explicit, and keeps the benchmark orchestration surface closer to what will run in cloud environments.

When the Hub is running on your host machine, `host.docker.internal` is the correct API hostname from inside the runner container. `localhost` inside that container points back to the container itself.

If you want to run one specific Hub job immediately without keeping a local runner alive, you can still use:

```bash
PYTHONPATH=python/runner-core/src python3 -m infergrade run-job \
  --api-url http://localhost:8000 \
  --run-id run_example
```

If you need the lower-level manual path, the Runner still supports:

```bash
PYTHONPATH=python/runner-core/src python3 -m infergrade doctor --api-url http://localhost:8000 --run-config-id rcfg_example
PYTHONPATH=python/runner-core/src python3 -m infergrade run-config --api-url http://localhost:8000 --run-config-id rcfg_example --output runs/rcfg_example --resume --real-run
PYTHONPATH=python/runner-core/src python3 -m infergrade upload-bundle runs/rcfg_example --api-url http://localhost:8000
```

If you are talking to a legacy or development API that still expects a shared bearer token, `INFERGRADE_API_TOKEN` remains supported.

Each run directory now includes `progress.json`. InferGrade will refuse to overwrite a non-empty output directory unless you explicitly opt into resuming with `--resume`.

`infergrade start` is just the friendly local alias for the lower-level worker loop. The lower-level form is still available when you need it:

```bash
PYTHONPATH=python/runner-core/src python3 -m infergrade worker \
  --api-url http://localhost:8000 \
  --api-token "$INFERGRADE_API_TOKEN" \
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

For the known-good first-user alpha lane, use:

- [docs/first_user_quickstart.md](../../docs/first_user_quickstart.md)
- [schemas/examples/run_config.alpha_tinyllama_demo.json](../../schemas/examples/run_config.alpha_tinyllama_demo.json)
