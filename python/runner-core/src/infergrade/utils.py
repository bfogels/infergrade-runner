import hashlib
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional


def utcnow_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_") or "value"


def stable_hash(payload: Any, length: int = 12) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:length]


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def write_json(path: str, payload: Dict[str, Any]) -> None:
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def write_text(path: str, payload: str) -> None:
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(payload)
        if not payload.endswith("\n"):
            handle.write("\n")


def read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def env_value(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read an environment variable, returning the default when unset."""
    if name in os.environ:
        return os.environ.get(name)
    return default


def dump_simple_yaml(value: Any, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(value, dict):
        lines: List[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append("%s%s:" % (prefix, key))
                lines.append(dump_simple_yaml(item, indent + 2))
            else:
                lines.append("%s%s: %s" % (prefix, key, _yaml_scalar(item)))
        return "\n".join(lines)
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append("%s-" % prefix)
                lines.append(dump_simple_yaml(item, indent + 2))
            else:
                lines.append("%s- %s" % (prefix, _yaml_scalar(item)))
        return "\n".join(lines)
    return "%s%s" % (prefix, _yaml_scalar(value))


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "" or any(ch in text for ch in [":", "#", "{", "}", "[", "]"]) or text.strip() != text:
        return json.dumps(text)
    return text
