#!/usr/bin/env python3
"""Write SHA-256 checksums for desktop Runner release artifacts."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="write_desktop_release_checksums")
    parser.add_argument("--output", required=True, help="Path to write the checksum manifest.")
    parser.add_argument("artifacts", nargs="+", help="Release artifact paths to hash.")
    return parser


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    args = build_parser().parse_args()
    output = Path(args.output)
    candidates = [Path(item) for item in args.artifacts]
    missing = [str(path) for path in candidates if not path.exists()]
    if missing:
        raise SystemExit("Missing release artifact(s): %s" % ", ".join(missing))

    artifacts = [path for path in candidates if path.is_file()]
    if not artifacts:
        raise SystemExit("No release artifacts were provided.")

    deduped = sorted({path.resolve() for path in artifacts}, key=lambda path: path.name)
    lines = ["%s  %s" % (sha256_file(path), path.name) for path in deduped]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("desktop_runner_sha256s=%s" % output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
