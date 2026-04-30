#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/apps/desktop-runner"
TAURI_DIR="$APP_DIR/src-tauri"
DMG_DIR="$TAURI_DIR/target/release/bundle/dmg"
MACOS_BUNDLE_DIR="$TAURI_DIR/target/release/bundle/macos"
CREATE_UPDATER_ARTIFACTS=0

if [ "${1:-}" = "--with-updater" ]; then
  CREATE_UPDATER_ARTIFACTS=1
  shift
fi

if [ "$#" -ne 0 ]; then
  echo "Usage: $0 [--with-updater]" >&2
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

cd "$APP_DIR"
npm ci
npm run build
npm audit --audit-level=moderate

cd "$TAURI_DIR"
cargo check --locked

rm -rf "$DMG_DIR"
if [ "$CREATE_UPDATER_ARTIFACTS" -eq 1 ]; then
  rm -rf "$MACOS_BUNDLE_DIR"
fi

cd "$APP_DIR"
if [ "$CREATE_UPDATER_ARTIFACTS" -eq 1 ]; then
  npm run tauri -- build --config '{"bundle":{"targets":["app","dmg"],"createUpdaterArtifacts":true}}' -- --locked
else
  npm run tauri -- build -- --locked
fi

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
