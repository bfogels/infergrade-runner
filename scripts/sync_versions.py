#!/usr/bin/env python3
"""Sync required package manifest versions from the root VERSION file."""

from __future__ import annotations

import argparse
import json
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


def replace_named_json_version(
    root: pathlib.Path,
    path: str,
    pattern: str,
    replacement: str,
    dry_run: bool = False,
    expected_name: str | None = None,
) -> bool:
    full_path = root / path
    data = json.loads(full_path.read_text(encoding="utf-8"))
    if expected_name is not None and data.get("name", data.get("productName")) != expected_name:
        raise ValueError(f"{path}: expected manifest name {expected_name!r}")
    return replace_text(root, path, pattern, replacement, dry_run=dry_run)


def replace_package_lock_versions(root: pathlib.Path, version: str, dry_run: bool = False) -> bool:
    path = "apps/desktop-runner/package-lock.json"
    full_path = root / path
    original = full_path.read_text(encoding="utf-8")
    data = json.loads(original)
    if data.get("name") != "infergrade-desktop-runner":
        raise ValueError(f"{path}: top-level package name is not infergrade-desktop-runner")
    root_package = data.get("packages", {}).get("")
    if not isinstance(root_package, dict):
        raise ValueError(f"{path}: root package entry for infergrade-desktop-runner not found")
    if root_package.get("name", "infergrade-desktop-runner") != "infergrade-desktop-runner":
        raise ValueError(f"{path}: root package entry is not infergrade-desktop-runner")

    top_pattern = r'(\{\s*"name"\s*:\s*"infergrade-desktop-runner",\s*"version"\s*:\s*)"[^"]+"'
    if not re.search(top_pattern, original):
        raise ValueError(f"{path}: top-level version pattern not found")
    root_package_patterns = (
        r'("packages"\s*:\s*\{\s*""\s*:\s*\{\s*"name"\s*:\s*"infergrade-desktop-runner",\s*"version"\s*:\s*)"[^"]+"',
        r'("packages"\s*:\s*\{\s*""\s*:\s*\{\s*"version"\s*:\s*)"[^"]+"',
    )
    root_pattern = next((pattern for pattern in root_package_patterns if re.search(pattern, original)), None)
    if root_pattern is None:
        raise ValueError(f"{path}: root package version pattern not found")

    updated = re.sub(top_pattern, rf'\1"{version}"', original, count=1)
    updated = re.sub(root_pattern, rf'\1"{version}"', updated, count=1)
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
        "apps/desktop-runner/src-tauri/Cargo.lock": (
            r'(name = "(?:infergrade_desktop_runner|infergrade_runner_engine)"\nversion = )"[^"]+"',
            rf'\1"{version}"',
            2,
        ),
    }
    for path, replacement_args in text_replacements.items():
        pattern, replacement, *rest = replacement_args
        count = rest[0] if rest else 1
        if replace_text(root, path, pattern, replacement, dry_run=dry_run, count=count):
            changed.append(path)

    json_replacements = {
        "apps/desktop-runner/package.json": (
            r'(\{\s*"name"\s*:\s*"infergrade-desktop-runner",\s*"version"\s*:\s*)"[^"]+"',
            rf'\1"{version}"',
        ),
        "apps/desktop-runner/src-tauri/tauri.conf.json": (
            r'("version"\s*:\s*)"[^"]+"',
            rf'\1"{version}"',
        ),
    }
    for path, (pattern, replacement) in json_replacements.items():
        expected_name = "InferGrade Runner" if path.endswith("tauri.conf.json") else "infergrade-desktop-runner"
        if replace_named_json_version(root, path, pattern, replacement, dry_run=dry_run, expected_name=expected_name):
            changed.append(path)

    if replace_package_lock_versions(root, version, dry_run=dry_run):
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
