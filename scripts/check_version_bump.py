#!/usr/bin/env python3
"""Require a VERSION bump on pull requests into main after VERSION exists."""

import argparse
import pathlib
import re
import subprocess
import sys
from typing import Tuple


ROOT = pathlib.Path(__file__).resolve().parents[1]
RELEASE_VERSION_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def parse_release_version(value: str) -> Tuple[int, int, int]:
    match = RELEASE_VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"VERSION must use MAJOR.MINOR.PATCH integers; got {value!r}.")
    return tuple(int(component) for component in match.groups())


def validate_forward_version(current: str, base: str) -> None:
    current_parts = parse_release_version(current)
    base_parts = parse_release_version(base)
    if current_parts <= base_parts:
        raise ValueError(f"VERSION must move forward from {base}; got {current}.")


def git_show(ref: str, path: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{ref}:{path}"],
        cwd=ROOT,
        stderr=subprocess.DEVNULL,
        text=True,
    ).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", required=True)
    args = parser.parse_args()

    current = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    try:
        base = git_show(args.base_ref, "VERSION")
    except subprocess.CalledProcessError:
        print("Base branch has no VERSION file yet; skipping first bump enforcement.")
        return 0
    try:
        validate_forward_version(current, base)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"VERSION moved forward from {base} to {current}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
