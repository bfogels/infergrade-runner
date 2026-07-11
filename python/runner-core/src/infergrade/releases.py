"""Release bundle helpers for InferGrade Runner."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from infergrade import __version__
from infergrade.contracts import export_contract_bundle, load_contract_manifest, repo_root


KNOWN_RELEASE_IMAGES: List[Dict[str, str]] = [
    {
        "image_name": "infergrade-runner-core",
        "role": "runner_listener",
        "archive_name": "infergrade-runner-core_{release_version}.tar",
        "golden_path": "local_listener_container",
    },
    {
        "image_name": "infergrade-llama-cpp",
        "role": "deployment_runtime",
        "backend": "llama.cpp",
        "archive_name": "infergrade-llama-cpp_{release_version}.tar",
    },
    {
        "image_name": "infergrade-ifeval",
        "role": "capability_runtime",
        "benchmark_id": "ifeval",
        "archive_name": "infergrade-ifeval_{release_version}.tar",
    },
    {
        "image_name": "infergrade-evalplus",
        "role": "capability_runtime",
        "benchmark_id": "evalplus",
        "archive_name": "infergrade-evalplus_{release_version}.tar",
    },
    {
        "image_name": "infergrade-mmlu-pro",
        "role": "capability_runtime",
        "benchmark_id": "mmlu_pro",
        "archive_name": "infergrade-mmlu-pro_{release_version}.tar",
    },
]


def default_release_version() -> str:
    """Return the default local release identifier for the current runner version."""
    return (os.environ.get("INFERGRADE_RELEASE_VERSION") or __version__).strip()


def release_channel(release_version: str) -> str:
    """Derive a human-readable release channel from the release identifier."""
    if "-" in str(release_version):
        return str(release_version).split("-", 1)[1]
    return "stable"


def export_release_bundle(
    output_dir: Optional[Path] = None,
    root: Optional[Path] = None,
    release_version: Optional[str] = None,
) -> Path:
    """Export a versioned Runner release bundle with contract and runtime references."""
    base = Path(root) if root is not None else repo_root()
    resolved_release_version = str(release_version or default_release_version())
    destination_root = Path(output_dir) if output_dir is not None else (base / "dist" / "releases")
    release_dir = destination_root / resolved_release_version
    if release_dir.exists():
        shutil.rmtree(release_dir)
    release_dir.mkdir(parents=True, exist_ok=True)

    bundled_contract_dir = release_dir / "contract"
    if output_dir is None:
        contract_bundle_dir = export_contract_bundle(output_dir=(base / "dist" / "contracts"), root=base)
        shutil.copytree(contract_bundle_dir, bundled_contract_dir)
    else:
        with tempfile.TemporaryDirectory() as temp_contract_dir:
            contract_bundle_dir = export_contract_bundle(output_dir=Path(temp_contract_dir), root=base)
            shutil.copytree(contract_bundle_dir, bundled_contract_dir)

    image_archive_source_dir = base / "dist" / "images" / resolved_release_version
    bundled_image_dir = release_dir / "images"
    bundled_images = _copy_release_archives(image_archive_source_dir, bundled_image_dir)
    contract_files = _artifact_entries(bundled_contract_dir, release_dir, artifact_kind="contract_file")
    image_files = _artifact_entries(bundled_image_dir, release_dir, artifact_kind="image_archive") if bundled_image_dir.exists() else []

    contract_manifest = load_contract_manifest(base)
    runtime_images = []
    capability_images = []
    listener_image = None
    for item in KNOWN_RELEASE_IMAGES:
        image_ref = "ghcr.io/bfogels/%s:%s" % (item["image_name"], resolved_release_version)
        archive_name = item["archive_name"].format(release_version=resolved_release_version)
        archive_path = "images/%s" % archive_name if archive_name in bundled_images else None
        archive_sha256 = bundled_images.get(archive_name)
        payload = {
            "image_name": item["image_name"],
            "image_ref": image_ref,
            "role": item["role"],
            "archive_path": archive_path,
            "archive_sha256": archive_sha256,
        }
        if item.get("backend"):
            payload["backend"] = item["backend"]
        if item.get("benchmark_id"):
            payload["benchmark_id"] = item["benchmark_id"]
        if item.get("golden_path") == "local_listener_container":
            listener_image = payload
        if item["role"] == "capability_runtime":
            capability_images.append(payload)
        else:
            runtime_images.append(payload)

    manifest = {
        "release_manifest_version": "0.1",
        "publisher": "infergrade-runner",
        "release_version": resolved_release_version,
        "release_channel": release_channel(resolved_release_version),
        "runner_version": __version__,
        "contract_version": contract_manifest.get("contract_version"),
        "contract_bundle": {
            "path": "contract",
            "manifest_path": "contract/contract_manifest.json",
            "manifest_sha256": _sha256_file(bundled_contract_dir / "contract_manifest.json"),
        },
        "runtime_images": runtime_images,
        "capability_images": capability_images,
        "golden_paths": {
            "local_listener_container": {
                "supported": True,
                "execution_mode": "local_container",
                "runner_image": listener_image["image_ref"] if listener_image else None,
                "image_archive_path": listener_image.get("archive_path") if listener_image else None,
                "requires_repo_checkout": False,
                "notes": "Recommended setup path for paired local execution.",
            },
            "apple_silicon_local_native": {
                "supported": True,
                "execution_mode": "local_native",
                "runner_package_version": __version__,
                "requires_repo_checkout": False,
                "notes": "Explicit native deviation for Metal-backed Apple Silicon benchmarking.",
            },
        },
        "development_defaults": {
            "local_runner_image": "infergrade-runner-core:local",
            "local_backend_images": {
                "llama.cpp": "infergrade-llama-cpp:local",
            },
            "mode_label": "development_snapshot",
        },
        "artifacts": contract_files + image_files,
    }
    (release_dir / "release_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return release_dir


def load_release_manifest(bundle_dir: Optional[Path] = None, root: Optional[Path] = None, release_version: Optional[str] = None) -> Dict[str, Any]:
    """Load an exported release manifest from disk."""
    if bundle_dir is not None:
        manifest_path = Path(bundle_dir) / "release_manifest.json"
    else:
        base = Path(root) if root is not None else repo_root()
        manifest_path = (base / "dist" / "releases" / str(release_version or default_release_version()) / "release_manifest.json")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _copy_release_archives(source_dir: Path, destination_dir: Path) -> Dict[str, str]:
    """Copy exported image archives into the release bundle when present."""
    copied: Dict[str, str] = {}
    if not source_dir.exists():
        return copied
    destination_dir.mkdir(parents=True, exist_ok=True)
    for source in sorted(source_dir.glob("*.tar")):
        destination = destination_dir / source.name
        shutil.copy2(source, destination)
        copied[source.name] = _sha256_file(destination)
    return copied


def _artifact_entries(source_dir: Path, release_dir: Path, artifact_kind: str) -> List[Dict[str, Any]]:
    """Return checksummed artifact metadata for files under one release subtree."""
    entries: List[Dict[str, Any]] = []
    if not source_dir.exists():
        return entries
    for path in sorted(item for item in source_dir.rglob("*") if item.is_file()):
        entries.append(
            {
                "kind": artifact_kind,
                "path": str(path.relative_to(release_dir)),
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return entries


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
