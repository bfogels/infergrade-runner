#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIDECAR_DIR="$ROOT_DIR/apps/desktop-runner/sidecar"
BINARIES_DIR="$ROOT_DIR/apps/desktop-runner/src-tauri/binaries"
CHECK_ONLY=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --check-only)
      CHECK_ONLY=1
      ;;
    *)
      echo "Usage: $0 [--check-only]" >&2
      exit 2
      ;;
  esac
  shift
done

if ! command -v cargo >/dev/null 2>&1; then
  echo "cargo is required to build the desktop Runner sidecar. Install Rust first." >&2
  exit 1
fi

TARGET_TRIPLE="${INFERGRADE_DESKTOP_SIDECAR_TARGET:-$(rustc -Vv | awk '/host:/ {print $2}')}"
if [ -z "$TARGET_TRIPLE" ]; then
  echo "Could not resolve Rust host target triple from rustc -Vv." >&2
  exit 1
fi

EXE_SUFFIX=""
case "$TARGET_TRIPLE" in
  *windows* | x86_64-pc-windows-msvc | aarch64-pc-windows-msvc)
    EXE_SUFFIX=".exe"
    ;;
esac

if [ "$CHECK_ONLY" -eq 1 ]; then
  cargo check --manifest-path "$SIDECAR_DIR/Cargo.toml" --locked
  exit 0
fi

if [ -n "${INFERGRADE_DESKTOP_SIDECAR_TARGET:-}" ]; then
  cargo build --manifest-path "$SIDECAR_DIR/Cargo.toml" --release --locked --target "$TARGET_TRIPLE"
  BUILT_BINARY="$SIDECAR_DIR/target/$TARGET_TRIPLE/release/infergrade-sidecar${EXE_SUFFIX}"
else
  cargo build --manifest-path "$SIDECAR_DIR/Cargo.toml" --release --locked
  BUILT_BINARY="$SIDECAR_DIR/target/release/infergrade-sidecar${EXE_SUFFIX}"
fi

if [ ! -f "$BUILT_BINARY" ]; then
  echo "Expected sidecar binary was not built at $BUILT_BINARY" >&2
  exit 1
fi

mkdir -p "$BINARIES_DIR"
OUTPUT_BINARY="$BINARIES_DIR/infergrade-sidecar-${TARGET_TRIPLE}${EXE_SUFFIX}"
cp "$BUILT_BINARY" "$OUTPUT_BINARY"
if [ "$EXE_SUFFIX" != ".exe" ]; then
  chmod 755 "$OUTPUT_BINARY"
fi

size_bytes="$(wc -c < "$OUTPUT_BINARY" | tr -d ' ')"
echo "desktop_runner_sidecar=$OUTPUT_BINARY"
echo "desktop_runner_sidecar_size_bytes=$size_bytes"
