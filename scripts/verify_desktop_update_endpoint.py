#!/usr/bin/env python3
"""Verify that desktop updater metadata and archives are anonymously reachable."""

from __future__ import annotations

import argparse
import json
import ssl
import time
from typing import Any, Callable
from urllib.request import Request, urlopen


def anonymous_urlopen(request: Request, timeout: int = 30):
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    return urlopen(request, timeout=timeout, context=context)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="verify_desktop_update_endpoint")
    parser.add_argument("--url", required=True, help="Public HTTPS Tauri updater manifest URL.")
    parser.add_argument("--expected-version", default="", help="Version the manifest must advertise.")
    return parser


def fetch(request: Request, opener: Callable[..., Any], read_limit: int | None = None) -> bytes:
    with opener(request, timeout=30) as response:
        status = getattr(response, "status", 200)
        if status < 200 or status >= 300:
            raise SystemExit(f"Updater endpoint returned HTTP {status}: {request.full_url}")
        return response.read(read_limit) if read_limit is not None else response.read()


def verify_manifest(
    url: str,
    expected_version: str = "",
    opener: Callable[..., Any] = anonymous_urlopen,
    attempts: int = 4,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if not url.startswith("https://"):
        raise SystemExit("Updater manifest URL must use HTTPS.")
    manifest_request = Request(url, headers={"User-Agent": "InferGrade-Desktop-Release-Verification/1"})
    try:
        manifest = json.loads(fetch(manifest_request, opener).decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"Updater manifest is not anonymously readable JSON: {url}: {error}") from error
    version = str(manifest.get("version", "")).strip()
    if not version:
        raise SystemExit("Updater manifest is missing version.")
    if expected_version and version != expected_version:
        raise SystemExit(f"Updater manifest version mismatch: expected {expected_version}, got {version}")
    platforms = manifest.get("platforms")
    if not isinstance(platforms, dict) or not platforms:
        raise SystemExit("Updater manifest must include one or more platforms.")
    for platform, payload in platforms.items():
        artifact_url = str(payload.get("url", "")).strip() if isinstance(payload, dict) else ""
        signature = str(payload.get("signature", "")).strip() if isinstance(payload, dict) else ""
        if not artifact_url.startswith("https://") or not signature:
            raise SystemExit(f"Updater platform {platform!r} is missing a public HTTPS URL or signature.")
        artifact_request = Request(
            artifact_url,
            headers={
                "Range": "bytes=0-0",
                "User-Agent": "InferGrade-Desktop-Release-Verification/1",
            },
        )
        last_error = None
        for attempt in range(max(1, attempts)):
            try:
                fetch(artifact_request, opener, read_limit=1)
                last_error = None
                break
            except OSError as error:
                last_error = error
                if attempt + 1 < max(1, attempts):
                    sleeper(2**attempt)
        if last_error is not None:
            raise SystemExit(f"Updater archive is not anonymously reachable: {artifact_url}: {last_error}") from last_error
    return manifest


def main() -> int:
    args = build_parser().parse_args()
    manifest = verify_manifest(args.url, args.expected_version)
    print(f"desktop_update_endpoint={args.url}")
    print(f"desktop_update_version={manifest['version']}")
    print(f"desktop_update_platforms={len(manifest['platforms'])}")
    print("desktop_update_anonymous_access=verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
