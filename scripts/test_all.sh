#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONPATH="$ROOT_DIR/python/runner-core/src${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m unittest discover -s "$ROOT_DIR/python/runner-core/tests"

if command -v cargo >/dev/null 2>&1; then
  echo "==> cargo build (engine + CLI + sidecar)"
  (cd "$ROOT_DIR" && cargo build --workspace --exclude infergrade_desktop_runner --locked)
  echo "==> cargo test (engine + CLI + sidecar)"
  (cd "$ROOT_DIR" && cargo test --workspace --exclude infergrade_desktop_runner --locked)
else
  echo "cargo not found on PATH; skipping Rust workspace tests." >&2
fi
