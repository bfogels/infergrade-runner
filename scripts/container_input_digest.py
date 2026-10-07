#!/usr/bin/env python3
"""Fingerprint everything that can change a container image built from this repo.

The digest covers the Dockerfile text (including ARG pins), every file reached by
its COPY/ADD sources, the target platforms, and the resolved base-image digest.
Release publishing reuses an already-published image whose fingerprint matches
instead of rebuilding it, so unchanged images keep byte-identical digests across
Runner versions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
from pathlib import Path
from typing import Iterable, List

SCHEMA = "infergrade-container-inputs-v1"


def _logical_lines(text: str) -> Iterable[str]:
    current = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if not current and line.lstrip().startswith("#"):
            continue
        if line.endswith("\\"):
            current += line[:-1] + " "
            continue
        current += line
        if current.strip():
            yield current.strip()
        current = ""
    if current.strip():
        yield current.strip()


def copy_sources(dockerfile_text: str) -> List[str]:
    """Return repository-relative COPY/ADD sources, skipping copies between stages."""
    sources: List[str] = []
    for line in _logical_lines(dockerfile_text):
        parts = line.split(None, 1)
        if len(parts) != 2 or parts[0].upper() not in ("COPY", "ADD"):
            continue
        rest = parts[1].strip()
        if rest.startswith("["):
            tokens = json.loads(rest)
        else:
            tokens = shlex.split(rest)
        flags = [t for t in tokens if t.startswith("--")]
        if any(f.startswith("--from=") for f in flags):
            continue
        paths = [t for t in tokens if not t.startswith("--")]
        if len(paths) < 2:
            raise ValueError("Unparseable %s instruction: %s" % (parts[0], line))
        for source in paths[:-1]:
            if "://" in source:
                raise ValueError("Remote ADD sources are not fingerprintable: %s" % source)
            sources.append(source)
    return sources


def base_images(dockerfile_text: str) -> List[str]:
    """Return external FROM images (stage aliases and scratch excluded)."""
    stages, images = set(), []
    for line in _logical_lines(dockerfile_text):
        parts = line.split()
        if not parts or parts[0].upper() != "FROM":
            continue
        tokens = [t for t in parts[1:] if not t.startswith("--")]
        ref = tokens[0]
        if ref not in stages and ref != "scratch" and ref not in images:
            images.append(ref)
        if len(tokens) >= 3 and tokens[1].upper() == "AS":
            stages.add(tokens[2])
    return images


def _files_under(root: Path, source: str) -> List[Path]:
    matches = sorted(root.glob(source)) if any(c in source for c in "*?[") else [root / source]
    files: List[Path] = []
    for match in matches:
        if not match.exists():
            raise FileNotFoundError("COPY source does not exist: %s" % source)
        if match.is_dir():
            files.extend(
                p for p in sorted(match.rglob("*"))
                if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
            )
        else:
            files.append(match)
    return files


def input_digest(root: Path, dockerfile: str, platforms: str, base_digest: str = "") -> str:
    dockerfile_path = root / dockerfile
    text = dockerfile_path.read_text(encoding="utf-8")
    digest = hashlib.sha256()

    def feed(label: str, payload: bytes) -> None:
        digest.update(label.encode("utf-8") + b"\0")
        digest.update(str(len(payload)).encode("ascii") + b"\0")
        digest.update(payload)

    feed("schema", SCHEMA.encode())
    feed("dockerfile", text.encode("utf-8"))
    feed("platforms", ",".join(sorted(p.strip() for p in platforms.split(",") if p.strip())).encode())
    feed("base", base_digest.strip().encode())
    seen = set()
    for source in copy_sources(text):
        for path in _files_under(root, source):
            rel = path.relative_to(root).as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            feed("file:" + rel, path.read_bytes())
    return digest.hexdigest()


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dockerfile", required=True, help="Dockerfile path relative to --root")
    parser.add_argument("--platforms", required=True, help="Comma-separated build platforms")
    parser.add_argument("--base-digest", default="", help="Resolved digest of the FROM image")
    parser.add_argument("--root", default=".", help="Build context (repository root)")
    parser.add_argument("--short", action="store_true", help="Print the 20-character tag form")
    parser.add_argument("--print-base-images", action="store_true", help="Print FROM images, one per line, and exit")
    args = parser.parse_args(argv)
    if args.print_base_images:
        text = (Path(args.root).resolve() / args.dockerfile).read_text(encoding="utf-8")
        print("\n".join(base_images(text)))
        return 0
    value = input_digest(Path(args.root).resolve(), args.dockerfile, args.platforms, args.base_digest)
    print(value[:20] if args.short else value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
