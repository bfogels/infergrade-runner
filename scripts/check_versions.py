#!/usr/bin/env python3
"""Check that Runner source version declarations stay in lockstep."""

import json
import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def json_version(path: str) -> str:
    return json.loads(read(path))["version"]


def regex_version(path: str, pattern: str) -> str:
    match = re.search(pattern, read(path), re.MULTILINE)
    if not match:
        raise AssertionError(f"{path}: version pattern not found")
    return match.group(1)


CHECKS = {
    "python/runner-core/pyproject.toml": lambda: regex_version(
        "python/runner-core/pyproject.toml", r'^version = "([^"]+)"$'
    ),
    "python/runner-core/setup.py": lambda: regex_version(
        "python/runner-core/setup.py", r'version="([^"]+)"'
    ),
    "python/runner-core/src/infergrade/__init__.py": lambda: regex_version(
        "python/runner-core/src/infergrade/__init__.py", r'^__version__ = "([^"]+)"$'
    ),
    "apps/desktop-runner/package.json": lambda: json_version("apps/desktop-runner/package.json"),
    "apps/desktop-runner/package-lock.json": lambda: json_version("apps/desktop-runner/package-lock.json"),
    "apps/desktop-runner/src-tauri/tauri.conf.json": lambda: json_version(
        "apps/desktop-runner/src-tauri/tauri.conf.json"
    ),
    "apps/desktop-runner/src-tauri/Cargo.toml": lambda: regex_version(
        "apps/desktop-runner/src-tauri/Cargo.toml", r'^version = "([^"]+)"$'
    ),
    "apps/runner-cli/Cargo.toml": lambda: regex_version(
        "apps/runner-cli/Cargo.toml", r'^version = "([^"]+)"$'
    ),
    "crates/runner-engine/Cargo.toml": lambda: regex_version(
        "crates/runner-engine/Cargo.toml", r'^version = "([^"]+)"$'
    ),
    "Cargo.lock infergrade-runner-cli": lambda: regex_version(
        "Cargo.lock",
        r'name = "infergrade-runner-cli"\nversion = "([^"]+)"',
    ),
    "Cargo.lock infergrade_desktop_runner": lambda: regex_version(
        "Cargo.lock",
        r'name = "infergrade_desktop_runner"\nversion = "([^"]+)"',
    ),
    "Cargo.lock infergrade_runner_engine": lambda: regex_version(
        "Cargo.lock",
        r'name = "infergrade_runner_engine"\nversion = "([^"]+)"',
    ),
}


def main() -> int:
    failures = []
    for label, getter in CHECKS.items():
        actual = getter()
        normalized = actual[1:] if actual.startswith("v") else actual
        if normalized != EXPECTED:
            failures.append(f"{label}: {actual!r} != VERSION {EXPECTED!r}")
    cargo_lock = read("Cargo.lock")
    for package_name in ("libredox", "winapi-util"):
        third_party_lock_match = re.search(
            r'name = "%s"\nversion = "([^"]+)"' % re.escape(package_name),
            cargo_lock,
        )
        if third_party_lock_match and third_party_lock_match.group(1) == EXPECTED:
            failures.append(
                "Cargo.lock: third-party %s version was changed to VERSION"
                % package_name
            )
    if failures:
        print("Version declarations are out of sync:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"All checked Runner versions match {EXPECTED}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
