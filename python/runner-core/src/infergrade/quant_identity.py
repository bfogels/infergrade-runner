"""Deterministic quant and artifact-source identity helpers."""

import os
import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse


CANONICALIZATION_VERSION = "quant_v1"
ONTOLOGY_IDENTITY_VERSION = "model_quant_identity_v1"

_SEPARATORS_RE = re.compile(r"[\s.\-]+")
_UNDERSCORES_RE = re.compile(r"_+")
_GGUF_TOKEN_RE = re.compile(
    r"(?<![a-z0-9])((?:iq|tq|q)_?\d+(?:_?k(?:_?(?:xxs|xs|s|m|l|xl|nl))?|_?(?:xxs|xs|s|m|l|xl|nl)|_[01])?)(?![a-z0-9]|_[a-z])",
    re.IGNORECASE,
)
_INT_TOKEN_RE = re.compile(r"(?<![a-z0-9])(int_?\d+)(?![a-z0-9])", re.IGNORECASE)
_FLOAT_TOKEN_RE = re.compile(
    r"(?<![a-z0-9])((?:bf|fp|nvfp|mxfp)_?\d+)(?![a-z0-9])",
    re.IGNORECASE,
)
_WEIGHT_ACTIVATION_RE = re.compile(
    r"(?<![a-z0-9])(w_?\d+_?a_?\d+)(?![a-z0-9])",
    re.IGNORECASE,
)
_GGUF_SIZE = r"xxs|xs|s|m|l|xl|nl"


def normalize_quantization_format(value: Any) -> Optional[str]:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    aliases = {
        "ggml_gguf": "gguf",
        "safetensor": "safetensors",
        "safe_tensors": "safetensors",
    }
    return aliases.get(normalized, normalized)


def normalize_source_provider(value: Any) -> Optional[str]:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    aliases = {
        "hf": "huggingface",
        "hugging_face": "huggingface",
    }
    return aliases.get(normalized, normalized)


def canonicalize_quantization_scheme(value: Any) -> Dict[str, Optional[str]]:
    """Return a lossless canonical scheme without guessing broader aliases."""
    raw = str(value or "").strip()
    normalized = _normalize_text(raw)
    if not normalized:
        return {"raw": raw or None, "canonical": None, "status": "unknown"}

    gguf = _canonical_gguf_token(normalized)
    if gguf:
        status = "generic" if re.fullmatch(r"(?:iq|tq|q)\d+", gguf) else (
            "exact" if normalized == gguf else "alias"
        )
        return {"raw": raw, "canonical": gguf, "status": status}

    compact = normalized.replace("_", "")
    if re.fullmatch(r"int\d+", compact):
        return {
            "raw": raw,
            "canonical": compact,
            "status": "exact" if normalized == compact else "alias",
        }
    if re.fullmatch(r"(?:bf|fp|nvfp|mxfp)\d+", compact):
        return {
            "raw": raw,
            "canonical": compact,
            "status": "exact" if normalized == compact else "alias",
        }
    if re.fullmatch(r"w\d+a\d+", compact):
        return {
            "raw": raw,
            "canonical": compact,
            "status": "exact" if normalized == compact else "alias",
        }
    if normalized in {"awq", "gptq", "bitsandbytes"}:
        return {"raw": raw, "canonical": normalized, "status": "generic"}
    return {"raw": raw, "canonical": normalized, "status": "unknown"}


