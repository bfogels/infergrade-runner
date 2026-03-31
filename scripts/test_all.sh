#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHONPATH="$ROOT_DIR/python/runner-core/src${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m unittest discover -s "$ROOT_DIR/python/runner-core/tests"
