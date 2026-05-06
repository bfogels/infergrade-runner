#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/apps/desktop-runner"
TAURI_DIR="$APP_DIR/src-tauri"
BUNDLE_DIR="$ROOT_DIR/target/release/bundle"
DMG_DIR="$BUNDLE_DIR/dmg"
MACOS_BUNDLE_DIR="$BUNDLE_DIR/macos"
CREATE_UPDATER_ARTIFACTS=0
CHECK_ONLY=0
SKIP_CHECKS=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --with-updater)
      CREATE_UPDATER_ARTIFACTS=1
      ;;
    --check-only)
      CHECK_ONLY=1
      ;;
    --skip-checks)
      SKIP_CHECKS=1
      ;;
    *)
      echo "Usage: $0 [--with-updater] [--check-only] [--skip-checks]" >&2
      exit 2
      ;;
  esac
  shift
done

if [ "$CHECK_ONLY" -eq 1 ] && [ "$SKIP_CHECKS" -eq 1 ]; then
  echo "--check-only and --skip-checks cannot be used together." >&2
  exit 2
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to build the desktop Runner app." >&2
  exit 1
fi

if ! command -v cargo >/dev/null 2>&1; then
  echo "cargo is required to build the desktop Runner app. Install Rust first." >&2
  exit 1
fi

if [ "$SKIP_CHECKS" -eq 0 ]; then
  cd "$APP_DIR"
  npm ci
  npm run build
  npm audit --audit-level=moderate

  "$ROOT_DIR/scripts/build_desktop_sidecar.sh"

  cd "$TAURI_DIR"
  cargo check --locked
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  exit 0
fi

rm -rf "$DMG_DIR"
if [ "$CREATE_UPDATER_ARTIFACTS" -eq 1 ]; then
  rm -rf "$MACOS_BUNDLE_DIR"
fi

cd "$APP_DIR"
"$ROOT_DIR/scripts/build_desktop_sidecar.sh"
MACOS_SIGNING_IDENTITY="${INFERGRADE_MACOS_SIGNING_IDENTITY:-}"

unset_if_empty() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    unset "$name"
  fi
}

unset_if_empty APPLE_CERTIFICATE
unset_if_empty APPLE_CERTIFICATE_PASSWORD
unset_if_empty APPLE_ID
unset_if_empty APPLE_PASSWORD
unset_if_empty APPLE_TEAM_ID
unset_if_empty APPLE_API_KEY
unset_if_empty APPLE_API_ISSUER
unset_if_empty APPLE_API_KEY_PATH

if [ -n "${APPLE_API_KEY_PATH:-}" ]; then
  unset APPLE_ID
  unset APPLE_PASSWORD
fi

if [ -n "${APPLE_CERTIFICATE:-}" ] && [ -z "${APPLE_CERTIFICATE_PASSWORD:-}" ]; then
  echo "APPLE_CERTIFICATE is set without APPLE_CERTIFICATE_PASSWORD; using ad-hoc macOS signing." >&2
  unset APPLE_CERTIFICATE
fi

if [ -n "${APPLE_CERTIFICATE:-}" ] && [ -z "$MACOS_SIGNING_IDENTITY" ]; then
  echo "APPLE_CERTIFICATE is set but INFERGRADE_MACOS_SIGNING_IDENTITY is not; using ad-hoc macOS signing." >&2
  unset APPLE_CERTIFICATE
  unset APPLE_CERTIFICATE_PASSWORD
fi

if [ -z "$MACOS_SIGNING_IDENTITY" ] && [ -z "${APPLE_CERTIFICATE:-}" ]; then
  MACOS_SIGNING_IDENTITY="-"
fi
export CREATE_UPDATER_ARTIFACTS MACOS_SIGNING_IDENTITY
build_config="$(python3 - <<'PY'
import json
import os

config = {"bundle": {"macOS": {}}}
if os.environ.get("CREATE_UPDATER_ARTIFACTS") == "1":
    config["bundle"]["targets"] = ["app", "dmg"]
    config["bundle"]["createUpdaterArtifacts"] = True
identity = os.environ.get("MACOS_SIGNING_IDENTITY", "")
if identity:
    config["bundle"]["macOS"]["signingIdentity"] = identity
if not config["bundle"]["macOS"]:
    del config["bundle"]["macOS"]
print(json.dumps(config, separators=(",", ":")))
PY
)"
npm run tauri -- build --config "$build_config" -- --locked

if [ ! -d "$DMG_DIR" ]; then
  echo "No DMG output directory found at $DMG_DIR" >&2
  exit 1
fi

found_artifact=0
for artifact in "$DMG_DIR"/*.dmg; do
  if [ ! -f "$artifact" ]; then
    continue
  fi
  found_artifact=1
  size_bytes="$(wc -c < "$artifact" | tr -d ' ')"
  digest="$(shasum -a 256 "$artifact" | awk '{print $1}')"
  echo "desktop_runner_artifact=$artifact"
  echo "desktop_runner_size_bytes=$size_bytes"
  echo "desktop_runner_sha256=$digest"
done

if [ "$CREATE_UPDATER_ARTIFACTS" -eq 1 ]; then
  shopt -s nullglob
  space_named_archives=("$MACOS_BUNDLE_DIR"/*" "*.tar.gz)
  for artifact in "${space_named_archives[@]}"; do
    normalized_artifact="${artifact// /.}"
    mv "$artifact" "$normalized_artifact"
    if [ -f "$artifact.sig" ]; then
      mv "$artifact.sig" "$normalized_artifact.sig"
    fi
  done
  updater_archives=("$MACOS_BUNDLE_DIR"/*.tar.gz)
  updater_signatures=("$MACOS_BUNDLE_DIR"/*.tar.gz.sig)
  shopt -u nullglob
  if [ "${#updater_archives[@]}" -ne 1 ]; then
    echo "Expected exactly one updater archive in $MACOS_BUNDLE_DIR, found ${#updater_archives[@]}" >&2
    exit 1
  fi
  if [ "${#updater_signatures[@]}" -ne 1 ]; then
    echo "Expected exactly one updater signature in $MACOS_BUNDLE_DIR, found ${#updater_signatures[@]}" >&2
    exit 1
  fi
  for artifact in "${updater_archives[@]}" "${updater_signatures[@]}"; do
    if [ ! -f "$artifact" ]; then
      continue
    fi
    size_bytes="$(wc -c < "$artifact" | tr -d ' ')"
    digest="$(shasum -a 256 "$artifact" | awk '{print $1}')"
    echo "desktop_runner_updater_artifact=$artifact"
    echo "desktop_runner_updater_size_bytes=$size_bytes"
    echo "desktop_runner_updater_sha256=$digest"
  done
fi

if [ "$found_artifact" -eq 0 ]; then
  echo "No DMG artifacts found in $DMG_DIR" >&2
  exit 1
fi
