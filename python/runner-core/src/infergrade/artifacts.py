"""Artifact resolution helpers for local, cached, and remote quantized files."""

import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Dict, Optional
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from infergrade.models import RunRequest
from infergrade.utils import ensure_dir, stable_hash


@dataclass
class ResolvedArtifact:
    """Describe the concrete artifact file used for a benchmark run."""

    original_uri: str
    resolved_path: str
    sha256: Optional[str]
    filename: str
    cache_hit: bool
    source_kind: str
    cache_dir: Optional[str]
    download_url: Optional[str]
    size_bytes: Optional[int]

    def to_dict(self) -> Dict[str, object]:
        """Return a JSON-friendly receipt for bundle provenance."""
        return {
            "original_uri": self.original_uri,
            "resolved_path": self.resolved_path,
            "sha256": self.sha256,
            "filename": self.filename,
            "cache_hit": self.cache_hit,
            "source_kind": self.source_kind,
            "cache_dir": self.cache_dir,
            "download_url": self.download_url,
            "size_bytes": self.size_bytes,
        }


def resolve_quant_artifact(request: RunRequest) -> Optional[ResolvedArtifact]:
    """Resolve the quantized weights for a run, downloading them when needed."""
    if not request.quant_artifact:
        return None
    artifact = request.quant_artifact
    if _is_local_artifact_reference(artifact):
        local_path = _normalize_local_path(artifact)
        if not os.path.isfile(local_path):
            raise ValueError("Quant artifact does not exist: %s" % artifact)
        sha256 = compute_file_sha256(local_path)
        _verify_expected_sha256(local_path, sha256, request.quant_artifact_sha256)
        return ResolvedArtifact(
            original_uri=artifact,
            resolved_path=local_path,
            sha256=sha256,
            filename=request.quant_artifact_filename or os.path.basename(local_path),
            cache_hit=False,
            source_kind="local_file",
            cache_dir=None,
            download_url=None,
            size_bytes=os.path.getsize(local_path),
        )

    download_url = artifact_to_download_url(artifact, revision=request.quant_artifact_revision)
    cache_dir = os.path.abspath(request.quant_artifact_cache_dir or default_artifact_cache_dir())
    ensure_dir(cache_dir)
    filename = request.quant_artifact_filename or _infer_filename(artifact)
    cache_path = _cache_path(cache_dir, artifact, filename, request.quant_artifact_sha256)
    if os.path.isfile(cache_path):
        cached_sha = compute_file_sha256(cache_path)
        _verify_expected_sha256(cache_path, cached_sha, request.quant_artifact_sha256)
        return ResolvedArtifact(
            original_uri=artifact,
            resolved_path=cache_path,
            sha256=cached_sha,
            filename=os.path.basename(cache_path),
            cache_hit=True,
            source_kind="cache",
            cache_dir=cache_dir,
            download_url=download_url,
            size_bytes=os.path.getsize(cache_path),
        )

    tmp_fd, tmp_path = tempfile.mkstemp(prefix="infergrade-artifact-", suffix=".tmp", dir=cache_dir)
    os.close(tmp_fd)
    try:
        _download_remote_artifact(download_url, tmp_path)
        sha256 = compute_file_sha256(tmp_path)
        _verify_expected_sha256(tmp_path, sha256, request.quant_artifact_sha256)
        os.replace(tmp_path, cache_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return ResolvedArtifact(
        original_uri=artifact,
        resolved_path=cache_path,
        sha256=sha256,
        filename=os.path.basename(cache_path),
        cache_hit=False,
        source_kind="download",
        cache_dir=cache_dir,
        download_url=download_url,
        size_bytes=os.path.getsize(cache_path),
    )


def default_artifact_cache_dir() -> str:
    """Return the default on-disk cache directory for downloaded artifacts."""
    home = os.path.expanduser("~")
    return os.path.join(home, ".cache", "infergrade", "artifacts")


def compute_file_sha256(path: str) -> str:
    """Compute a SHA256 digest for a local file."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def artifact_to_download_url(uri: str, revision: Optional[str] = None) -> str:
    """Translate a supported artifact reference into a concrete download URL."""
    if uri.startswith("hf://"):
        without_scheme = uri[len("hf://") :].strip("/")
        parts = without_scheme.split("/")
        if len(parts) < 3:
            raise ValueError("hf:// artifact references must include repo and file path: %s" % uri)
        repo_id = "/".join(parts[:2])
        file_path = "/".join(parts[2:])
        resolved_revision = revision or "main"
        return "https://huggingface.co/%s/resolve/%s/%s" % (
            repo_id,
            urllib_parse.quote(resolved_revision, safe=""),
            urllib_parse.quote(file_path, safe="/"),
        )
    if uri.startswith("http://") or uri.startswith("https://"):
        return uri
    raise ValueError("Unsupported remote artifact reference: %s" % uri)


def _download_remote_artifact(download_url: str, destination_path: str) -> None:
    """Download a remote artifact, falling back to curl when stdlib transport fails."""
    try:
        with urllib_request.urlopen(download_url) as response, open(destination_path, "wb") as handle:
            shutil.copyfileobj(response, handle)
        return
    except Exception as exc:
        if not _should_fallback_to_curl(exc):
            raise
    _download_with_curl(download_url, destination_path)


def _should_fallback_to_curl(exc: Exception) -> bool:
    """Return whether curl is likely to succeed where urllib failed."""
    if shutil.which("curl") is None:
        return False
    if isinstance(exc, urllib_error.URLError):
        return True
    return False


def _download_with_curl(download_url: str, destination_path: str) -> None:
    """Use curl as a pragmatic fallback for artifact downloads."""
    completed = subprocess.run(
        ["curl", "-L", "--fail", "-o", destination_path, download_url],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            "curl failed while downloading %s: %s" % (download_url, message or "unknown error")
        )


def _cache_path(cache_dir: str, artifact: str, filename: str, expected_sha256: Optional[str]) -> str:
    """Derive a stable cache path for a remote artifact reference."""
    digest = expected_sha256 or stable_hash({"artifact": artifact, "filename": filename}, length=16)
    return os.path.join(cache_dir, "%s-%s" % (digest[:16], filename))


def _infer_filename(uri: str) -> str:
    """Infer a filename from a URI when the request omitted one explicitly."""
    parsed = urllib_parse.urlparse(uri)
    path = parsed.path if parsed.scheme in ("http", "https", "file") else uri
    filename = os.path.basename(path)
    if filename:
        return filename
    return "artifact.bin"


def _is_local_artifact_reference(uri: str) -> bool:
    """Return whether a URI should be treated as an already-local file."""
    if uri.startswith("file://"):
        return True
    return not (uri.startswith("http://") or uri.startswith("https://") or uri.startswith("hf://"))


def _normalize_local_path(uri: str) -> str:
    """Normalize local artifact references into absolute filesystem paths."""
    if uri.startswith("file://"):
        return urllib_parse.unquote(urllib_parse.urlparse(uri).path)
    return os.path.abspath(uri)


def _verify_expected_sha256(path: str, actual_sha256: str, expected_sha256: Optional[str]) -> None:
    """Raise when the resolved artifact digest does not match the request contract."""
    if not expected_sha256:
        return
    if actual_sha256.lower() != expected_sha256.lower():
        raise ValueError(
            "SHA256 mismatch for %s. Expected %s, got %s."
            % (path, expected_sha256.lower(), actual_sha256.lower())
        )
