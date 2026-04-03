"""Runner-owned contract publication helpers."""

import json
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from infergrade import __version__


def repo_root() -> Path:
    """Return the repository root for the Runner workspace."""
    return Path(__file__).resolve().parents[4]


def contract_manifest_path(root: Optional[Path] = None) -> Path:
    """Return the path to the Runner-owned contract manifest."""
    base = Path(root) if root is not None else repo_root()
    return base / "schemas" / "contract_manifest.json"


def load_contract_manifest(root: Optional[Path] = None) -> Dict[str, Any]:
    """Load the contract manifest and normalize its declared version."""
    path = contract_manifest_path(root)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["contract_version"] = str(manifest.get("contract_version") or __version__)
    manifest["publisher"] = str(manifest.get("publisher") or "infergrade-runner")
    return manifest


def export_contract_bundle(output_dir: Optional[Path] = None, root: Optional[Path] = None) -> Path:
    """Export the Runner contract bundle into a versioned directory."""
    base = Path(root) if root is not None else repo_root()
    manifest = load_contract_manifest(base)
    contract_version = manifest["contract_version"]
    destination_root = Path(output_dir) if output_dir is not None else (base / "dist" / "contracts")
    bundle_dir = destination_root / contract_version
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    for relative_path in manifest.get("schema_files", []):
        _copy_relative_path(base, bundle_dir, relative_path)
    for relative_path in manifest.get("example_files", []):
        _copy_relative_path(base, bundle_dir, relative_path)
    for relative_path in manifest.get("catalog_files", []):
        _copy_relative_path(base, bundle_dir, relative_path)
    for relative_path in manifest.get("supporting_docs", []):
        _copy_relative_path(base, bundle_dir, relative_path)

    export_manifest = dict(manifest)
    export_manifest["bundle_root"] = "."
    export_manifest["exported_by"] = "infergrade-runner"
    export_manifest["export_format"] = "contract_bundle_v1"
    (bundle_dir / "contract_manifest.json").write_text(
        json.dumps(export_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return bundle_dir


def _copy_relative_path(base: Path, bundle_dir: Path, relative_path: str) -> None:
    """Copy one repo-relative file into the exported bundle."""
    source = base / relative_path
    if not source.exists():
        raise FileNotFoundError("Contract export source does not exist: %s" % relative_path)
    destination = bundle_dir / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
