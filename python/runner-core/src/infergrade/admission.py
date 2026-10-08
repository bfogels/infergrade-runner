"""Machine-local durable admission control; active jobs are never interrupted."""
import contextlib
import json
import os
from pathlib import Path
import stat
import tempfile

from infergrade.pairing import runner_config_dir
from infergrade.process_locks import file_lock

SCHEMA = "infergrade.admission.v1"


def _directory():
    directory = Path(runner_config_dir())
    if directory.is_symlink():
        raise RuntimeError("Admission control refuses a linked config directory.")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory


def _read(directory):
    path = directory / "admission.json"
    try:
        fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        return {"schema_version": SCHEMA, "paused": False}
    except OSError as exc:
        raise RuntimeError("Admission state is unavailable; new benchmarks are blocked.") from exc
    try:
        if path.is_symlink() or not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("not a regular state file")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(4097)
        if len(data) > 4096:
            raise ValueError("oversized state")
        value = json.loads(data)
        if not isinstance(value, dict) or set(value) != {"schema_version", "paused"} or value["schema_version"] != SCHEMA or type(value["paused"]) is not bool:
            raise ValueError("invalid state")
        return value
    except (ValueError, OSError) as exc:
        raise RuntimeError("Admission state is invalid; new benchmarks are blocked. Explicitly pause or resume to repair it.") from exc
    finally:
        os.close(fd)


@contextlib.contextmanager
def claim_admission():
    directory = _directory()
    with file_lock(directory / "admission.lock"):
        yield not _read(directory)["paused"]


def admission_status():
    directory = _directory()
    with file_lock(directory / "admission.lock"):
        return _read(directory)


def set_admission_paused(paused):
    if type(paused) is not bool:
        raise ValueError("paused must be a boolean")
    directory = _directory()
    with file_lock(directory / "admission.lock"):
        path = directory / "admission.json"
        if path.is_symlink():
            raise RuntimeError("Admission control refuses linked state.")
        value = {"schema_version": SCHEMA, "paused": paused}
        fd, temporary = tempfile.mkstemp(prefix=".admission-", dir=str(directory))
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(value, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            if os.name != "nt":
                directory_fd = os.open(str(directory), os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return value


def admission_heartbeat_metadata(metadata=None):
    """Best-effort atomic snapshot; never wait for admission or fail active work."""
    result = dict(metadata or {})
    try:
        directory = Path(runner_config_dir())
        if directory.is_symlink():
            raise RuntimeError("linked config")
        result["admission_paused"] = _read(directory)["paused"]
    except (RuntimeError, OSError, ValueError):
        result["admission_paused"] = None
    if result["admission_paused"] is None:
        result["admission_warning"] = "Admission preference is unavailable; new claims require repair."
    else:
        result.pop("admission_warning", None)
    return result
