#!/usr/bin/env python3
"""Export the InferGrade Runner release bundle."""

import argparse
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
RUNNER_SRC = SCRIPT_ROOT / "python" / "runner-core" / "src"
if str(RUNNER_SRC) not in sys.path:
    sys.path.insert(0, str(RUNNER_SRC))

from infergrade.releases import export_release_bundle


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for release bundle export."""
    parser = argparse.ArgumentParser(prog="export_release_bundle")
    parser.add_argument("--output-dir", help="Optional export root. Defaults to dist/releases under the repo root.")
    parser.add_argument("--release-version", help="Optional release identifier. Defaults to INFERGRADE_RELEASE_VERSION or the preview lane.")
    return parser


def main() -> int:
    """Export the release bundle and print the bundle directory."""
    args = build_parser().parse_args()
    bundle_dir = export_release_bundle(
        output_dir=Path(args.output_dir) if args.output_dir else None,
        release_version=args.release_version,
    )
    print(bundle_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
