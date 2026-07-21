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
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from infergrade.environment import _detect_cpu_architecture
from infergrade.runtimes import llama_cpp_runtime_dir, selected_llama_cpp_runtime
from infergrade.utils import utcnow_iso


RUNTIME_BUILD_IDENTITY_VERSION = "infergrade_runtime_build_v1"
RUNTIME_LOCK_VERSION = "infergrade_runtime_lock_v1"
RUNTIME_RECEIPT_VERSION = "infergrade_runtime_receipt_v1"
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_MAX_RECEIPT_FILES = 4096
_MAX_RECEIPT_PATH_LENGTH = 512
_MAX_RECEIPT_FILE_SIZE = 2**50
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
        "archive_checksum_verified": bool((selected.get("archive") or {}).get("checksum_verified"))
        if isinstance(selected.get("archive"), dict)
        else False,
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
    roles_by_path: Dict[Path, List[str]] = {}
    for role, path in paths.items():
        roles_by_path.setdefault(path.resolve(), []).append(role)
    candidates = []
    for path, roles in roles_by_path.items():
        stat_result = path.stat()
        candidates.append(
            {
                "kind": "regular",
                "mode": _mode(path),
                "size_bytes": int(stat_result.st_size),
                "sha256": _sha256_file(path),
                "roles": sorted(roles),
                "source_path": str(path),
            }
        )
    candidates.sort(
        key=lambda item: (
            item["sha256"],
            item["size_bytes"],
            item["mode"],
            item["source_path"],
        )
    )
    records = []
    for index, item in enumerate(candidates):
        record = dict(item)
        # Synthetic names keep private/custom executable basenames out of public receipts.
        # Role bindings are assertions on the locked content, not part of build identity.
        record["relative_path"] = "selected/%04d" % (index + 1)
        records.append(record)
    return records


def _package_root(paths: Dict[str, Path], selection_metadata: Dict[str, Any]) -> Optional[Path]:
    """Return a registry-backed managed root, or downgrade an unverifiable selection."""
    build = selection_metadata.get("managed_runtime_build") or {}
    if selection_metadata.get("origin") != "managed_download":
        return None
    build_id = str(build.get("runtime_build_id") or "")
    source_assertion_id = str(build.get("source_assertion_id") or "")
    archive_sha256 = str(selection_metadata.get("archive_sha256") or "")
    if (
        not _SHA256_PATTERN.fullmatch(build_id)
        or not _SHA256_PATTERN.fullmatch(source_assertion_id)
        or not _SHA256_PATTERN.fullmatch(archive_sha256)
        or not selection_metadata.get("archive_checksum_verified")
        or build.get("identity_version") != RUNTIME_BUILD_IDENTITY_VERSION
        or build.get("content_scope") != "managed_package"
    ):
        selection_metadata["origin"] = "managed_download_unverified"
        return None
    expected_root = (llama_cpp_runtime_dir() / "builds").resolve() / build_id
    expected_manifest = (llama_cpp_runtime_dir() / "build-metadata").resolve() / (build_id + ".json")
    expected_assertion = (
        (llama_cpp_runtime_dir() / "source-assertions").resolve()
        / build_id
        / (source_assertion_id + ".json")
    )
    configured_root = Path(str(build.get("package_root") or "")).expanduser().resolve()
    configured_manifest = Path(str(build.get("manifest_path") or "")).expanduser().resolve()
    configured_assertion = Path(str(build.get("source_assertion_path") or "")).expanduser().resolve()
    if (
        configured_root != expected_root
        or configured_manifest != expected_manifest
        or configured_assertion != expected_assertion
        or expected_root.is_symlink()
        or expected_manifest.is_symlink()
        or expected_assertion.is_symlink()
        or not expected_root.is_dir()
        or not expected_manifest.is_file()
        or not expected_assertion.is_file()
    ):
        selection_metadata["origin"] = "managed_download_unverified"
        return None
    if not all(path == expected_root or expected_root in path.parents for path in paths.values()):
        selection_metadata["origin"] = "managed_download_unverified"
        return None
    try:
        with expected_manifest.open("r", encoding="utf-8") as handle:
            registry = json.load(handle)
        with expected_assertion.open("r", encoding="utf-8") as handle:
            assertion = json.load(handle)
    except (OSError, ValueError):
        selection_metadata["origin"] = "managed_download_unverified"
        return None
    if not isinstance(registry, dict) or not isinstance(assertion, dict):
        selection_metadata["origin"] = "managed_download_unverified"
        return None
    identity = registry.get("identity")
    assertion_archive = assertion.get("archive")
    registry_digest = str((assertion_archive or {}).get("sha256") or "")
    registry_runtime_id = assertion.get("runtime_id")
    assertion_maturity = assertion.get("maturity")
    assertion_provenance = assertion.get("provenance")
    catalog_assertion = assertion.get("catalog_assertion")
    base_assertion_keys = {
        "assertion_version",
        "runtime_build_id",
        "runtime_id",
        "origin",
        "maturity",
        "provenance",
        "archive",
    }
    catalog_assertion_valid = catalog_assertion is None or (
        isinstance(catalog_assertion, dict)
        and set(catalog_assertion)
        == {
            "spec_version",
            "targets_version",
            "targets_sha256",
            "target_name",
            "publisher",
        }
        and catalog_assertion.get("spec_version") == "infergrade_runtime_catalog_v1"
        and isinstance(catalog_assertion.get("targets_version"), int)
        and not isinstance(catalog_assertion.get("targets_version"), bool)
        and catalog_assertion.get("targets_version") > 0
        and _SHA256_PATTERN.fullmatch(str(catalog_assertion.get("targets_sha256") or ""))
        and isinstance(catalog_assertion.get("target_name"), str)
        and 0 < len(catalog_assertion.get("target_name")) <= 512
        and isinstance(catalog_assertion.get("publisher"), str)
        and 0 < len(catalog_assertion.get("publisher")) <= 128
    )
    if (
        registry.get("registry_version") != "infergrade_runtime_build_registry_v1"
        or registry.get("runtime_build_id") != build_id
        or set(registry) != {"registry_version", "runtime_build_id", "identity"}
        or not isinstance(identity, dict)
        or _canonical_sha256(identity) != build_id
        or assertion.get("assertion_version") != "infergrade_runtime_source_assertion_v1"
        or set(assertion) not in (base_assertion_keys, base_assertion_keys | {"catalog_assertion"})
        or not catalog_assertion_valid
        or assertion.get("runtime_build_id") != build_id
        or _canonical_sha256(assertion) != source_assertion_id
        or assertion.get("origin") != "managed_download"
        or not isinstance(registry_runtime_id, str)
        or not registry_runtime_id.strip()
        or len(registry_runtime_id) > 128
        or registry_runtime_id != registry_runtime_id.strip()
        or (
            assertion_maturity is not None
            and (
                not isinstance(assertion_maturity, str)
                or assertion_maturity != assertion_maturity.strip()
                or len(assertion_maturity) > 64
            )
        )
        or not isinstance(assertion_provenance, str)
        or len(assertion_provenance) > 1024
        or not isinstance(assertion_archive, dict)
        or set(assertion_archive) != {
            "sha256",
            "checksum_verified",
            "independent_signature_verified",
        }
        or assertion_archive.get("checksum_verified") is not True
        or not isinstance(assertion_archive.get("independent_signature_verified"), bool)
        or registry_digest != archive_sha256
        or not _SHA256_PATTERN.fullmatch(registry_digest)
    ):
        selection_metadata["origin"] = "managed_download_unverified"
        return None
    selection_metadata["archive_sha256"] = registry_digest
    selection_metadata["archive_checksum_verified"] = True
    selection_metadata["independent_signature_verified"] = bool(
        assertion_archive.get("independent_signature_verified")
    )
    selection_metadata["runtime_id"] = registry_runtime_id
    selection_metadata["channel"] = assertion_maturity
    selection_metadata["provenance"] = assertion_provenance
    selection_metadata["source_assertion_id"] = source_assertion_id
    _reject_revoked_catalog_build(catalog_assertion, build_id)
    return expected_root


