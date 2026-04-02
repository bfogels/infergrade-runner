"""Persist and resolve paired local runner configuration."""

import json
import os
from typing import Any, Dict, Optional

from infergrade.utils import ensure_dir, env_value


def runner_config_dir() -> str:
    """Return the directory that stores local runner pairing state."""
    override = env_value("INFERGRADE_CONFIG_DIR")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    xdg = env_value("XDG_CONFIG_HOME")
    if xdg:
        return os.path.abspath(os.path.join(os.path.expanduser(xdg), "infergrade"))
    return os.path.abspath(os.path.expanduser("~/.config/infergrade"))


def runner_profile_path() -> str:
    """Return the local profile path used by the paired runner flow."""
    return os.path.join(runner_config_dir(), "runner_profile.json")


def load_runner_profile() -> Optional[Dict[str, Any]]:
    """Load the paired runner profile when present."""
    path = runner_profile_path()
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_runner_profile(profile: Dict[str, Any]) -> str:
    """Persist the paired runner profile to disk with user-only permissions."""
    path = runner_profile_path()
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(profile, handle, indent=2, sort_keys=True)
        handle.write("\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def clear_runner_profile() -> bool:
    """Delete the paired runner profile when present."""
    path = runner_profile_path()
    if not os.path.exists(path):
        return False
    os.unlink(path)
    return True


def resolve_runner_api_url(api_url: Optional[str] = None) -> Optional[str]:
    """Resolve the API URL from the explicit value or the paired runner profile."""
    if api_url:
        return str(api_url).strip()
    profile = load_runner_profile() or {}
    return str(profile.get("api_url") or "").strip() or None


def resolve_runner_api_token(api_token: Optional[str] = None) -> Optional[str]:
    """Resolve the Hub token from the explicit value or the paired runner profile."""
    if api_token:
        return str(api_token).strip()
    profile = load_runner_profile() or {}
    return str(profile.get("access_token") or "").strip() or None
