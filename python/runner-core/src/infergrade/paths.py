"""Filesystem path helpers for repo and packaged Runner layouts."""

import os
from pathlib import Path
from typing import Iterable


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
