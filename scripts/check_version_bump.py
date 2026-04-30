#!/usr/bin/env python3
"""Require a VERSION bump on pull requests into main after VERSION exists."""

import argparse
import pathlib
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]


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
    if current == base:
        print(
            f"VERSION must change for PRs into main; current and {args.base_ref} are both {current}.",
            file=sys.stderr,
        )
        return 1
    print(f"VERSION changed from {base} to {current}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
