#!/usr/bin/env python3
"""Classify the safe main-to-develop synchronization path."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def _is_ancestor(repository: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError(result.stderr.strip() or "git merge-base failed")
    return result.returncode == 0


def branch_sync_mode(repository: Path, main_ref: str, develop_ref: str) -> str:
    """Return the only safe synchronization shape for the two refs."""
    if _is_ancestor(repository, main_ref, develop_ref):
        return "already_synced"
    if _is_ancestor(repository, develop_ref, main_ref):
        return "ancestry_pr"
    return "integration_pr"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--main-ref", default="origin/main")
    parser.add_argument("--develop-ref", default="origin/develop")
    args = parser.parse_args()
    print(branch_sync_mode(args.repository, args.main_ref, args.develop_ref))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
