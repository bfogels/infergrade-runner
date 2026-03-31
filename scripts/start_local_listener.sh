#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_URL="${INFERGRADE_API_URL:-http://host.docker.internal:8000}"
RUNNER_IMAGE="${INFERGRADE_LOCAL_RUNNER_IMAGE:-infergrade-runner-core:local}"
RUNS_DIR="${INFERGRADE_RUNS_DIR:-$ROOT_DIR/runs}"
ARTIFACT_CACHE_DIR="${INFERGRADE_ARTIFACT_CACHE_DIR:-$HOME/.cache/infergrade/artifacts}"
REBUILD_IMAGE="${INFERGRADE_REBUILD_LISTENER_IMAGE:-1}"
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-url)
      API_URL="$2"
      shift 2
      ;;
    --hub-token)
      export INFERGRADE_HUB_TOKEN="$2"
      shift 2
      ;;
    --runner-image)
      RUNNER_IMAGE="$2"
      shift 2
      ;;
    --runs-dir)
      RUNS_DIR="$2"
      shift 2
      ;;
    --artifact-cache-dir)
      ARTIFACT_CACHE_DIR="$2"
      shift 2
      ;;
    --no-rebuild)
      REBUILD_IMAGE="0"
      shift
      ;;
    --)
      shift
      EXTRA_ARGS+=("$@")
      break
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

mkdir -p "$RUNS_DIR" "$ARTIFACT_CACHE_DIR"

INSTALL_ARGS=(--image "$RUNNER_IMAGE")
if [[ "$REBUILD_IMAGE" == "1" ]]; then
  INSTALL_ARGS+=(--rebuild)
fi

PYTHONPATH="$ROOT_DIR/python/runner-core/src${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m infergrade install-images "${INSTALL_ARGS[@]}"

DOCKER_ARGS=(
  run
  --rm
  -v /var/run/docker.sock:/var/run/docker.sock
  -v "$RUNS_DIR:/app/runs"
  -v "$ARTIFACT_CACHE_DIR:/root/.cache/infergrade/artifacts"
)

if [[ -n "${INFERGRADE_HUB_TOKEN:-}" ]]; then
  DOCKER_ARGS+=(-e "INFERGRADE_HUB_TOKEN=${INFERGRADE_HUB_TOKEN}")
fi

LISTENER_ARGS=(start --api-url "$API_URL")
if [[ ${#EXTRA_ARGS[@]} -gt 0 ]]; then
  LISTENER_ARGS+=("${EXTRA_ARGS[@]}")
fi

exec docker "${DOCKER_ARGS[@]}" "$RUNNER_IMAGE" "${LISTENER_ARGS[@]}"
