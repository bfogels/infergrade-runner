#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_TAG="${INFERGRADE_RELEASE_VERSION:-$(<"${ROOT_DIR}/VERSION")-alpha}"
BUNDLE_DIR_RELATIVE="dist/releases/${VERSION_TAG}"
BUNDLE_DIR="${ROOT_DIR}/${BUNDLE_DIR_RELATIVE}"

cd "${ROOT_DIR}"

python3 ./scripts/check_versions.py

if [[ "${INFERGRADE_RELEASE_INCLUDE_IMAGES:-0}" == "1" ]]; then
  INFERGRADE_IMAGE_TAG="${VERSION_TAG}" bash ./scripts/build_alpha_images.sh
  INFERGRADE_IMAGE_TAG="${VERSION_TAG}" bash ./scripts/export_alpha_images.sh
fi

python3 ./scripts/export_release_bundle.py --release-version "${VERSION_TAG}"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "release_version=${VERSION_TAG}"
    echo "bundle_dir=${BUNDLE_DIR_RELATIVE}"
  } >> "${GITHUB_OUTPUT}"
fi

echo "Built InferGrade Runner release bundle: ${BUNDLE_DIR}"
