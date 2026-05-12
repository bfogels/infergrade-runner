"""Persist and resolve paired local runner configuration."""

import json
import os
from typing import Any, Dict, Optional

from infergrade.environment import capture_environment
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


def preferred_local_execution_mode() -> str:
    """Return the clearest default local execution mode for this machine."""
    environment = capture_environment("local_native")
    if (environment or {}).get("hardware_class") == "apple_silicon":
        return "local_native"
    return "local_container"


def resolve_runner_execution_mode(execution_mode: Optional[str] = None) -> str:
    """Resolve the execution mode from an explicit value, saved profile, or local hardware."""
    if execution_mode:
        return str(execution_mode).strip()
    profile = load_runner_profile() or {}
    if profile.get("preferred_execution_mode"):
        return str(profile["preferred_execution_mode"]).strip()
    return preferred_local_execution_mode()


def resolve_runner_id(runner_id: Optional[str] = None) -> Optional[str]:
    """Resolve the durable runner identifier from an explicit value or the paired profile."""
    if runner_id:
        return str(runner_id).strip()
    profile = load_runner_profile() or {}
    saved = str(profile.get("runner_id") or "").strip()
    return saved or None


def resolve_runner_label(label: Optional[str] = None) -> Optional[str]:
    """Resolve the saved human runner label."""
    if label:
        return str(label).strip()
    profile = load_runner_profile() or {}
    return str(profile.get("runner_label") or profile.get("label") or "").strip() or None


def resolve_runner_kind(kind: Optional[str] = None) -> Optional[str]:
    """Resolve the saved runner identity kind."""
    if kind:
        return str(kind).strip()
    profile = load_runner_profile() or {}
    return str(profile.get("runner_kind") or "").strip() or None
