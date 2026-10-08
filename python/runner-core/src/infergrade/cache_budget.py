"""Owned-download budgets; never upgrade an execution's shared cache lease."""
import contextlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import tempfile

from infergrade.cache_control import (
    CONTROL, _control, _identity, _read_metadata, _save_metadata, _valid_name,
    managed_status, process_lock,
)

GIB = 1024 ** 3
LIMITS = (25, 50, 100, 200)
SCHEMA = 'infergrade.cache_budget.v1'


def _read(root, name):
    path = root / CONTROL / name
    if path.is_symlink():
        raise RuntimeError('Download budget refuses linked metadata.')
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        info = os.fstat(fd)
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
            raise ValueError('Invalid metadata file.')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(4097)
        if len(data) > 4096:
            raise ValueError('Metadata exceeds the byte limit.')
        value = json.loads(data)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, RecursionError):
        raise RuntimeError('Invalid download budget metadata.') from None
    finally:
        if fd is not None:
            os.close(fd)
    if not isinstance(value, dict):
        raise RuntimeError('Invalid download budget metadata.')
    return value


def _write(root, name, value):
    path = root / CONTROL / name
    if path.is_symlink():
        raise RuntimeError('Download budget refuses linked metadata.')
    fd, temporary = tempfile.mkstemp(prefix='budget-', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(json.dumps(value, sort_keys=True).encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != 'nt':
            parent = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _limit(root):
    value = _read(root, 'budget.json')
    if value is None:
        return None
    if (set(value) != {'schema_version', 'limit_gb'} or value['schema_version'] != SCHEMA
            or (value['limit_gb'] is not None and (type(value['limit_gb']) is not int or value['limit_gb'] not in LIMITS))):
        raise RuntimeError('Invalid download budget metadata.')
    return value['limit_gb']


def _owned(root, values):
    owned = []
    for key, row in values.items():
        if not isinstance(row, dict) or not _valid_name(row.get('name')):
            continue
        try:
            identity = _identity(root / row['name'])
        except (OSError, RuntimeError):
            continue
        if identity == row.get('identity'):
            owned.append((key, row, identity[2]))
    return owned


def budget_status(cache_dir=None):
    root, _ = _control(cache_dir or Path.home() / '.cache/infergrade/artifacts')
    active = False
    try:
        with process_lock(root, 'producer.lock', shared=True, blocking=False):
            pass
    except RuntimeError as exc:
        # Linked/invalid locks are errors, not an active producer.
        if str(exc) != 'Cache is in use. Stop listening and finish active work before clearing space.':
            raise
        active = True
    with process_lock(root), process_lock(root, 'metadata.lock', shared=False):
        limit = _limit(root)
        owned = _owned(root, _read_metadata(root))
        reservation = _read(root, 'reservation.json') if active else None
        reserved = 0
        if reservation is not None:
            if (set(reservation) != {'schema_version', 'bytes'} or reservation['schema_version'] != SCHEMA
                    or type(reservation['bytes']) is not int or reservation['bytes'] < 0):
                raise RuntimeError('Invalid download reservation.')
            reserved = reservation['bytes']
        disk = shutil.disk_usage(root)
        return {'schema_version': SCHEMA, 'limit_gb': limit,
                'limit_bytes': limit * GIB if limit is not None else None,
                'managed_bytes': sum(size for _, _, size in owned),
                'kept_bytes': sum(size for _, row, size in owned if row.get('keep') is not False),
                'reserved_bytes': reserved, 'producer_active': active,
                'disk_free_bytes': disk.free, 'disk_total_bytes': disk.total}


def set_limit(limit_gb, cache_dir=None, trim=False):
    if limit_gb is not None and (type(limit_gb) is not int or limit_gb not in LIMITS):
        raise ValueError('Choose 25, 50, 100, 200 GB or no limit.')
    removed = []
    # Trimming requires exclusive cleanup authority; do not upgrade a reader.
    with process_lock(cache_dir or Path.home() / '.cache/infergrade/artifacts', shared=not trim, blocking=False) as root:
        with process_lock(root, 'producer.lock', shared=False, blocking=False), process_lock(root, 'metadata.lock', shared=False):
            values = _read_metadata(root)
            _limit(root)  # A malformed persisted policy cannot silently become no limit.
            owned = _owned(root, values)
            required = max(0, sum(size for _, _, size in owned) - limit_gb * GIB) if limit_gb is not None else 0
            candidates = [(key, row, size) for key, row, size in owned
                          if row.get('keep') is False and isinstance(row.get('installed_at'), (int, float))
                          and not isinstance(row['installed_at'], bool) and math.isfinite(row['installed_at'])]
            candidates.sort(key=lambda item: (item[1]['installed_at'], item[1]['name'], item[0]))
            if required and (not trim or sum(size for _, _, size in candidates) < required):
                raise RuntimeError('Clear enough unkept downloads before lowering the limit; kept files are preserved.')
            for key, row, size in candidates:
                if required <= 0:
                    break
                path = root / row['name']
                if _identity(path) != row['identity']:
                    raise RuntimeError('Cache ownership changed; the limit was not updated.')
                path.unlink()
                del values[key]
                removed.append({'artifact_id': key, 'name': row['name'], 'size_bytes': size})
                required -= size
            if removed:
                _save_metadata(root, values)
            _write(root, 'budget.json', {'schema_version': SCHEMA, 'limit_gb': limit_gb})
    return {'budget': budget_status(root), 'removed': removed, 'status': managed_status(root)}


@contextlib.contextmanager
def download_budget(cache_dir, expected_bytes, cache_paths=()):
    """Serialize producers, reserve authorized bytes, and preserve cache winners."""
    with process_lock(cache_dir) as root, process_lock(root, 'producer.lock', shared=False):
        # Recheck after waiting: the preceding producer may have installed this file.
        if any(path and Path(path).absolute().parent != root for path in cache_paths):
            raise RuntimeError('Invalid cache producer destination.')
        winner = next((Path(path) for path in cache_paths if path and Path(path).is_file() and not Path(path).is_symlink()), None)
        if winner is not None:
            yield str(winner)
            return
        with process_lock(root, 'metadata.lock', shared=False):
            limit = _limit(root)
            owned_bytes = sum(size for _, _, size in _owned(root, _read_metadata(root)))
            if limit is not None:
                if type(expected_bytes) is not int or expected_bytes <= 0:
                    raise RuntimeError('A download limit requires a verified artifact byte size before downloading.')
                if owned_bytes + expected_bytes > limit * GIB:
                    raise RuntimeError('Download limit reached. Finish active work and clear unkept downloads before trying again.')
            _write(root, 'reservation.json', {'schema_version': SCHEMA, 'bytes': expected_bytes or 0})
        try:
            yield None
        finally:
            with process_lock(root, 'metadata.lock', shared=False):
                _write(root, 'reservation.json', {'schema_version': SCHEMA, 'bytes': 0})
