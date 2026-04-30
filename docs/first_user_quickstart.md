# InferGrade First-User Quickstart

This is the smallest known-good path for a first outside user.

It deliberately optimizes for success:

- one public GGUF
- one backend
- one deployment profile
- one short decision-suite deployment check
- protected API writes
- resumable local output

If this path does not feel smooth, InferGrade is not ready for first-user testing.

## The Demo Config

Use [schemas/examples/run_config.alpha_tinyllama_demo.json](../schemas/examples/run_config.alpha_tinyllama_demo.json).

It targets:

- model: `TinyLlama/TinyLlama-1.1B-Chat-v1.0`
- artifact: public TinyLlama GGUF on Hugging Face
- backend: `llama.cpp`
- capability suite: `chat_instruction_following`
- benchmark group: `deployment_chat`
- benchmark check: `interactive_chat_v1`
- derived compatibility tier: `canary`

## Prerequisites

- Docker
- Python 3.8+
- roughly 3 GB free disk for the image, artifact cache, and bundle output

If you are testing on Apple Silicon and want realistic local `llama.cpp` numbers, use the native path instead of the Docker execution path in this document:

```bash
brew install llama.cpp
PYTHONPATH=python/runner-core/src python3 -m infergrade doctor \
  --api-url http://127.0.0.1:8000 \
  --run-config-id rcfg_tinyllama_alpha_demo \
  --execution-mode local_native
PYTHONPATH=python/runner-core/src python3 -m infergrade run-job \
  --api-url http://127.0.0.1:8000 \
  --execution-mode local_native \
  --run-id run_replace_me
```

The containerized path below is still appropriate for Linux, cloud workers, and CPU-only validation, but it does not exercise Metal on Apple Silicon.

The important product shift is that InferGrade is now capability-first. Even this minimal demo config carries an explicit benchmark selection and only uses `canary` as a derived compatibility label.

## 1. Get The Runtime Image

Preferred hosted path:

```bash
RUNNER_RELEASE_TAG="$(cat VERSION)-alpha"
docker pull "ghcr.io/<your-github-owner>/infergrade-llama-cpp:${RUNNER_RELEASE_TAG}"
docker tag "ghcr.io/<your-github-owner>/infergrade-llama-cpp:${RUNNER_RELEASE_TAG}" "infergrade-llama-cpp:${RUNNER_RELEASE_TAG}"
```

Fallback if you received an exported archive from the host:

```bash
RUNNER_RELEASE_TAG="$(cat VERSION)-alpha"
docker load -i "infergrade-llama-cpp_${RUNNER_RELEASE_TAG}.tar"
```

If you want the released paired-listener path instead of a repo-based manual runner invocation, fetch the listener image too:

```bash
RUNNER_RELEASE_TAG="$(cat VERSION)-alpha"
docker pull "ghcr.io/<your-github-owner>/infergrade-runner-core:${RUNNER_RELEASE_TAG}"
docker tag "ghcr.io/<your-github-owner>/infergrade-runner-core:${RUNNER_RELEASE_TAG}" "infergrade-runner-core:${RUNNER_RELEASE_TAG}"
```

Or load the exported archive:

```bash
RUNNER_RELEASE_TAG="$(cat VERSION)-alpha"
docker load -i "infergrade-runner-core_${RUNNER_RELEASE_TAG}.tar"
```

## 2. Start The Protected API

```bash
export INFERGRADE_API_TOKEN=replace-with-a-long-random-token
export INFERGRADE_API_ALLOWED_ORIGINS=http://127.0.0.1:3000
export INFERGRADE_DEFAULT_IMAGE_TAG="$(cat VERSION)-alpha"

cd /path/to/infergrade/services/api
PYTHONPATH=src python3 -m uvicorn infergrade_api.main:app --host 127.0.0.1 --port 8000
```

## 3. Start The Web App

```bash
cd /path/to/infergrade/apps/web
npm run serve
```

Point the web app at `http://127.0.0.1:8000`, enter the same API token, and generate a run config.

If you want to use the fixed demo config in this repo instead of generating one through the UI, publish it first:

```bash
cd /path/to/infergrade
curl -X POST http://127.0.0.1:8000/run-configs \
  -H "Authorization: Bearer $INFERGRADE_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data @schemas/examples/run_config.alpha_tinyllama_demo.json
```

## 4. Create A Local Run

```bash
cd /path/to/infergrade
curl -X POST http://127.0.0.1:8000/v1/runs \
  -H "Authorization: Bearer $INFERGRADE_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"run_config_id":"rcfg_tinyllama_alpha_demo","execution_mode":"local_container"}'
```

This returns a `run_id` plus a one-command local execution handoff.

If you paired a local Runner through the Hub UI, the golden-path containerized listener command is:

```bash
docker run --rm \
  -e INFERGRADE_HUB_TOKEN="$INFERGRADE_HUB_TOKEN" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$PWD/runs:/app/runs" \
  -v "$HOME/.cache/infergrade/artifacts:/root/.cache/infergrade/artifacts" \
  "infergrade-runner-core:$(cat VERSION)-alpha" start --api-url http://host.docker.internal:8000
```

That path does not require a local Runner repo checkout. The manual `run-job` flow below remains the explicit fallback.

## 5. Execute The Local Run

```bash
cd /path/to/infergrade
PYTHONPATH=python/runner-core/src python3 -m infergrade run-job \
  --api-url http://127.0.0.1:8000 \
  --api-token "$INFERGRADE_API_TOKEN" \
  --run-id run_replace_me
```

The runner will:

- run preflight checks automatically
- resolve the public GGUF into the local artifact cache
- execute `llama.cpp` in Docker
- upload the bundle automatically on success
- write `manifest.json`, `summary.json`, `validation.json`, and `progress.json`
- write `report.md`
- preserve the artifact-resolution receipt and raw telemetry artifacts

## 6. Confirm The Catalog Updated

```bash
curl http://127.0.0.1:8000/stats/overview
curl http://127.0.0.1:8000/bundles
```

## Known-Good First-User Expectations

The first run should produce:

- one accepted bundle
- one stored result
- server-applied trust labels
- resumable local state
- a standalone `report.md`
- a browsable catalog entry in the web app

If you want the fastest path possible, use the demo config exactly as written before trying broader models or capability suites.
