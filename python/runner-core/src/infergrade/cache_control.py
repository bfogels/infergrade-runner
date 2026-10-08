"""Explicit cache ownership, Keep preferences, and crash-safe process leases."""

import contextlib
import functools
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import time

CONTROL = ".infergrade-cache-control"
MAX_METADATA_BYTES = 2 * 1024 * 1024


def default_root():
    return Path.home() / ".cache" / "infergrade" / "artifacts"


def _control(root):
    root = Path(root).expanduser().absolute()
    if root.is_symlink():
        raise RuntimeError("Cache control refuses a linked cache directory.")
    root.mkdir(parents=True, exist_ok=True)
    directory = root / CONTROL
    if directory.is_symlink():
        raise RuntimeError("Cache control refuses linked metadata.")
    directory.mkdir(mode=0o700, exist_ok=True)
    return root, directory


@contextlib.contextmanager
def process_lock(root, name="cache-lease.lock", shared=True, blocking=True):
    from infergrade.process_locks import file_lock

    root, directory = _control(root)
    with file_lock(directory / name, shared=shared, blocking=blocking,
                   busy_message="Cache is in use. Stop listening and finish active work before clearing space."):
        yield root


def _roots(request=None):
    roots = {str(default_root())}
    for value in [
        getattr(request, "quant_artifact_cache_dir", None),
        os.environ.get("INFERGRADE_HOST_ARTIFACT_CACHE_DIR"),
    ]:
        if value:
            roots.add(str(Path(value).expanduser().absolute()))
    for value in [
        getattr(request, "quant_artifact", None),
        getattr(request, "quant_artifact_resolved_path", None),
    ]:
        if value:
            # Defer this import to avoid the artifacts/cache-control import cycle.
            from infergrade.artifacts import (
                _is_local_artifact_reference,
                _normalize_local_path,
            )

            if not _is_local_artifact_reference(str(value)):
                continue
            path = Path(_normalize_local_path(str(value))).expanduser().absolute()
            for parent in {path.parent, path.resolve().parent}:
                if (parent / CONTROL).is_dir():
                    roots.add(str(parent))
    return sorted(roots)


@contextlib.contextmanager
def request_cache_lease(request):
    if getattr(request, "simulate", False):
        yield
        return
    with contextlib.ExitStack() as stack:
        for root in _roots(request):
            stack.enter_context(process_lock(root))
        yield


def cache_read_lease(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        request = kwargs.get("request") or (
            args[0] if args and hasattr(args[0], "quant_artifact") else None
        )
        if getattr(request, "simulate", False) or kwargs.get("simulate", False):
            return function(*args, **kwargs)
        with request_cache_lease(request):
            return function(*args, **kwargs)

    return wrapped


def _read_metadata(root):
    path = root / CONTROL / "managed.json"
    if not path.exists():
        return {}
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > MAX_METADATA_BYTES
    ):
        raise RuntimeError("Cache metadata is invalid; no files were removed.")
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or len(value) > 10000:
        raise RuntimeError("Cache metadata is invalid; no files were removed.")
    return value


def _save_metadata(root, value):
    raw = json.dumps(value, sort_keys=True).encode()
    if len(raw) > MAX_METADATA_BYTES:
        raise RuntimeError("Cache metadata exceeds its limit.")
    fd, name = tempfile.mkstemp(
        prefix="managed-", suffix=".tmp", dir=str(root / CONTROL)
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, str(root / CONTROL / "managed.json"))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _identity(path):
    data = path.lstat()
    if not stat.S_ISREG(data.st_mode) or path.is_symlink():
        raise RuntimeError("Only regular managed cache files can be changed.")
    return [data.st_dev, data.st_ino, data.st_size, data.st_mtime_ns, data.st_ctime_ns]


def _valid_name(name):
    return (
        isinstance(name, str)
        and 0 < len(name) <= 240
        and name not in {".", ".."}
        and "/" not in name
        and "\\" not in name
        and "\x00" not in name
    )


def record_install(cache_dir, path, sha256):
    """Called only after a new verified file is installed without overwrite."""
    root, _ = _control(cache_dir)
    path = Path(path).absolute()
    if (
        path.parent != root
        or not _valid_name(path.name)
        or not re.fullmatch("[a-f0-9]{64}", sha256)
    ):
        raise RuntimeError("Invalid managed cache installation.")
    with process_lock(root, "metadata.lock", shared=False):
        values = _read_metadata(root)
        identity = _identity(path)
        artifact_id = hashlib.sha256((path.name + "\0" + sha256).encode()).hexdigest()
        values[artifact_id] = {
            "name": path.name,
            "sha256": sha256,
            "identity": identity,
            "keep": False,
            "installed_at": time.time(),
            "last_used_at": time.time(),
        }
        _save_metadata(root, values)
    return artifact_id


