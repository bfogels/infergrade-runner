#!/usr/bin/env python3
"""Sync required package manifest versions from the root VERSION file."""

from __future__ import annotations

import argparse
import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[1]


def read_version(root: pathlib.Path) -> str:
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
        raise ValueError(f"VERSION must be SemVer-like, got {version!r}")
    return version


def replace_text(
    root: pathlib.Path,
    path: str,
    pattern: str,
    replacement: str,
    dry_run: bool = False,
    count: int = 1,
) -> bool:
    full_path = root / path
    original = full_path.read_text(encoding="utf-8")
    updated, replacements = re.subn(pattern, replacement, original, count=count, flags=re.MULTILINE)
    if replacements != count:
        raise ValueError(f"{path}: version pattern not found")
    if updated == original:
        return False
    if not dry_run:
        full_path.write_text(updated, encoding="utf-8")
    return True


def sync_versions(root: pathlib.Path = ROOT, dry_run: bool = False) -> list[str]:
    version = read_version(root)
    changed: list[str] = []

    text_replacements = {
        "python/runner-core/pyproject.toml": (
            r'^version = "[^"]+"$',
            f'version = "{version}"',
        ),
        "python/runner-core/setup.py": (
            r'version="[^"]+"',
            f'version="{version}"',
        ),
        "python/runner-core/src/infergrade/__init__.py": (
            r'^__version__ = "[^"]+"$',
            f'__version__ = "{version}"',
        ),
        "apps/desktop-runner/src-tauri/Cargo.toml": (
            r'^version = "[^"]+"$',
            f'version = "{version}"',
        ),
        "apps/desktop-runner/package.json": (
            r'("version"\s*:\s*)"[^"]+"',
            rf'\1"{version}"',
        ),
        "apps/desktop-runner/src-tauri/tauri.conf.json": (
            r'("version"\s*:\s*)"[^"]+"',
            rf'\1"{version}"',
        ),
        "apps/desktop-runner/src-tauri/Cargo.lock": (
            r'(name = "infergrade_desktop_runner"\nversion = )"[^"]+"',
            rf'\1"{version}"',
        ),
    }
    for path, (pattern, replacement) in text_replacements.items():
        if replace_text(root, path, pattern, replacement, dry_run=dry_run):
            changed.append(path)

    if replace_text(
        root,
        "apps/desktop-runner/package-lock.json",
        r'("version"\s*:\s*)"[^"]+"',
        rf'\1"{version}"',
        dry_run=dry_run,
        count=2,
    ):
        changed.append("apps/desktop-runner/package-lock.json")

    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if any required version copy is out of sync.")
    args = parser.parse_args()

    changed = sync_versions(ROOT, dry_run=args.check)
    if args.check and changed:
        print("Version copies were out of sync; run `python3 ./scripts/sync_versions.py` and commit the result.")
        for path in changed:
            print(f"  - {path}")
        return 1
    if changed:
        print("Updated version copy/copies:")
        for path in changed:
            print(f"  - {path}")
    else:
        print("All required version copies already match VERSION.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
