"""Local-file benchmarks through the canonical scorer, without Hub publication."""

import contextlib
import hashlib
import json
import os
import stat
import tempfile
import uuid
from pathlib import Path

from infergrade.benchmark_catalog import normalize_request_selection
from infergrade.cache_control import request_cache_lease
from infergrade.gguf import read_gguf_architecture_stream
from infergrade.models import RunRequest
from infergrade.pairing import runner_config_dir
from infergrade.runner import run_infergrade
from infergrade.utils import utcnow_iso

SCHEMA = "infergrade.private_benchmark.v1"
# These are existing Runner checks. Coding and reasoning remain partial surfaces;
# the canonical scorer owns score readiness and missing weighted coverage.
CHECKS = {
    "general_assistant": ["ifeval", "assistant_compositional_instruction_v2", "multiturn_chat_memory_v1"],
    "agentic_coding": ["coding_static_repair_v1"],
    "reasoning": ["reasoning_exact_answer_v1"],
}


def _regular_file(value, executable=False):
    path = Path(value).expanduser().resolve(strict=True)
    fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("Select a regular local file.")
        if executable and os.name != "nt" and not os.access(str(path), os.X_OK):
            raise ValueError("Select an executable llama.cpp binary.")
    finally:
        os.close(fd)
    return path


def _model_identity(path):
    fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size < 24:
            raise ValueError("Select a local GGUF model file.")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            if handle.read(4) != b"GGUF":
                raise ValueError("Select a local GGUF model file.")
            handle.seek(0)
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
            handle.seek(0)
            architecture = read_gguf_architecture_stream(handle)
        after = os.fstat(fd)
        current = path.stat()
        def identity(value):
            return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if identity(before) != identity(after) or identity(after) != identity(current):
            raise ValueError("The model changed during verification. Try again with an unchanged file.")
        return digest.hexdigest(), before.st_size, architecture
    finally:
        os.close(fd)


def _directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or path.is_symlink():
        raise ValueError("Private benchmark storage must be an unlinked directory.")
    if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ValueError("Private benchmark storage must belong to you and be accessible only to you.")
    return path


