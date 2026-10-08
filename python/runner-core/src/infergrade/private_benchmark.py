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
