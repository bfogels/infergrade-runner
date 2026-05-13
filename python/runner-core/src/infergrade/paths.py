"""Filesystem path helpers for repo and packaged Runner layouts."""

import os
from pathlib import Path
from typing import Iterable, Optional


def runner_root() -> Path:
    """Return a root containing Runner-owned resources such as schemas.

    Source checkouts keep schemas at the repository root. The desktop app
    bundles runner-core under Resources/runner-core and schemas under
    Resources/schemas, so walking fixed parents from __file__ is not reliable.
    """
    current = Path(__file__).resolve()
    for candidate in _candidate_roots(current):
        if (candidate / "schemas").is_dir():
            return candidate
    return current.parents[4]


def _candidate_roots(current: Path) -> Iterable[Path]:
    env_root = os.environ.get("INFERGRADE_RUNNER_ROOT")
    if env_root:
        yield Path(env_root)
    for parent in current.parents:
        yield parent
        yield parent / "Resources"


def runner_output_root() -> Path:
    """Return the user-writable root for Hub-claimed run outputs."""
    override = os.environ.get("INFERGRADE_RUNNER_OUTPUT_ROOT")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "infergrade" / "runs"


def resolve_worker_output_dir(output_dir: Optional[str], run_id: str) -> str:
    """Resolve a Hub job output_dir into a path the packaged runner can write.

    Hub jobs historically use relative paths such as ``runs/run_id``. That is
    fine in a developer checkout, but a packaged macOS app may launch from an
    unwritable current directory. Treat claimed paths as untrusted by default:
    place them under the Runner output root and contain traversal attempts.
    """
    safe_run_id = _safe_path_segment(run_id, fallback="run")
    raw = str(output_dir or "").strip() or os.path.join("runs", safe_run_id)
    expanded = Path(raw).expanduser()
    if expanded.is_absolute() and os.environ.get("INFERGRADE_ALLOW_ABSOLUTE_WORKER_OUTPUT_DIR") == "1":
        return str(expanded)
    if expanded.is_absolute():
        parts = [safe_run_id]
    else:
        normalized = Path(os.path.normpath(raw))
        parts = [part for part in normalized.parts if part not in ("", ".")]
        if any(part == ".." for part in parts):
            parts = [safe_run_id]
        elif parts and parts[0] == "runs":
            parts = parts[1:]
        parts = [_safe_path_segment(part, fallback=safe_run_id) for part in parts]

    if not parts:
        parts = [safe_run_id]
    root = runner_output_root().resolve()
    resolved = root.joinpath(*parts).resolve()
    if resolved != root and root not in resolved.parents:
        resolved = root.joinpath(safe_run_id).resolve()
    return str(resolved)


def _safe_path_segment(value: str, fallback: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in ("-", "_", ".") else "_" for char in str(value or ""))
    cleaned = cleaned.strip(" .")
    if not cleaned or cleaned in {".", ".."}:
        return fallback
    return cleaned
