#!/usr/bin/env python3
"""Build an isolated materializer manifest from a verified archive receipt."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


PLATFORMS = {
    "macos-arm64": {
        "system": "macos",
        "arch": "aarch64",
        "accelerator": "metal",
        "asset": "llama-{tag}-bin-macos-arm64.tar.gz",
    },
    "ubuntu-x64": {
        "system": "linux",
        "arch": "x86_64",
        "accelerator": "cpu",
        "asset": "llama-{tag}-bin-ubuntu-x64.tar.gz",
    },
}


def load_object(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("archive receipt must be a JSON object")
    return value


def build_manifest(receipt: Dict[str, Any]) -> Dict[str, Any]:
    if receipt.get("candidate_only") is not True:
        raise ValueError("archive receipt must be candidate-only")
    if receipt.get("version_smoke", {}).get("status") != "passed":
        raise ValueError("archive receipt must include a passed version smoke")
    platform_name = str(receipt.get("platform") or "")
    if platform_name not in PLATFORMS:
        raise ValueError("immutable materialization supports only macos-arm64 and ubuntu-x64 receipts")
    platform = PLATFORMS[platform_name]
    upstream = receipt.get("upstream") or {}
    artifact = receipt.get("artifact") or {}
    tag = str(upstream.get("release") or "")
    if not tag.startswith("b") or not tag[1:].isdigit():
        raise ValueError("receipt release must use llama.cpp's bNNNN format")
    digest = str(artifact.get("downloaded_sha256") or "")
    if (
        digest != artifact.get("github_asset_sha256")
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("receipt archive digest is not verified")
    size = int(artifact.get("size_bytes") or 0)
    if size <= 0 or size > 512 * 1024 * 1024:
        raise ValueError("receipt archive size is outside the qualification bound")
    required = artifact.get("required_members")
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ValueError("receipt expected binary inventory is missing")
    for name in ("llama-cli", "llama-server"):
        if name not in required:
            raise ValueError(f"receipt is missing required binary {name}")
    url = str(artifact.get("download_url") or "")
    expected_name = str(platform["asset"]).format(tag=tag)
    expected_url = f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{expected_name}"
    if artifact.get("name") != expected_name or url != expected_url:
        raise ValueError("receipt archive URL is not the exact official release asset")

    runtime_id = f"llama-cpp-{tag}-{platform['system']}-{platform['arch']}-qualification"
    return {
        "runtime_id": runtime_id,
        "channel": "upstream_release",
        "backend": "llama.cpp",
        "accelerator": platform["accelerator"],
        "version_label": f"llama.cpp {tag} {platform_name} qualification",
        "upstream": {
            "project": "ggml-org/llama.cpp",
            "tag": tag,
            "release_url": str(upstream.get("url") or ""),
        },
        "platform": {"system": platform["system"], "arch": platform["arch"]},
        "archive": {
            "url": url,
            "sha256": digest,
            "size_bytes": size,
            "format": "tar.gz",
            "signature_url": None,
        },
        "download": {
            "requires_explicit_user_action": True,
            "message": "Maintainer qualification from a same-job verified official archive.",
        },
        "expected_binaries": required,
        "binary_names": {
            "cli": "llama-cli",
            "server": "llama-server",
            "perplexity": "llama-perplexity",
        },
        "rollback_runtime_id": "qualification-isolated-cache-only",
        "catalog_assertion": None,
        "provenance": (
            f"Official ggml-org/llama.cpp {tag} release archive verified against GitHub's "
            "asset digest in this job; no independent signature or signed InferGrade catalog assertion."
        ),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = build_manifest(load_object(args.archive_receipt))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