def _reject_revoked_catalog_build(catalog_assertion: Any, runtime_build_id: str) -> None:
    """Block new locks for an explicitly revoked target; active locks are untouched."""
    if not isinstance(catalog_assertion, dict):
        return
    catalog_root = llama_cpp_runtime_dir() / "catalog"
    active_path = catalog_root / "active.json"
    if not active_path.is_file():
        # Offline operation with no refreshed policy keeps installed bytes usable.
        return
    try:
        active = json.loads(active_path.read_text(encoding="utf-8"))
        generation = str(active.get("generation") or "")
        if not generation or "/" in generation or ".." in generation or "\\" in generation:
            raise ValueError("unsafe active generation")
        targets_path = catalog_root / "generations" / generation / "targets.json"
        targets_bytes = targets_path.read_bytes()
        if hashlib.sha256(targets_bytes).hexdigest() != active.get("targets_sha256"):
            raise ValueError("targets digest mismatch")
        envelope = json.loads(targets_bytes.decode("utf-8"))
        targets_version = int((envelope.get("signed") or {}).get("version") or 0)
        if targets_version < int(catalog_assertion.get("targets_version") or 0):
            raise ValueError("catalog version rollback")
        target_name = catalog_assertion.get("target_name")
        target = ((envelope.get("signed") or {}).get("targets") or {}).get(target_name)
        custom = (target or {}).get("custom") or {}
        if custom.get("runtime_build_id") != runtime_build_id:
            raise ValueError("catalog target build mismatch")
        if custom.get("revoked") is True or custom.get("maturity") == "revoked":
            raise RuntimeError(
                "Cannot start a new run: the signed runtime catalog revoked build %s. "
                "An already-active run keeps its immutable lock; select a reviewed replacement for new work."
                % runtime_build_id
            )
    except RuntimeError:
        raise
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "Cannot validate the active signed runtime policy for a new run: %s. "
            "Refresh the runtime catalog or select a non-catalog rollback build."
            % error
        )


