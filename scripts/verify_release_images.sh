#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_TAG="${INFERGRADE_IMAGE_TAG:-$(<"${ROOT_DIR}/VERSION")}"
REGISTRY_PREFIX="${INFERGRADE_IMAGE_REGISTRY_PREFIX:-ghcr.io/bfogels}"

exec python3 "${ROOT_DIR}/scripts/verify_release_images.py" \
  --tag "${VERSION_TAG}" \
  --registry-prefix "${REGISTRY_PREFIX}"
