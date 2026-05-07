#!/usr/bin/env python3
"""Verify downloaded desktop Runner release artifacts against local manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urlparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="verify_desktop_release_artifacts")
    parser.add_argument("--directory", required=True, help="Directory containing downloaded release artifacts.")
    parser.add_argument(
        "--checksums",
        default="SHA256SUMS",
        help="Checksum manifest filename or path. Defaults to SHA256SUMS inside --directory.",
    )
    parser.add_argument(
        "--update-manifest",
        default="infergrade-runner-desktop-latest.json",
        help="Updater manifest filename or path. Defaults to infergrade-runner-desktop-latest.json inside --directory.",
    )
    parser.add_argument("--require-dmg", action="store_true", help="Require at least one DMG artifact.")
    parser.add_argument(
        "--require-updater",
        action="store_true",
        help="Require an updater manifest, updater archive, and updater signature.",
    )
    return parser


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_manifest_path(directory: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = directory / path
    return path


def parse_checksum_manifest(path: Path) -> list[tuple[str, str]]:
    if not path.is_file():
        raise SystemExit(f"Checksum manifest does not exist: {path}")
    entries: list[tuple[str, str]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        if "  " not in line:
            raise SystemExit(f"{path}:{line_number}: expected '<sha256>  <filename>'")
        digest, name = line.split("  ", 1)
        name = name.strip()
        if len(digest) != 64 or not all(ch in "0123456789abcdefABCDEF" for ch in digest):
            raise SystemExit(f"{path}:{line_number}: invalid SHA-256 digest")
        if not name or Path(name).is_absolute() or "/" in name or "\\" in name or name in {".", ".."}:
            raise SystemExit(f"{path}:{line_number}: checksum filename must be a plain artifact filename")
        entries.append((digest.lower(), name))
    if not entries:
        raise SystemExit(f"Checksum manifest is empty: {path}")
    return entries


def verify_checksums(directory: Path, checksum_path: Path) -> list[Path]:
    verified: list[Path] = []
    seen: set[str] = set()
    for expected, name in parse_checksum_manifest(checksum_path):
        if name in seen:
            raise SystemExit(f"Duplicate checksum entry: {name}")
        seen.add(name)
        artifact = directory / name
        if not artifact.is_file():
            raise SystemExit(f"Missing checksummed artifact: {artifact}")
        actual = sha256_file(artifact)
        if actual != expected:
            raise SystemExit(f"Checksum mismatch for {name}: expected {expected}, got {actual}")
        verified.append(artifact)
    return verified


def artifact_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = unquote(Path(parsed.path).name)
    if not name:
        raise SystemExit(f"Updater manifest URL is missing an artifact filename: {url}")
    return name


def require_checksum_coverage(verified_names: set[str], artifact: Path) -> None:
    if artifact.name not in verified_names:
        raise SystemExit(f"Release artifact is not covered by SHA256SUMS: {artifact.name}")


def verify_update_manifest(
    directory: Path,
    manifest_path: Path,
    require_updater: bool,
    verified_names: set[str],
) -> None:
    if not manifest_path.exists():
        if require_updater:
            raise SystemExit(f"Updater manifest does not exist: {manifest_path}")
        return
    require_checksum_coverage(verified_names, manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = str(manifest.get("version", "")).strip()
    platforms = manifest.get("platforms")
    if not version:
        raise SystemExit("Updater manifest is missing version.")
    if not isinstance(platforms, dict) or not platforms:
        raise SystemExit("Updater manifest must include one or more platforms.")
    for platform, payload in platforms.items():
        if not isinstance(payload, dict):
            raise SystemExit(f"Updater platform {platform!r} must be an object.")
        signature = str(payload.get("signature", "")).strip()
        url = str(payload.get("url", "")).strip()
        if not signature:
            raise SystemExit(f"Updater platform {platform!r} is missing a signature.")
        if not url.startswith("https://"):
            raise SystemExit(f"Updater platform {platform!r} must use an HTTPS artifact URL.")
        archive_name = artifact_name_from_url(url)
        archive = directory / archive_name
        signature_file = directory / f"{archive_name}.sig"
        if not archive.is_file():
            raise SystemExit(f"Updater archive listed in manifest is missing: {archive}")
        if not signature_file.is_file():
            raise SystemExit(f"Updater signature artifact is missing: {signature_file}")
        require_checksum_coverage(verified_names, archive)
        require_checksum_coverage(verified_names, signature_file)
        signature_file_value = signature_file.read_text(encoding="utf-8").strip()
        if not signature_file_value:
            raise SystemExit(f"Updater signature artifact is empty: {signature_file}")
        if signature_file_value != signature:
            raise SystemExit(f"Updater manifest signature does not match signature artifact: {signature_file}")


def main() -> int:
    args = build_parser().parse_args()
    directory = Path(args.directory)
    if not directory.is_dir():
        raise SystemExit(f"Release artifact directory does not exist: {directory}")
    checksum_path = resolve_manifest_path(directory, args.checksums)
    update_manifest_path = resolve_manifest_path(directory, args.update_manifest)

    verified = verify_checksums(directory, checksum_path)
    if args.require_dmg and not any(path.suffix == ".dmg" for path in verified):
        raise SystemExit("No DMG artifact was verified.")
    verified_names = {path.name for path in verified}
    verify_update_manifest(directory, update_manifest_path, args.require_updater, verified_names)

    print(f"desktop_release_artifact_dir={directory}")
    print(f"desktop_release_checksums={checksum_path}")
    print(f"desktop_release_artifacts_verified={len(verified)}")
    print("desktop_release_updater_manifest=%s" % (update_manifest_path if update_manifest_path.exists() else "not_checked"))
    print("desktop_release_notarization=not_checked_by_artifact_manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
