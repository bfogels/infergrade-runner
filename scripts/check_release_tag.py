#!/usr/bin/env python3
"""Fail closed when a version tag does not describe the checked-out release."""

import argparse
import subprocess
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]


def validate_release_tag(
    tag: str,
    *,
    root: Path = ROOT,
    commit: Optional[str] = None,
    main_ref: Optional[str] = None,
) -> None:
    """Require the tag to match VERSION and, when requested, belong to main."""
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    expected = "v%s" % version
    if tag != expected:
        raise ValueError("Release tag %r does not match VERSION %r (expected %r)." % (tag, version, expected))
    if bool(commit) != bool(main_ref):
        raise ValueError("Provide both commit and main_ref when checking release ancestry.")
    if commit and main_ref:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, main_ref],
            cwd=root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or "%s is not an ancestor of %s" % (commit, main_ref)
            raise ValueError("Release tag must point to main history: %s" % detail)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="check_release_tag")
    parser.add_argument("--tag", required=True, help="Tag name to compare with VERSION, for example v0.3.36.")
    parser.add_argument("--commit", help="Tagged commit to verify against --main-ref.")
    parser.add_argument("--main-ref", help="Fetched main reference, normally origin/main.")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        validate_release_tag(
            args.tag,
            root=args.root,
            commit=args.commit,
            main_ref=args.main_ref,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print("release_tag=valid tag=%s" % args.tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
