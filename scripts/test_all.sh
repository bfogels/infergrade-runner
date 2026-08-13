#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Release-identity tests must exercise the Runner's version-matched defaults,
# not developer image overrides inherited from the invoking shell.
unset \
  INFERGRADE_IFEVAL_IMAGE \
  INFERGRADE_EVALPLUS_IMAGE \
  INFERGRADE_MMLU_PRO_IMAGE \
  INFERGRADE_GPQA_IMAGE \
  INFERGRADE_BFCL_IMAGE \
  INFERGRADE_REPOSITORY_EDIT_IMAGE

PYTHONPATH="$ROOT_DIR/python/runner-core/src${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m unittest discover -s "$ROOT_DIR/python/runner-core/tests"

PYTHONPATH="$ROOT_DIR/python/runner-core/src${PYTHONPATH:+:$PYTHONPATH}" \
  python3 "$ROOT_DIR/scripts/audit_benchmark_tiers.py" --fail-invalid >/dev/null

# Rust tests are owned by the dedicated `rust` CI job and the local
# `cargo test --workspace` workflow. Opt in here only when explicitly
# requested -- presence of `cargo` is not a strong enough signal because
# GitHub-hosted runners ship with rustup/cargo preinstalled.
if [ "${INFERGRADE_RUN_RUST_TESTS:-0}" = "1" ]; then
  if command -v cargo >/dev/null 2>&1; then
    echo "==> cargo build (engine + CLI + sidecar)"
    (cd "$ROOT_DIR" && cargo build --workspace --exclude infergrade_desktop_runner --locked)
    echo "==> cargo test (engine + CLI + sidecar)"
    (cd "$ROOT_DIR" && cargo test --workspace --exclude infergrade_desktop_runner --locked)
  else
    echo "INFERGRADE_RUN_RUST_TESTS=1 but cargo not found on PATH." >&2
    exit 1
  fi
fi
