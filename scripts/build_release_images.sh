#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_TAG="${INFERGRADE_IMAGE_TAG:-$(<"${ROOT_DIR}/VERSION")}"

build_image() {
  local name="$1"
  local dockerfile="$2"

  echo "==> Building ${name}:${VERSION_TAG}"
  docker build \
    -t "${name}:${VERSION_TAG}" \
    -t "${name}:local" \
    -f "${ROOT_DIR}/${dockerfile}" \
    "${ROOT_DIR}"
}

build_image "infergrade-llama-cpp" "containers/llama-cpp/Dockerfile"
build_image "infergrade-ifeval" "containers/capability-ifeval/Dockerfile"
build_image "infergrade-evalplus" "containers/capability-evalplus/Dockerfile"
build_image "infergrade-mmlu-pro" "containers/capability-mmlu-pro/Dockerfile"
build_image "infergrade-runner-core" "containers/runner-core/Dockerfile"

echo
echo "Built release-ready local images:"
echo "  infergrade-llama-cpp:${VERSION_TAG}"
echo "  infergrade-ifeval:${VERSION_TAG}"
echo "  infergrade-evalplus:${VERSION_TAG}"
echo "  infergrade-mmlu-pro:${VERSION_TAG}"
echo "  infergrade-runner-core:${VERSION_TAG}"