def infer_quantization_from_label(value: Any) -> Dict[str, Optional[str]]:
    """Find a recognized quant token in one artifact basename only."""
    raw = os.path.basename(str(value or "").split("?", 1)[0]).strip()
    stem = raw
    for suffix in (".safetensors", ".gguf", ".bin", ".pt", ".pth"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    normalized = _normalize_text(stem)
    for pattern in (_GGUF_TOKEN_RE, _INT_TOKEN_RE, _FLOAT_TOKEN_RE, _WEIGHT_ACTIVATION_RE):
        match = pattern.search(normalized)
        if match:
            resolved = canonicalize_quantization_scheme(match.group(1))
            if (
                resolved.get("canonical")
                and str(resolved["canonical"]).lower() not in stem.lower()
                and resolved.get("status") == "exact"
            ):
                resolved["status"] = "alias"
            return resolved
    return {"raw": raw or None, "canonical": None, "status": "unknown"}


def quantization_identity(
    explicit_scheme: Any,
    artifact_label: Any,
    quantization_format: Any,
    inferred_quantization_format: Any = None,
) -> Dict[str, Optional[str]]:
    """Bind explicit metadata and filename inference into one fail-closed ID."""
    explicit = canonicalize_quantization_scheme(explicit_scheme)
    inferred = infer_quantization_from_label(artifact_label)
    normalized_format = normalize_quantization_format(quantization_format)
    inferred_format = normalize_quantization_format(inferred_quantization_format)
    explicit_known = explicit["status"] != "unknown" and bool(explicit["canonical"])
    inferred_known = inferred["status"] != "unknown" and bool(inferred["canonical"])

    compatible_formats = (
        {normalized_format, inferred_format} in ({"safetensors", "awq"}, {"safetensors", "gptq"})
    )
    format_conflict = bool(
        normalized_format
        and inferred_format
        and normalized_format != inferred_format
        and not compatible_formats
    )
    if format_conflict:
        canonical = explicit["canonical"] if explicit_scheme not in (None, "") else inferred["canonical"]
        status = "conflict"
        quantization_id = None
    elif explicit_known and inferred_known and explicit["canonical"] != inferred["canonical"]:
        canonical = explicit["canonical"]
        status = "conflict"
        quantization_id = None
    elif explicit_scheme not in (None, ""):
        canonical = explicit["canonical"]
        status = explicit["status"]
        quantization_id = (
            "%s:%s" % (normalized_format, canonical)
            if normalized_format and canonical and status != "unknown"
            else None
        )
    else:
        canonical = inferred["canonical"]
        status = inferred["status"]
        quantization_id = (
            "%s:%s" % (normalized_format, canonical)
            if normalized_format and canonical and status != "unknown"
            else canonical
            if canonical and status != "unknown"
            else None
        )
    return {
        "quantization_scheme_raw": str(explicit_scheme or inferred.get("raw") or "").strip() or None,
        "quantization_scheme": canonical,
        "quantization_id": quantization_id,
        "canonicalization_status": status,
        "canonicalization_version": CANONICALIZATION_VERSION,
    }


def infer_artifact_source(
    artifact_reference: Any,
    explicit_source: Optional[Dict[str, Any]] = None,
    revision: Any = None,
    allow_plain_hf_repo: bool = False,
) -> Dict[str, Optional[str]]:
    """Return source/provider identity, preferring an unambiguous HF URI."""
    source = {
        "provider": None,
        "repository_id": None,
        "publisher": None,
        "publisher_id": None,
        "revision": str(revision or "").strip() or None,
    }
    explicit = explicit_source if isinstance(explicit_source, dict) else {}
    for key in source:
        if key in explicit and explicit.get(key) not in (None, ""):
            source[key] = str(explicit[key]).strip()
    source["provider"] = normalize_source_provider(source["provider"])

    hf = _huggingface_repository(artifact_reference, allow_plain_reference=allow_plain_hf_repo)
    if hf:
        publisher, repository_id = hf
        source.update(
            {
                "provider": "huggingface",
                "repository_id": repository_id,
                "publisher": publisher,
                "publisher_id": "huggingface:%s" % publisher.lower(),
            }
        )
    elif (
        source["repository_id"]
        and source["provider"] == "huggingface"
        and "/" in source["repository_id"]
    ):
        publisher = source["repository_id"].split("/", 1)[0]
        source["publisher"] = publisher
        source["publisher_id"] = "huggingface:%s" % publisher.lower()
    elif source["publisher"]:
        provider = source["provider"] or "publisher"
        source["publisher_id"] = "%s:%s" % (provider, _slug(source["publisher"]))
    elif source["publisher_id"]:
        source["publisher_id"] = _normalize_publisher_id(source["publisher_id"])
    return source


def artifact_source_identity_payload(source: Any) -> Dict[str, Optional[str]]:
    """Return case-stable source coordinates while preserving display metadata."""
    value = source if isinstance(source, dict) else {}
    provider = normalize_source_provider(value.get("provider"))
    repository_id = str(value.get("repository_id") or "").strip() or None
    if provider == "huggingface" and repository_id:
        repository_id = repository_id.lower()
    return {
        "provider": provider,
        "repository_id": repository_id,
        "publisher_id": _normalize_publisher_id(value.get("publisher_id")),
        "revision": str(value.get("revision") or "").strip() or None,
    }


def _canonical_gguf_token(value: str) -> Optional[str]:
    normalized = _normalize_text(value)
    numeric_suffix = re.fullmatch(r"(iq|tq|q)_?(\d+)_([01])", normalized)
    if numeric_suffix:
        return "%s%s_%s" % numeric_suffix.groups()
    k_quant = re.fullmatch(
        r"(iq|tq|q)_?(\d+)_?k(?:_?(%s))?" % _GGUF_SIZE,
        normalized,
    )
    if k_quant:
        prefix, bits, size = k_quant.groups()
        return "%s%s_k%s" % (prefix, bits, "_%s" % size if size else "")
    sized = re.fullmatch(r"(iq|tq|q)_?(\d+)_?(%s)" % _GGUF_SIZE, normalized)
    if sized:
        prefix, bits, size = sized.groups()
        return "%s%s_%s" % (prefix, bits, size)
    generic = re.fullmatch(r"(iq|tq|q)_?(\d+)", normalized)
    if generic:
        return "%s%s" % generic.groups()
    return None


def _huggingface_repository(value: Any, allow_plain_reference: bool = False):
    reference = str(value or "").strip()
    if reference.startswith("hf://"):
        parts = [part for part in reference[5:].split("/") if part]
    else:
        parsed = urlparse(reference)
        if parsed.netloc.lower() in {"huggingface.co", "www.huggingface.co"}:
            parts = [part for part in parsed.path.split("/") if part]
        elif (
            allow_plain_reference
            and not parsed.scheme
            and not reference.startswith(("/", "."))
            and "\\" not in reference
            and len([part for part in reference.split("/") if part]) == 2
        ):
            parts = [part for part in reference.split("/") if part]
        else:
            return None
    if len(parts) < 2:
        return None
    return parts[0], "%s/%s" % (parts[0], parts[1])


def _normalize_text(value: Any) -> str:
    normalized = _SEPARATORS_RE.sub("_", str(value or "").strip().lower())
    normalized = _UNDERSCORES_RE.sub("_", normalized)
    return normalized.strip("_")


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-") or "unknown"


def _normalize_publisher_id(value: Any) -> Optional[str]:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if ":" not in raw:
        return _slug(raw)
    provider, publisher = raw.split(":", 1)
    return "%s:%s" % (normalize_source_provider(provider) or "publisher", _slug(publisher))
