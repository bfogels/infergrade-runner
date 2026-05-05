#!/usr/bin/env python3
"""Write a Tauri updater manifest for the desktop Runner app."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="write_desktop_update_manifest")
    parser.add_argument("--bundle-dir", help="Directory containing one Tauri updater archive.")
    parser.add_argument(
        "--artifact",
        action="append",
        default=[],
        metavar="PLATFORM=PATH",
        help="Explicit signed updater artifact to include. May be repeated for multi-platform manifests.",
    )
    parser.add_argument("--version", required=True, help="Application version to advertise.")
    parser.add_argument("--base-url", required=True, help="Release download URL prefix.")
    parser.add_argument("--output", required=True, help="Path to write the updater manifest.")
    parser.add_argument("--notes", default="InferGrade Runner desktop update.", help="Release notes.")
    parser.add_argument("--platform", default="darwin-aarch64", help="Tauri updater platform key.")
    return parser


def platform_artifact_from_bundle_dir(bundle_dir: Path, platform: str) -> tuple[str, Path]:
    archives = sorted(bundle_dir.glob("*.tar.gz"))
    if len(archives) != 1:
        raise SystemExit("Expected exactly one updater .tar.gz archive in %s, found %s" % (bundle_dir, len(archives)))
    return platform, archives[0]


def platform_artifact_from_arg(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise SystemExit("--artifact must use PLATFORM=PATH")
    platform, artifact = value.split("=", 1)
    platform = platform.strip()
    if not platform:
        raise SystemExit("--artifact platform cannot be empty")
    artifact_path = Path(artifact)
    if not artifact_path.is_file():
        raise SystemExit("Updater artifact does not exist: %s" % artifact_path)
    return platform, artifact_path


def signature_for_artifact(archive: Path) -> Path:
    signature_path = archive.with_suffix(archive.suffix + ".sig")
    if not signature_path.exists():
        raise SystemExit("No signature file found for %s" % archive)
    return signature_path


def main() -> int:
    args = build_parser().parse_args()
    if bool(args.bundle_dir) == bool(args.artifact):
        raise SystemExit("Provide either --bundle-dir or one or more --artifact entries.")

    platform_artifacts = []
    if args.bundle_dir:
        platform_artifacts.append(platform_artifact_from_bundle_dir(Path(args.bundle_dir), args.platform))
    for artifact_arg in args.artifact:
        platform_artifacts.append(platform_artifact_from_arg(artifact_arg))

    base_url = args.base_url.rstrip("/")
    platforms = {}
    for platform, archive in platform_artifacts:
        if platform in platforms:
            raise SystemExit("Duplicate updater platform: %s" % platform)
        signature_path = signature_for_artifact(archive)
        platforms[platform] = {
            "signature": signature_path.read_text(encoding="utf-8").strip(),
            "url": "%s/%s" % (base_url, quote(archive.name)),
        }

    manifest = {
        "version": args.version,
        "notes": args.notes,
        "pub_date": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "platforms": platforms,
    }
    output = Path(args.output)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("desktop_runner_update_manifest=%s" % output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