def touch_managed(cache_dir, path):
    root, _ = _control(cache_dir)
    with process_lock(root, "metadata.lock", shared=False):
        values = _read_metadata(root)
        for row in values.values():
            if (
                isinstance(row, dict)
                and row.get("name") == Path(path).name
                and row.get("identity") == _identity(Path(path))
            ):
                row["last_used_at"] = time.time()
        _save_metadata(root, values)


def managed_status(cache_dir=None):
    root = Path(cache_dir or default_root()).expanduser().absolute()
    with process_lock(root), process_lock(root, "metadata.lock", shared=False):
        values = _read_metadata(root)
        artifacts = []
        for path in sorted(root.iterdir()):
            if (
                path.is_symlink()
                or not path.is_file()
                or path.suffix in {".tmp", ".download"}
            ):
                continue
            identity = _identity(path)
            match = next(
                (
                    (key, row)
                    for key, row in values.items()
                    if isinstance(row, dict)
                    and row.get("name") == path.name
                    and row.get("identity") == identity
                ),
                None,
            )
            artifacts.append(
                {
                    "name": path.name,
                    "size_bytes": identity[2],
                    "managed": bool(match),
                    "artifact_id": match[0] if match else None,
                    "keep": bool(match and match[1].get("keep")),
                    "last_used_at": match[1].get("last_used_at") if match else None,
                }
            )
        return {
            "cache_dir": str(root),
            "artifact_count": len(artifacts),
            "artifact_bytes": sum(row["size_bytes"] for row in artifacts),
            "artifacts": artifacts,
        }


def set_keep(artifact_id, keep, cache_dir=None):
    if not re.fullmatch("[a-f0-9]{64}", str(artifact_id)) or not isinstance(keep, bool):
        raise ValueError("Choose a managed artifact and a Keep preference.")
    with process_lock(cache_dir or default_root()) as root, process_lock(
        root, "metadata.lock", shared=False
    ):
        values = _read_metadata(root)
        row = values.get(artifact_id)
        if (
            not isinstance(row, dict)
            or not _valid_name(row.get("name"))
            or _identity(root / row["name"]) != row.get("identity")
        ):
            raise RuntimeError("Managed artifact is unavailable.")
        row["keep"] = keep
        _save_metadata(root, values)
    return managed_status(root)


def clear_unkept(cache_dir=None, artifact_id=None, dry_run=False):
    if artifact_id is not None and not re.fullmatch("[a-f0-9]{64}", str(artifact_id)):
        raise ValueError("Invalid managed artifact.")
    removed = []
    with process_lock(
        cache_dir or default_root(), shared=False, blocking=False
    ) as root, process_lock(root, "metadata.lock", shared=False):
        values = _read_metadata(root)
        for key, row in list(values.items()):
            if artifact_id is not None and key != artifact_id:
                continue
            if (
                not isinstance(row, dict)
                or row.get("keep") is not False
                or not _valid_name(row.get("name"))
            ):
                continue
            path = root / row["name"]
            try:
                if _identity(path) != row.get("identity"):
                    continue
            except (OSError, RuntimeError):
                continue
            if not dry_run:
                path.unlink()
                del values[key]
            removed.append(
                {
                    "artifact_id": key,
                    "name": row["name"],
                    "size_bytes": row["identity"][2],
                }
            )
        if not dry_run:
            _save_metadata(root, values)
    return {
        "removed_count": len(removed),
        "removed_bytes": sum(row["size_bytes"] for row in removed),
        "removed": removed,
        "dry_run": dry_run,
        "status": managed_status(root),
    }


def download_starter():
    from infergrade.artifacts import resolve_quant_artifact
    from infergrade.models import RunRequest

    uri = "hf://TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
    request = RunRequest(
        model="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
        backend="llama.cpp",
        tier="canary",
        simulate=False,
        quant_artifact=uri,
        quant_artifact_revision="52e7645ba7c309695bec7ac98f4f005b139cf465",
        quant_artifact_filename="tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        quant_artifact_download_size_bytes=668788096,
        quant_artifact_sha256="9fecc3b3cd76bba89d504f29b616eedf7da85b96540e490ca5824d3f7d2776a0",
    )
    artifact = resolve_quant_artifact(request)
    return {
        "status": "already_present" if artifact.cache_hit else "downloaded",
        "path": artifact.resolved_path,
        "url": artifact.download_url,
        "size_bytes": artifact.size_bytes,
    }
