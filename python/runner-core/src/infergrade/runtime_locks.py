"""Resolve one immutable native runtime binding for an InferGrade run attempt.

The selected runtime record is a user preference.  It must never remain the
execution authority after a run starts: this module resolves that preference
to exact binaries, fingerprints the execution tree, and persists a private
lock outside the upload bundle so resume cannot silently switch runtimes.
"""

import hashlib
import json
import os
import platform
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from infergrade.runtimes import llama_cpp_runtime_dir, selected_llama_cpp_runtime
from infergrade.utils import utcnow_iso


RUNTIME_BUILD_IDENTITY_VERSION = "infergrade_runtime_build_v1"
RUNTIME_LOCK_VERSION = "infergrade_runtime_lock_v1"
RUNTIME_RECEIPT_VERSION = "infergrade_runtime_receipt_v1"
_ROLE_DEFAULTS = {
    "cli": "llama-cli",
    "server": "llama-server",
    "perplexity": "llama-perplexity",
}
_ROLE_REQUEST_FIELDS = {
    "cli": "llama_cpp_cli_path",
    "server": "llama_cpp_server_path",
    "perplexity": "llama_cpp_perplexity_path",
}
_ROLE_ENV = {
    "cli": "INFERGRADE_LLAMA_CPP_CLI",
    "server": "INFERGRADE_LLAMA_CPP_SERVER",
    "perplexity": "INFERGRADE_LLAMA_CPP_PERPLEXITY",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix("%s.tmp-%s" % (path.suffix, os.getpid()))
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(str(temporary), 0o600)
    os.replace(str(temporary), str(path))


def _lock_path(lock_id: str) -> Path:
    return llama_cpp_runtime_dir() / "locks" / (lock_id + ".json")


def _resolve_file(candidate: Optional[str]) -> Optional[Path]:
    if not candidate:
        return None
    resolved = shutil.which(candidate)
    if not resolved:
        return None
    path = Path(resolved).expanduser().resolve()
    return path if path.is_file() else None


def _sibling(cli: Optional[Path], role: str) -> Optional[Path]:
    if not cli:
        return None
    suffix = ".exe" if cli.suffix.lower() == ".exe" else ""
    return _resolve_file(str(cli.parent / (_ROLE_DEFAULTS[role] + suffix)))


def _resolve_role_paths(request: Any) -> Tuple[Dict[str, Path], Dict[str, Any]]:
    selected = selected_llama_cpp_runtime() or {}
    selected_binaries = selected.get("binaries") if isinstance(selected.get("binaries"), dict) else {}
    explicit = {
        role: getattr(request, field, None)
        for role, field in _ROLE_REQUEST_FIELDS.items()
    }
    environment = {role: os.environ.get(name) for role, name in _ROLE_ENV.items()}

    if any(explicit.values()):
        source = "operator_paths"
        preferred = explicit
    elif any(environment.values()):
        source = "environment_paths"
        preferred = environment
    elif selected_binaries:
        source = str(selected.get("source") or "selected_preference")
        preferred = {role: selected_binaries.get(role) for role in _ROLE_DEFAULTS}
    else:
        source = "system_path"
        preferred = dict(_ROLE_DEFAULTS)

    cli = _resolve_file(preferred.get("cli"))
    if not cli:
        raise RuntimeError(
            "Cannot lock llama.cpp runtime: llama-cli is unavailable for the selected runtime preference."
        )
    paths: Dict[str, Path] = {"cli": cli}
    for role in ("server", "perplexity"):
        resolved = _resolve_file(preferred.get(role))
        if resolved is None and source in ("operator_paths", "environment_paths", "system_path"):
            resolved = _sibling(cli, role) or _resolve_file(_ROLE_DEFAULTS[role])
        if resolved is not None:
            paths[role] = resolved
    if "server" not in paths:
        raise RuntimeError(
            "Cannot lock llama.cpp runtime: llama-server is unavailable. The CLI and server must be resolved before execution."
        )
    return paths, {
        "origin": source,
        "runtime_id": selected.get("runtime_id") if source not in ("operator_paths", "environment_paths", "system_path") else None,
        "channel": selected.get("channel"),
        "provenance": selected.get("provenance"),
        "archive_sha256": (selected.get("archive") or {}).get("sha256") if isinstance(selected.get("archive"), dict) else None,
        "independent_signature_verified": bool(
            (selected.get("archive") or {}).get("independent_signature_verified")
        ) if isinstance(selected.get("archive"), dict) else False,
        "managed_runtime_build": selected.get("runtime_build") if isinstance(selected.get("runtime_build"), dict) else None,
    }


def _mode(path: Path) -> int:
    if os.name == "nt":
        return 0
    return int(path.stat().st_mode & 0o777)


def _role_records(paths: Dict[str, Path]) -> List[Dict[str, Any]]:
    records = []
    for role, path in sorted(paths.items()):
        stat_result = path.stat()
        records.append(
            {
                "relative_path": "roles/%s/%s" % (role, path.name),
                "kind": "regular",
                "mode": _mode(path),
                "size_bytes": int(stat_result.st_size),
                "sha256": _sha256_file(path),
                "roles": [role],
                "source_path": str(path),
            }
        )
    return records


def _package_root(paths: Dict[str, Path], selection_metadata: Dict[str, Any]) -> Optional[Path]:
    build = selection_metadata.get("managed_runtime_build") or {}
    configured = build.get("package_root")
    if configured:
        root = Path(configured).expanduser().resolve()
        if root.is_dir() and all(path == root or root in path.parents for path in paths.values()):
            return root
    if selection_metadata.get("origin") != "managed_download":
        return None
    common = Path(os.path.commonpath([str(path.parent) for path in paths.values()])).resolve()
    return common if common.is_dir() else None


def _package_records(root: Path, role_paths: Dict[str, Path]) -> List[Dict[str, Any]]:
    canonical_root = root.resolve()
    roles_by_path: Dict[Path, List[str]] = {}
    for role, path in role_paths.items():
        roles_by_path.setdefault(path.resolve(), []).append(role)
    records = []
    package_paths = sorted(root.rglob("*"), key=lambda item: item.as_posix())
    for path in package_paths:
        if path.is_symlink() and (not path.exists() or path.is_dir()):
            raise RuntimeError(
                "Cannot lock llama.cpp runtime: managed packages may not contain broken or directory symlinks."
            )
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved != canonical_root and canonical_root not in resolved.parents:
            raise RuntimeError(
                "Cannot lock llama.cpp runtime: managed package contains a file outside its immutable root."
            )
        stat_result = resolved.stat()
        records.append(
            {
                "relative_path": path.relative_to(root).as_posix(),
                "kind": "regular",
                "mode": _mode(resolved),
                "size_bytes": int(stat_result.st_size),
                "sha256": _sha256_file(resolved),
                "roles": sorted(roles_by_path.get(resolved, [])),
                "source_path": str(resolved),
            }
        )
    if not records:
        raise RuntimeError("Cannot lock llama.cpp runtime: the managed runtime package is empty.")
    present_roles = {role for item in records for role in item["roles"]}
    missing_roles = sorted(set(role_paths) - present_roles)
    if missing_roles:
        raise RuntimeError(
            "Cannot lock llama.cpp runtime: managed package manifest omitted role(s): %s"
            % ", ".join(missing_roles)
        )
    return records


def _identity_files(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {key: item[key] for key in ("relative_path", "kind", "mode", "size_bytes", "sha256", "roles")}
        for item in records
    ]


def _normalized_platform_arch() -> str:
    arch = (platform.machine() or "unknown").lower()
    return {
        "arm64": "aarch64",
        "amd64": "x86_64",
        "x64": "x86_64",
        "i386": "x86",
        "i686": "x86",
    }.get(arch, arch)


def _build_identity(records: List[Dict[str, Any]], content_scope: str) -> Dict[str, Any]:
    system = platform.system().lower() or "unknown"
    if system == "darwin":
        system = "macos"
    return {
        "identity_version": RUNTIME_BUILD_IDENTITY_VERSION,
        "runtime_family": "llama.cpp",
        "runtime_interface": "llama_cpp_cli_server_v1",
        "platform": {
            "system": system,
            "arch": _normalized_platform_arch(),
        },
        "content_scope": content_scope,
        "files": _identity_files(records),
    }


def _public_lock_summary(lock: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "lock_version": lock["lock_version"],
        "runtime_lock_id": lock["runtime_lock_id"],
        "runtime_build_id": lock["runtime_build_id"],
        "runtime_family": lock["runtime_family"],
        "runtime_interface": lock["runtime_interface"],
        "content_scope": lock["content_scope"],
        "origin": lock["origin"],
        "maturity": lock.get("maturity"),
        "provenance_strength": lock["provenance_strength"],
        "file_count": len(lock["files"]),
        "locked_roles": sorted(lock["resolved_paths"]),
        "created_at": lock["created_at"],
    }


def _verify_lock(lock: Dict[str, Any]) -> None:
    for item in lock.get("files") or []:
        path = Path(item["source_path"])
        if not path.is_file():
            raise RuntimeError(
                "Locked llama.cpp runtime changed before execution: missing %s. Start a new run attempt after selecting a valid runtime."
                % item["relative_path"]
            )
        if int(path.stat().st_size) != int(item["size_bytes"]) or _sha256_file(path) != item["sha256"]:
            raise RuntimeError(
                "Locked llama.cpp runtime changed before execution: digest mismatch for %s. Start a new run attempt; InferGrade will not substitute another runtime."
                % item["relative_path"]
            )
    identity = _build_identity(lock["files"], lock["content_scope"])
    if _canonical_sha256(identity) != lock["runtime_build_id"]:
        raise RuntimeError("Locked llama.cpp runtime identity no longer matches its execution tree.")


def resolve_runtime_lock(
    request: Any,
    bundle_id: str,
    existing_summary: Optional[Dict[str, Any]] = None,
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Resolve or restore a path-private lock and return it plus its public summary."""
    if request.simulate or request.backend != "llama.cpp" or request.execution_mode != "local_native":
        return None
    if existing_summary:
        lock_id = str(existing_summary.get("runtime_lock_id") or "")
        if not lock_id:
            raise RuntimeError("Cannot resume: progress has an incomplete runtime lock summary.")
        path = _lock_path(lock_id)
        if not path.is_file():
            raise RuntimeError(
                "Cannot resume: the exact local runtime lock is missing. Start a new run attempt; InferGrade will not silently select the current runtime."
            )
        with path.open("r", encoding="utf-8") as handle:
            lock = json.load(handle)
        try:
            if lock.get("runtime_lock_id") != lock_id or lock.get("runtime_build_id") != existing_summary.get("runtime_build_id"):
                raise RuntimeError("Cannot resume: the stored runtime lock does not match progress.json.")
            _verify_lock(lock)
        except Exception:
            lock["status"] = "failed"
            lock["updated_at"] = utcnow_iso()
            _atomic_write_json(path, lock)
            raise
    else:
        paths, selection_metadata = _resolve_role_paths(request)
        root = _package_root(paths, selection_metadata)
        content_scope = "managed_package" if root else "selected_binary_set"
        records = _package_records(root, paths) if root else _role_records(paths)
        identity = _build_identity(records, content_scope)
        build_id = _canonical_sha256(identity)
        declared_build = selection_metadata.get("managed_runtime_build") or {}
        declared_build_id = declared_build.get("runtime_build_id")
        if declared_build_id and declared_build_id != build_id:
            raise RuntimeError(
                "Cannot lock llama.cpp runtime: the managed package no longer matches its content-addressed build identity."
            )
        lock_id = _canonical_sha256(
            {
                "lock_version": RUNTIME_LOCK_VERSION,
                "bundle_id": bundle_id,
                "runtime_build_id": build_id,
                "resolved_roles": sorted(paths),
            }
        )
        origin = selection_metadata["origin"]
        lock = {
            "lock_version": RUNTIME_LOCK_VERSION,
            "runtime_lock_id": lock_id,
            "bundle_id": bundle_id,
            "runtime_build_id": build_id,
            "runtime_family": "llama.cpp",
            "runtime_interface": "llama_cpp_cli_server_v1",
            "content_scope": content_scope,
            "origin": origin,
            "maturity": selection_metadata.get("channel"),
            "provenance_strength": (
                "independently_signed"
                if selection_metadata.get("independent_signature_verified")
                else "checksum_verified"
                if selection_metadata.get("archive_sha256")
                else "local_fingerprint_only"
            ),
            "provenance": selection_metadata.get("provenance"),
            "runtime_id": selection_metadata.get("runtime_id"),
            "archive_sha256": selection_metadata.get("archive_sha256"),
            "resolved_paths": {role: str(path) for role, path in paths.items()},
            "files": records,
            "created_at": utcnow_iso(),
            "updated_at": utcnow_iso(),
            "status": "active",
            "prelaunch_verification": "passed",
        }
        _verify_lock(lock)
        _atomic_write_json(_lock_path(lock_id), lock)
    for role, field in _ROLE_REQUEST_FIELDS.items():
        setattr(request, field, lock.get("resolved_paths", {}).get(role))
    return lock, _public_lock_summary(lock)


def finalize_runtime_receipt(lock: Dict[str, Any]) -> Dict[str, Any]:
    """Verify the execution tree again and emit a path-free public receipt."""
    _verify_lock(lock)
    lock["status"] = "completed"
    lock["updated_at"] = utcnow_iso()
    lock["postrun_verification"] = "passed"
    _atomic_write_json(_lock_path(lock["runtime_lock_id"]), lock)
    receipt_files = [
        {
            "relative_path": item["relative_path"],
            "kind": item["kind"],
            "mode": item["mode"],
            "size_bytes": item["size_bytes"],
            "sha256": item["sha256"],
            "roles": list(item["roles"]),
        }
        for item in lock["files"]
    ]
    receipt = {
        "receipt_version": RUNTIME_RECEIPT_VERSION,
        "runtime_lock_id": lock["runtime_lock_id"],
        "runtime_build_id": lock["runtime_build_id"],
        "runtime_family": lock["runtime_family"],
        "runtime_interface": lock["runtime_interface"],
        "content_scope": lock["content_scope"],
        "origin": lock["origin"],
        "maturity": lock.get("maturity"),
        "provenance_strength": lock["provenance_strength"],
        "locked_roles": sorted(lock["resolved_paths"]),
        "execution_tree_file_count": len(receipt_files),
        "execution_tree_manifest_sha256": _canonical_sha256(receipt_files),
        "files": receipt_files,
        "verification": {
            "prelaunch": "passed",
            "postrun": "passed",
            "silent_substitution_allowed": False,
        },
    }
    return receipt


def runtime_receipt_summary(receipt: Dict[str, Any]) -> Dict[str, Any]:
    """Return the compact result-record projection of a full execution-tree receipt."""
    payload = {key: receipt.get(key) for key in (
        "receipt_version",
        "runtime_lock_id",
        "runtime_build_id",
        "runtime_family",
        "runtime_interface",
        "content_scope",
        "origin",
        "maturity",
        "provenance_strength",
        "locked_roles",
        "execution_tree_file_count",
        "execution_tree_manifest_sha256",
        "verification",
    )}
    payload["role_files"] = [
        item
        for item in receipt.get("files") or []
        if item.get("roles")
    ]
    return payload


def mark_runtime_lock_failed(lock: Optional[Dict[str, Any]]) -> None:
    if not lock:
        return
    lock["status"] = "failed"
    lock["updated_at"] = utcnow_iso()
    _atomic_write_json(_lock_path(lock["runtime_lock_id"]), lock)
