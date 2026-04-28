#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/apps/desktop-runner"
TAURI_DIR="$APP_DIR/src-tauri"
DMG_DIR="$TAURI_DIR/target/release/bundle/dmg"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to build the desktop Runner app." >&2
  exit 1
fi

if ! command -v cargo >/dev/null 2>&1; then
  echo "cargo is required to build the desktop Runner app. Install Rust first." >&2
  exit 1
fi

cd "$APP_DIR"
npm install
npm run build
npm audit --audit-level=moderate

cd "$TAURI_DIR"
cargo check

cd "$APP_DIR"
npm run tauri -- build

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

if [ "$found_artifact" -eq 0 ]; then
  echo "No DMG artifacts found in $DMG_DIR" >&2
  exit 1
fi
