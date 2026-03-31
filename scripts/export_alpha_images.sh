#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_TAG="${INFERGRADE_IMAGE_TAG:-0.1.0-alpha}"
DIST_DIR="${ROOT_DIR}/dist/images/${VERSION_TAG}"

mkdir -p "${DIST_DIR}"

export_image() {
  local image_name="$1"
  local archive_name="$2"

  local archive_path="${DIST_DIR}/${archive_name}"
  echo "==> Exporting ${image_name}:${VERSION_TAG} to ${archive_path}"
  docker image inspect "${image_name}:${VERSION_TAG}" >/dev/null
  docker save -o "${archive_path}" "${image_name}:${VERSION_TAG}"
  shasum -a 256 "${archive_path}" > "${archive_path}.sha256"
}

export_image "infergrade-llama-cpp" "infergrade-llama-cpp_${VERSION_TAG}.tar"
export_image "infergrade-ifeval" "infergrade-ifeval_${VERSION_TAG}.tar"
export_image "infergrade-evalplus" "infergrade-evalplus_${VERSION_TAG}.tar"
export_image "infergrade-runner-core" "infergrade-runner-core_${VERSION_TAG}.tar"

echo
echo "Exported OCI archives to ${DIST_DIR}"
