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
    unwritable current directory. Keep absolute paths unchanged for explicit
    operator control, and place relative paths under the Runner output root.
    """
    raw = str(output_dir or "").strip() or os.path.join("runs", run_id)
    expanded = Path(raw).expanduser()
    if expanded.is_absolute():
        return str(expanded)

    normalized = Path(os.path.normpath(raw))
    parts = [part for part in normalized.parts if part not in ("", ".")]
    if any(part == ".." for part in parts):
        parts = [run_id]
    elif parts and parts[0] == "runs":
        parts = parts[1:]
    if not parts:
        parts = [run_id]
    return str(runner_output_root().joinpath(*parts))
