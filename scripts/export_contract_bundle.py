#!/usr/bin/env python3
"""Export the InferGrade Runner contract bundle."""

import argparse
from pathlib import Path

from infergrade.contracts import export_contract_bundle


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for contract export."""
    parser = argparse.ArgumentParser(prog="export_contract_bundle")
    parser.add_argument(
        "--output-dir",
        help="Optional export root. Defaults to dist/contracts under the repo root.",
    )
    return parser


def main() -> int:
    """Export the contract bundle and print the bundle directory."""
    args = build_parser().parse_args()
    bundle_dir = export_contract_bundle(output_dir=Path(args.output_dir) if args.output_dir else None)
    print(bundle_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
