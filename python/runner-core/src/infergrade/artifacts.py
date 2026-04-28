"""Artifact resolution helpers for local, cached, and remote quantized files."""

import json
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from infergrade.models import RunRequest
from infergrade.utils import ensure_dir, stable_hash


DEFAULT_MIN_ARTIFACT_CACHE_FREE_GB = 5.0
DEFAULT_PARTIAL_ARTIFACT_MIN_AGE_SECONDS = 3600
PARTIAL_ARTIFACT_PREFIX = "infergrade-artifact-"
PARTIAL_ARTIFACT_SUFFIX = ".tmp"


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
            filename=_safe_artifact_filename(request.quant_artifact_filename)
            or os.path.basename(local_path),
            cache_hit=False,
            source_kind="local_file",
            cache_dir=None,
            download_url=None,
            size_bytes=os.path.getsize(local_path),
        )

    resolved_artifact_uri = artifact
    _require_secure_remote_artifact(resolved_artifact_uri, request.quant_artifact_sha256)
    download_url = artifact_to_download_url(resolved_artifact_uri, revision=request.quant_artifact_revision)
    cache_dir = _normalized_cache_dir(request.quant_artifact_cache_dir or default_artifact_cache_dir())
    ensure_dir(cache_dir)
    filename = _safe_artifact_filename(request.quant_artifact_filename) or _infer_filename(resolved_artifact_uri)
    cache_path = _cache_path(cache_dir, resolved_artifact_uri, filename, request.quant_artifact_sha256)
    if os.path.isfile(cache_path):
        cached_sha = compute_file_sha256(cache_path)
        _verify_expected_sha256(cache_path, cached_sha, request.quant_artifact_sha256)
        return ResolvedArtifact(
            original_uri=resolved_artifact_uri,
            resolved_path=cache_path,
            sha256=cached_sha,
            filename=os.path.basename(cache_path),
            cache_hit=True,
            source_kind="cache",
            cache_dir=cache_dir,
            download_url=download_url,
            size_bytes=os.path.getsize(cache_path),
        )

    ensure_min_free_space(cache_dir, min_artifact_cache_free_bytes(), "artifact cache")
    tmp_fd, tmp_path = tempfile.mkstemp(prefix="infergrade-artifact-", suffix=".tmp", dir=cache_dir)
    os.close(tmp_fd)
    try:
        try:
            _download_remote_artifact(download_url, tmp_path)
        except Exception as exc:
            if _is_huggingface_not_found(exc) and resolved_artifact_uri.startswith("hf://"):
                canonical_artifact_uri = canonicalize_hf_artifact_reference(resolved_artifact_uri)
                if canonical_artifact_uri != resolved_artifact_uri:
                    resolved_artifact_uri = canonical_artifact_uri
                    download_url = artifact_to_download_url(resolved_artifact_uri, revision=request.quant_artifact_revision)
                    filename = _safe_artifact_filename(request.quant_artifact_filename) or _infer_filename(resolved_artifact_uri)
                    cache_path = _cache_path(cache_dir, resolved_artifact_uri, filename, request.quant_artifact_sha256)
                    _download_remote_artifact(download_url, tmp_path)
                else:
                    raise
            else:
                raise
        sha256 = compute_file_sha256(tmp_path)
        _verify_expected_sha256(tmp_path, sha256, request.quant_artifact_sha256)
        os.replace(tmp_path, cache_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return ResolvedArtifact(
        original_uri=resolved_artifact_uri,
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


def min_artifact_cache_free_bytes() -> int:
    """Return the configured minimum free bytes required for artifact downloads."""
    return _env_gb_to_bytes("INFERGRADE_MIN_ARTIFACT_CACHE_FREE_GB", DEFAULT_MIN_ARTIFACT_CACHE_FREE_GB)


def artifact_cache_status(cache_dir: Optional[str] = None) -> Dict[str, object]:
    """Return size, partial-file, and free-space details for the artifact cache."""
    path = _normalized_cache_dir(cache_dir or default_artifact_cache_dir())
    files = _artifact_cache_files(path)
    partial_files = [item for item in files if _is_partial_artifact_path(item["path"])]
    artifact_files = [item for item in files if not _is_partial_artifact_path(item["path"])]
    disk_path = _existing_disk_usage_path(path)
    free_bytes = shutil.disk_usage(disk_path).free
    min_free_bytes = min_artifact_cache_free_bytes()
    return {
        "cache_dir": path,
        "exists": os.path.isdir(path),
        "artifact_count": len(artifact_files),
        "artifact_bytes": sum(int(item["size_bytes"]) for item in artifact_files),
        "partial_count": len(partial_files),
        "partial_bytes": sum(int(item["size_bytes"]) for item in partial_files),
        "total_count": len(files),
        "total_bytes": sum(int(item["size_bytes"]) for item in files),
        "free_bytes": free_bytes,
        "free_gb": _bytes_to_gb(free_bytes),
        "min_required_free_bytes": min_free_bytes,
        "min_required_free_gb": _bytes_to_gb(min_free_bytes),
    }


def prune_partial_artifacts(
    cache_dir: Optional[str] = None,
    dry_run: bool = False,
    min_age_seconds: int = DEFAULT_PARTIAL_ARTIFACT_MIN_AGE_SECONDS,
) -> Dict[str, object]:
    """Remove stale incomplete temp files from the cache, leaving active downloads intact."""
    path = _normalized_cache_dir(cache_dir or default_artifact_cache_dir())
    now = time.time()
    partial_files = [
        item
        for item in _artifact_cache_files(path)
        if _is_partial_artifact_path(item["path"]) and _is_stale_partial_artifact(item, now, min_age_seconds)
    ]
    removed: List[Dict[str, object]] = []
    for item in partial_files:
        if not dry_run:
            try:
                os.unlink(item["path"])
            except FileNotFoundError:
                continue
        removed.append(item)
    return {
        "cache_dir": path,
        "dry_run": dry_run,
        "min_age_seconds": max(0, int(min_age_seconds)),
        "removed_count": len(removed),
        "removed_bytes": sum(int(item["size_bytes"]) for item in removed),
        "removed": removed,
        "status": artifact_cache_status(path),
    }


def ensure_min_free_space(path: str, min_free_bytes: int, context: str) -> None:
    """Raise when a directory has less free disk space than the configured floor."""
    if min_free_bytes <= 0:
        return
    expanded = _normalized_cache_dir(path)
    free_bytes = shutil.disk_usage(_existing_disk_usage_path(expanded)).free
    if free_bytes >= min_free_bytes:
        return
    raise RuntimeError(
        "insufficient free disk space for %s: %.2f GB free, %.2f GB required at %s"
        % (context, _bytes_to_gb(free_bytes), _bytes_to_gb(min_free_bytes), expanded)
    )


def _normalized_cache_dir(path: str) -> str:
    """Expand user-relative cache paths before resolving them to absolute paths."""
    return os.path.abspath(os.path.expanduser(path))


def _env_gb_to_bytes(name: str, default_gb: float) -> int:
    """Parse an environment variable expressed in GiB into bytes."""
    raw_value = os.environ.get(name)
    if raw_value is None or str(raw_value).strip() == "":
        gb_value = default_gb
    else:
        try:
            gb_value = float(str(raw_value).strip())
        except ValueError:
            gb_value = default_gb
    return max(0, int(gb_value * (1024 ** 3)))


def _bytes_to_gb(value: int) -> float:
    """Return a two-decimal GiB value for human-facing diagnostics."""
    return round(float(value) / float(1024 ** 3), 2)


def _existing_disk_usage_path(path: str) -> str:
    """Return the nearest existing path suitable for shutil.disk_usage."""
    candidate = os.path.abspath(os.path.expanduser(path))
    while candidate and not os.path.exists(candidate):
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
    return candidate or os.path.abspath(os.sep)


def _artifact_cache_files(path: str) -> List[Dict[str, object]]:
    """Return top-level cache files with sizes for status and pruning."""
    if not os.path.isdir(path):
        return []
    files: List[Dict[str, object]] = []
    for name in sorted(os.listdir(path)):
        file_path = os.path.join(path, name)
        if not os.path.isfile(file_path):
            continue
        try:
            size_bytes = os.path.getsize(file_path)
            mtime = os.path.getmtime(file_path)
        except OSError:
            continue
        files.append({"path": file_path, "name": name, "size_bytes": size_bytes, "mtime": mtime})
    return files


def _is_stale_partial_artifact(item: Dict[str, object], now: float, min_age_seconds: int) -> bool:
    """Return whether a temp artifact is old enough to treat as interrupted."""
    try:
        age_seconds = now - float(item.get("mtime") or now)
    except (TypeError, ValueError):
        age_seconds = 0
    return age_seconds >= max(0, int(min_age_seconds))


def _is_partial_artifact_path(path: str) -> bool:
    """Return whether a path looks like an interrupted artifact temp download."""
    name = os.path.basename(path)
    return name.startswith(PARTIAL_ARTIFACT_PREFIX) and name.endswith(PARTIAL_ARTIFACT_SUFFIX)


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


def canonicalize_hf_artifact_reference(uri: str) -> str:
    """Return an hf:// URI rewritten to the exact Hub sibling path when possible."""
    repo_id, file_path = _parse_hf_artifact_reference(uri)
    siblings = _fetch_huggingface_siblings(repo_id)
    if file_path in siblings:
        return uri
    lookup = {path.lower(): path for path in siblings}
    corrected = lookup.get(file_path.lower())
    if not corrected:
        return uri
    return "hf://%s/%s" % (repo_id, corrected)


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


# curl's --proto / --proto-redir accept a list of permitted protocols with a
# leading "=" meaning "replace the default list". "=https" forbids cleartext
# http even if a 30x redirect tries to downgrade us mid-transfer.
_CURL_HTTPS_ONLY = ["--proto", "=https", "--proto-redir", "=https"]


def _download_with_curl(download_url: str, destination_path: str) -> None:
    """Use curl as a pragmatic fallback for artifact downloads."""
    completed = subprocess.run(
        ["curl", "-L", "--fail"] + _CURL_HTTPS_ONLY + ["-o", destination_path, download_url],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            "curl failed while downloading %s: %s" % (download_url, message or "unknown error")
        )


def _fetch_huggingface_siblings(repo_id: str) -> list:
    """Fetch sibling filenames for a Hugging Face model, using curl when needed."""
    url = "https://huggingface.co/api/models/%s" % urllib_parse.quote(repo_id, safe="/")
    try:
        with urllib_request.urlopen(url) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        if not _should_fallback_to_curl(exc):
            raise
        payload = _fetch_json_with_curl(url)
    return [item.get("rfilename") for item in payload.get("siblings", []) if item.get("rfilename")]


def _fetch_json_with_curl(url: str) -> Dict[str, object]:
    """Fetch JSON via curl as a pragmatic fallback on local Python SSL issues."""
    completed = subprocess.run(
        ["curl", "-L", "--fail"] + _CURL_HTTPS_ONLY + ["-H", "Accept: application/json", url],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError("curl failed while fetching %s: %s" % (url, message or "unknown error"))
    return json.loads(completed.stdout)


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


def _parse_hf_artifact_reference(uri: str) -> tuple:
    """Split an hf:// URI into repo id and file path."""
    without_scheme = uri[len("hf://") :].strip("/")
    parts = without_scheme.split("/")
    if len(parts) < 3:
        raise ValueError("hf:// artifact references must include repo and file path: %s" % uri)
    return "/".join(parts[:2]), "/".join(parts[2:])


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


def _is_huggingface_not_found(exc: Exception) -> bool:
    """Return whether an artifact download error looks like an HF 404."""
    message = str(exc).lower()
    return "404" in message or "not found" in message


def _verify_expected_sha256(path: str, actual_sha256: str, expected_sha256: Optional[str]) -> None:
    """Raise when the resolved artifact digest does not match the request contract."""
    if not expected_sha256:
        return
    if actual_sha256.lower() != expected_sha256.lower():
        raise ValueError(
            "SHA256 mismatch for %s. Expected %s, got %s."
            % (path, expected_sha256.lower(), actual_sha256.lower())
        )


def _safe_artifact_filename(candidate: Optional[str]) -> Optional[str]:
    """Return a hub-supplied filename verified to be a plain basename.

    The runner previously joined ``quant_artifact_filename`` (which the hub
    controls via the run config) straight into the cache path. A value like
    ``"../../../etc/passwd"`` would cause ``os.path.abspath`` to resolve
    the cache path outside ``cache_dir``, letting a malicious hub drop
    downloaded bytes anywhere the runner user can write
    (``~/.ssh/authorized_keys``, ``~/.config/infergrade/runner_profile.json``
    to clobber the token, shell rc files, etc.).

    Rather than silently basename-ing and hiding the hub's intent, fail
    loud: reject any filename that contains path separators, null bytes,
    or a ``..`` / ``.`` component. Operators investigating a rejected run
    will see the raw filename the hub asked for.
    """
    if candidate is None:
        return None
    trimmed = str(candidate).strip()
    if not trimmed:
        return None
    if "\x00" in trimmed:
        raise ValueError(
            "Invalid quant_artifact_filename %r: null bytes are not allowed"
            % candidate
        )
    if "/" in trimmed or "\\" in trimmed:
        raise ValueError(
            "Invalid quant_artifact_filename %r: path separators are not allowed"
            % candidate
        )
    if trimmed in {".", ".."}:
        raise ValueError(
            "Invalid quant_artifact_filename %r: traversal components are not allowed"
            % candidate
        )
    # Redundant sanity check - basename should match trimmed now that we have
    # rejected every way a separator could slip through.
    basename = os.path.basename(trimmed)
    if basename != trimmed or not basename:
        raise ValueError(
            "Invalid quant_artifact_filename %r: must be a plain basename"
            % candidate
        )
    return basename


def _require_secure_remote_artifact(uri: str, expected_sha256: Optional[str]) -> None:
    """Gate cleartext remote artifact downloads behind a pinned SHA256.

    ``https://`` and ``hf://`` URIs travel over TLS so TLS itself is the
    integrity guarantee. A plain ``http://`` URI is MITM-able (coffee shop
    wifi, hostile ISP, compromised transparent proxy), and the hub's run
    config is not itself signed, so the only defence left is the pinned
    digest. Refuse to download unpinned ``http://`` artifacts rather than
    silently pulling whatever bytes the network served.
    """
    if not uri:
        return
    if uri.startswith("https://") or uri.startswith("hf://"):
        return
    if uri.startswith("http://"):
        if not expected_sha256:
            raise ValueError(
                "Refusing to download artifact over cleartext http:// without a "
                "pinned quant_artifact_sha256: %s" % uri
            )
        return
    # Any other scheme is rejected upstream by ``artifact_to_download_url``.
