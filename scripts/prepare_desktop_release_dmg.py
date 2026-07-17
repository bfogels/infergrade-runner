#!/usr/bin/env python3
"""Give the notarized macOS installer one stable public release filename."""

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_PUBLIC_DMG_NAME = "InferGrade.Runner.macOS-arm64.dmg"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prepare_desktop_release_dmg")
    parser.add_argument("--dmg-dir", required=True, help="Directory containing exactly one notarized DMG.")
    parser.add_argument(
        "--output-name",
        default=DEFAULT_PUBLIC_DMG_NAME,
        help="Stable public DMG filename. Defaults to %(default)s.",
    )
    return parser


def prepare_public_dmg(dmg_dir: Path, output_name: str = DEFAULT_PUBLIC_DMG_NAME) -> Path:
    if not output_name or Path(output_name).name != output_name or not output_name.endswith(".dmg"):
        raise ValueError("Public DMG output name must be one plain .dmg filename.")
    if not dmg_dir.is_dir():
        raise ValueError(f"DMG directory does not exist: {dmg_dir}")

    dmgs = sorted(path for path in dmg_dir.glob("*.dmg") if path.is_file())
    if len(dmgs) != 1:
        raise ValueError(f"Expected exactly one DMG in {dmg_dir}, found {len(dmgs)}.")

    source = dmgs[0]
    destination = dmg_dir / output_name
    if source != destination:
        if destination.exists():
            raise ValueError(f"Stable public DMG path already exists: {destination}")
        source.replace(destination)
    return destination


def main() -> int:
    args = build_parser().parse_args()
    try:
        destination = prepare_public_dmg(Path(args.dmg_dir), args.output_name)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(f"desktop_public_dmg={destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
