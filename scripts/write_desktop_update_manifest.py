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
    parser.add_argument("--bundle-dir", required=True, help="Directory containing Tauri updater archives.")
    parser.add_argument("--version", required=True, help="Application version to advertise.")
    parser.add_argument("--base-url", required=True, help="Release download URL prefix.")
    parser.add_argument("--output", required=True, help="Path to write the updater manifest.")
    parser.add_argument("--notes", default="InferGrade Runner desktop update.", help="Release notes.")
    parser.add_argument("--platform", default="darwin-aarch64", help="Tauri updater platform key.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    bundle_dir = Path(args.bundle_dir)
    archives = sorted(bundle_dir.glob("*.tar.gz"))
    if len(archives) != 1:
        raise SystemExit("Expected exactly one updater .tar.gz archive in %s, found %s" % (bundle_dir, len(archives)))
    archive = archives[0]
    signature_path = archive.with_suffix(archive.suffix + ".sig")
    if not signature_path.exists():
        raise SystemExit("No signature file found for %s" % archive)
    base_url = args.base_url.rstrip("/")
    manifest = {
        "version": args.version,
        "notes": args.notes,
        "pub_date": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "platforms": {
            args.platform: {
                "signature": signature_path.read_text(encoding="utf-8").strip(),
                "url": "%s/%s" % (base_url, quote(archive.name)),
            }
        },
    }
    output = Path(args.output)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("desktop_runner_update_manifest=%s" % output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
