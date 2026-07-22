"""Small bounded GGUF metadata helpers shared by resolution and execution."""

import os
import re
import struct
from typing import Any, Optional


def _read_exact(handle, length: int) -> bytes:
    payload = handle.read(length)
    if len(payload) != length:
        raise ValueError("Unexpected end of GGUF metadata.")
    return payload


def _read_u32(handle) -> int:
    return struct.unpack("<I", _read_exact(handle, 4))[0]


def _read_u64(handle) -> int:
    return struct.unpack("<Q", _read_exact(handle, 8))[0]


def _read_string(handle) -> str:
    length = _read_u64(handle)
    if length > 1024 * 1024:
        raise ValueError("GGUF metadata string is unexpectedly large.")
    return _read_exact(handle, length).decode("utf-8", errors="replace")


def _skip_value(handle, value_type: int) -> None:
    fixed_width = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
    if value_type in fixed_width:
        _read_exact(handle, fixed_width[value_type])
        return
    if value_type == 8:
        _read_string(handle)
        return
    if value_type == 9:
        item_type = _read_u32(handle)
        count = _read_u64(handle)
        if count > 100000:
            raise ValueError("GGUF metadata array is unexpectedly large.")
        for _ in range(count):
            _skip_value(handle, item_type)
        return
    raise ValueError("Unsupported GGUF metadata value type: %s" % value_type)


def normalize_architecture(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "").replace("_", "")


def read_gguf_architecture(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as handle:
            if _read_exact(handle, 4) != b"GGUF":
                return None
            _read_u32(handle)
            _read_u64(handle)
            metadata_count = _read_u64(handle)
            if metadata_count > 100000:
                return None
            for _ in range(metadata_count):
                key = _read_string(handle)
                value_type = _read_u32(handle)
                if key == "general.architecture" and value_type == 8:
                    return normalize_architecture(_read_string(handle))
                _skip_value(handle, value_type)
    except (OSError, struct.error, UnicodeDecodeError, ValueError):
        return None
    return None


def infer_llama_cpp_architecture(request: Any) -> Optional[str]:
    hints = dict(getattr(request, "ontology_hints", {}) or {})
    explicit = (
        hints.get("architecture")
        or hints.get("model_architecture")
        or hints.get("gguf_architecture")
        or hints.get("llama_cpp_architecture")
    )
    if explicit:
        return normalize_architecture(str(explicit))
    artifact = getattr(request, "quant_artifact_resolved_path", None) or getattr(request, "quant_artifact", None)
    if artifact and os.path.isfile(artifact) and str(artifact).lower().endswith(".gguf"):
        architecture = read_gguf_architecture(artifact)
        if architecture:
            return architecture
    candidates = [
        getattr(request, "model", None),
        hints.get("family_name"),
        getattr(request, "quant_artifact_filename", None),
        getattr(request, "quant_artifact", None),
    ]
    for candidate in candidates:
        normalized = re.sub(r"[^a-z0-9]+", "", str(candidate or "").lower())
        for marker in ("dspark", "qwen35", "qwen3", "gemma4", "gemma3", "gemma2"):
            if marker in normalized:
                return marker
    return None