def _receipt(path, payload):
    fd, temporary = tempfile.mkstemp(prefix=".receipt-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def _private_permissions():
    previous = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(previous)


def _run_private_benchmark(model_file, use_case, tier, cli_path, server_path, emit_progress=None):
    """Run a selected native check inventory and retain its ordinary local bundle."""
    if use_case not in CHECKS or tier not in ("canary", "standard"):
        raise ValueError("Choose an available local use case and canary or standard depth.")
    # No request documents, remote artifact URLs, API credentials or upload flags.
    model = _regular_file(model_file)
    cli = _regular_file(cli_path, executable=True)
    server = _regular_file(server_path, executable=True)
    digest, size, architecture = _model_identity(model)
    identifier = "private_" + uuid.uuid4().hex
    config = Path(runner_config_dir())
    if config.is_symlink():
        raise ValueError("Private benchmark storage refuses linked configuration directories.")
    with _private_permissions():
        root = _directory(config / "private-runs")
        directory = _directory(root / identifier)
        request = RunRequest(
            model="local/sha256-" + digest, backend="llama.cpp", tier=tier,
            tier_was_explicit=True, use_case=use_case, simulate=False, upload=False,
            execution_mode="local_native", quant_artifact=str(model),
            quant_artifact_sha256=digest, quant_artifact_filename=model.name,
            quant_artifact_download_size_bytes=size, llama_cpp_cli_path=str(cli),
            llama_cpp_server_path=str(server),
            benchmark_check_ids=CHECKS[use_case] + ["interactive_chat_v1"],
            deployment_profiles=["interactive_chat_v1"],
            deployment_warmup_runs=1, deployment_measured_runs=3,
            output_dir=str(directory / "bundle"),
            ontology_hints={"architecture": architecture} if architecture else {},
        )
        normalize_request_selection(request)
        receipt = {
            "schema_version": SCHEMA, "id": identifier, "created_at": utcnow_iso(),
            "status": "running", "use_case": use_case, "tier": tier,
            "model_filename": model.name, "artifact_sha256": digest,
            "benchmark_check_ids": list(request.benchmark_check_ids),
            "uploaded": False, "bundle_id": None,
        }
        receipt_path = directory / "receipt.json"
        _receipt(receipt_path, receipt)
        try:
            result = run_infergrade(request, emit_progress=emit_progress)
            if result.get("validation", {}).get("valid") is not True:
                raise RuntimeError("The local result bundle did not pass validation. Inspect its local report.")
            receipt.update(status="completed", bundle_id=result["bundle_id"])
            _receipt(receipt_path, receipt)
            return {**receipt, "output_dir": request.output_dir, "report_path": result["report_path"], "receipt_path": str(receipt_path)}
        except BaseException:
            receipt["status"] = "failed"
            _receipt(receipt_path, receipt)
            raise


def run_private_benchmark(model_file, use_case, tier, cli_path, server_path, emit_progress=None):
    """Keep managed files leased across verification and canonical execution."""
    lease_request = RunRequest(
        model="local/unverified", backend="llama.cpp", tier="canary", simulate=False,
        quant_artifact=str(Path(model_file).expanduser().absolute()),
    )
    with request_cache_lease(lease_request):
        return _run_private_benchmark(model_file, use_case, tier, cli_path, server_path, emit_progress)


def _bounded_json(path, limit):
    fd = os.open(str(path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        if path.is_symlink() or not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('Not a regular private result file.')
        with os.fdopen(fd, 'rb', closefd=False) as handle:
            data = handle.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Private result exceeds the reader bound.')
        return json.loads(data)
    finally:
        os.close(fd)


def private_benchmark_history():
    """Read closed metadata from bounded, locally owned result directories."""
    import re
    root = Path(runner_config_dir()) / 'private-runs'
    if root.parent.is_symlink() or root.is_symlink():
        raise ValueError('Private benchmark storage refuses linked directories.')
    if not root.exists():
        return {'schema_version': 'infergrade.private_history.v1', 'results': [], 'truncated': False, 'unreadable_count': 0}
    _directory(root)
    entries = []
    truncated = False
    with os.scandir(root) as scan:
        inspected = 0
        for entry in scan:
            inspected += 1
            if inspected > 10000:
                truncated = True
                break
            if re.fullmatch(r'private_[0-9a-f]{32}', entry.name) and entry.is_dir(follow_symlinks=False):
                entries.append(entry.name)
    rows, unreadable = [], 0
    # Receipt timestamps provide ordering after a bounded scan; no paths from
    # mutable receipt content are ever followed.
    for identifier in entries:
        directory = root / identifier
        try:
            _directory(directory)
            value = _bounded_json(directory / 'receipt.json', 16384)
            expected = {'schema_version', 'id', 'created_at', 'status', 'use_case', 'tier', 'model_filename', 'artifact_sha256', 'benchmark_check_ids', 'uploaded', 'bundle_id'}
            if not isinstance(value, dict) or set(value) != expected or value['schema_version'] != SCHEMA or value['id'] != identifier or value['uploaded'] is not False:
                raise ValueError('Invalid private receipt.')
            if value['status'] not in ('running', 'completed', 'failed') or value['use_case'] not in CHECKS or value['tier'] not in ('canary', 'standard'):
                raise ValueError('Invalid private state.')
            if value['benchmark_check_ids'] != CHECKS[value['use_case']] + ['interactive_chat_v1'] or not re.fullmatch(r'[0-9a-f]{64}', value['artifact_sha256']):
                raise ValueError('Invalid private check inventory.')
            if not isinstance(value['model_filename'], str) or not 1 <= len(value['model_filename']) <= 4096 or not isinstance(value['created_at'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', value['created_at']):
                raise ValueError('Invalid private display metadata.')
            bundle = directory / 'bundle'
            if bundle.is_symlink() or (bundle / 'results').is_symlink():
                raise ValueError('Linked private bundle.')
            report = bundle / 'report.md'
            report_available = report.is_file() and not report.is_symlink()
            row = {key: value[key] for key in ('id', 'created_at', 'status', 'use_case', 'tier', 'model_filename', 'artifact_sha256')}
            row.update(report_available=report_available, report_path=str(report) if report_available else None, capability_status=None, score=None, component_scores={})
            row['_bundle_id'] = value['bundle_id']
            rows.append(row)
        except (OSError, ValueError, TypeError, AttributeError, RecursionError):
            unreadable += 1
    rows.sort(key=lambda row: (row['created_at'], row['id']), reverse=True)
    latest = []
    for row in rows[:50]:
        bundle_id = row.pop('_bundle_id')
        try:
            if row['status'] == 'completed':
                _history_capability(row, root / row['id'] / 'bundle', bundle_id)
            latest.append(row)
        except (OSError, ValueError, TypeError, AttributeError, RecursionError):
            unreadable += 1
    return {'schema_version': 'infergrade.private_history.v1', 'results': latest, 'truncated': truncated or len(rows) > 50, 'unreadable_count': unreadable}


def _history_capability(row, bundle, bundle_id):
    import math
    import re
    if not isinstance(bundle_id, str) or not re.fullmatch(r'qb_[0-9]{8}_[0-9]{6}_[0-9a-f]{8}', bundle_id):
        raise ValueError('Invalid private bundle identity.')
    record = _bounded_json(bundle / 'results' / 'interactive_chat_v1.json', 2 * 1024 * 1024)
    if record.get('bundle_id') != bundle_id or record.get('result_id') != bundle_id + '_interactive_chat_v1' or record.get('configuration', {}).get('quant_artifact_sha256') != row['artifact_sha256']:
        raise ValueError('Private result identity mismatch.')
    capability = record.get('capability', {})
    state = capability.get('capability_status')
    if state is not None and state not in ('completed', 'partial', 'failed', 'skipped', 'simulated', 'unavailable'):
        raise ValueError('Invalid capability state.')
    row['capability_status'] = state
    details = capability.get('capability_score_details', {})
    score = capability.get('capability_score')
    if details.get('score_ready') is True and type(score) in (int, float) and math.isfinite(score) and 0 <= score <= 1:
        row['score'] = score
    for name, score in capability.get('capability_component_scores', {}).items():
        if name in CHECKS[row['use_case']] and type(score) in (int, float) and math.isfinite(score) and 0 <= score <= 1:
            row['component_scores'][name] = score