def _assert_records_bounded(records: List[Dict[str, Any]]) -> None:
    if not 1 <= len(records) <= _MAX_RECEIPT_FILES:
        raise RuntimeError(
            "Cannot lock llama.cpp runtime: content manifest must contain between 1 and %d files."
            % _MAX_RECEIPT_FILES
        )
    for item in records:
        relative_path = str(item.get("relative_path") or "")
        if not relative_path or len(relative_path) > _MAX_RECEIPT_PATH_LENGTH:
            raise RuntimeError(
                "Cannot lock llama.cpp runtime: content manifest path exceeds the %d-character receipt limit."
                % _MAX_RECEIPT_PATH_LENGTH
            )
        size_bytes = item.get("size_bytes")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or not 0 <= size_bytes <= _MAX_RECEIPT_FILE_SIZE:
            raise RuntimeError("Cannot lock llama.cpp runtime: content manifest contains an unsupported file size.")


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
        relative_path = path.relative_to(root).as_posix()
        if len(relative_path) > _MAX_RECEIPT_PATH_LENGTH:
            raise RuntimeError(
                "Cannot lock llama.cpp runtime: content manifest path exceeds the %d-character receipt limit."
                % _MAX_RECEIPT_PATH_LENGTH
            )
        if len(records) >= _MAX_RECEIPT_FILES:
            raise RuntimeError(
                "Cannot lock llama.cpp runtime: content manifest exceeds the %d-file receipt limit."
                % _MAX_RECEIPT_FILES
            )
        stat_result = resolved.stat()
        file_roles = [] if path.is_symlink() else sorted(roles_by_path.get(resolved, []))
        records.append(
            {
                "relative_path": relative_path,
                "kind": "regular",
                "mode": _mode(resolved),
                "size_bytes": int(stat_result.st_size),
                "sha256": _sha256_file(resolved),
                "roles": file_roles,
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
    _assert_records_bounded(records)
    return records


def _identity_files(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {key: item[key] for key in ("relative_path", "kind", "mode", "size_bytes", "sha256")}
        for item in records
    ]


def _normalized_platform_arch() -> str:
    # Runtime identity belongs to the host/runtime platform, not the Python
    # process architecture. An Intel Python running through Rosetta reports
    # x86_64 even though it launches the managed Apple Silicon binaries that
    # the native Rust installer correctly registered as aarch64.
    arch = (_detect_cpu_architecture() or "unknown").lower()
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
    return _build_identity_for_platform(
        records,
        content_scope,
        system=system,
        arch=_normalized_platform_arch(),
    )


def _build_identity_for_platform(
    records: List[Dict[str, Any]],
    content_scope: str,
    system: str,
    arch: str,
) -> Dict[str, Any]:
    """Construct the qualified content identity with explicit platform inputs."""
    return {
        "identity_version": RUNTIME_BUILD_IDENTITY_VERSION,
        "runtime_family": "llama.cpp",
        "runtime_interface": "llama_cpp_cli_server_v1",
        "platform": {
            "system": system,
            "arch": arch,
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
        "provenance_evidence": lock["provenance_evidence"],
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
        _assert_records_bounded(records)
        identity = _build_identity(records, content_scope)
        build_id = _canonical_sha256(identity)
        declared_build = selection_metadata.get("managed_runtime_build") or {}
        declared_build_id = declared_build.get("runtime_build_id")
        if root and declared_build_id and declared_build_id != build_id:
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
                if root and selection_metadata.get("independent_signature_verified")
                else "checksum_verified"
                if root and selection_metadata.get("archive_checksum_verified")
                else "local_fingerprint_only"
            ),
            "provenance_evidence": (
                {
                    "kind": "managed_registry",
                    "registry_version": "infergrade_runtime_registry_v1",
                    "runtime_id": selection_metadata["runtime_id"],
                    "source_archive_sha256": selection_metadata["archive_sha256"],
                    "source_assertion_id": selection_metadata["source_assertion_id"],
                }
                if root
                else {"kind": "local_fingerprint"}
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
    if existing_summary:
        # Resuming is a new active execution lease on the same immutable lock.
        lock["status"] = "active"
        lock["updated_at"] = utcnow_iso()
        _atomic_write_json(_lock_path(lock["runtime_lock_id"]), lock)
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
    _assert_records_bounded(receipt_files)
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
        "provenance_evidence": lock["provenance_evidence"],
        "locked_roles": sorted(lock["resolved_paths"]),
        "content_manifest_file_count": len(receipt_files),
        "content_manifest_sha256": _canonical_sha256(receipt_files),
        "role_files": [item for item in receipt_files if item.get("roles")],
        "files": receipt_files,
        "verification": {
            "prelaunch": "passed",
            "postrun": "passed",
            "silent_substitution_allowed": False,
        },
    }
    return receipt


def runtime_receipt_summary(receipt: Dict[str, Any]) -> Dict[str, Any]:
    """Return the compact result-record projection of a path-free content receipt."""
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
        "provenance_evidence",
        "locked_roles",
        "content_manifest_file_count",
        "content_manifest_sha256",
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
