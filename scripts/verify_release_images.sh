#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_TAG="${INFERGRADE_IMAGE_TAG:-$(<"${ROOT_DIR}/VERSION")}"
REGISTRY_PREFIX="${INFERGRADE_IMAGE_REGISTRY_PREFIX:-ghcr.io/bfogels}"
DOCKER_CONFIG_DIR="$(mktemp -d)"
trap 'rm -rf "${DOCKER_CONFIG_DIR}"' EXIT

images=(
  infergrade-runner-core
  infergrade-llama-cpp
  infergrade-ifeval
  infergrade-evalplus
  infergrade-mmlu-pro
)

for image in "${images[@]}"; do
  ref="${REGISTRY_PREFIX}/${image}:${VERSION_TAG}"
  if ! manifest="$(DOCKER_CONFIG="${DOCKER_CONFIG_DIR}" docker manifest inspect "${ref}")"; then
    echo "Anonymous image verification failed: ${ref}" >&2
    exit 1
  fi
  digest="$(printf '%s' "${manifest}" | shasum -a 256 | awk '{print $1}')"
  printf '%s\tmanifest_sha256:%s\n' "${ref}" "${digest}"
done

echo "Verified anonymous registry access for ${#images[@]} InferGrade images at ${VERSION_TAG}."
