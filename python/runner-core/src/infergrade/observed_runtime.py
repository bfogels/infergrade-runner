"""Loopback-only observed runtime contract and OpenAI-compatible transport.

This module deliberately describes what a local endpoint reports, rather than
what the endpoint's model artifact or runtime can be independently verified to
be.  It is a small seam for an already-running local server.  The existing
managed/native llama.cpp path remains the source of verified runtime receipts.

The module has no logging and never puts an endpoint URL, credential, local
path, or generated text in an observed receipt.  Errors expose stable codes so
callers can report a useful failure without echoing request or response data.
"""

import ipaddress
import json
import math
import re
import socket
import ssl
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from infergrade.tls import verified_https_context


OBSERVED_RUNTIME_CONTRACT_VERSION = "observed_runtime_v1"
OPENAI_CHAT_COMPLETIONS_PROTOCOL = "openai_chat_completions_v1"
QUICK_GENERATION_PROFILE_VERSION = "quick_generation_v1"

DEFAULT_TIMEOUT_SECONDS = 2.0
MAX_TIMEOUT_SECONDS = 10.0
DEFAULT_GENERATION_TIMEOUT_SECONDS = 300.0
MAX_GENERATION_TIMEOUT_SECONDS = 600.0
DEFAULT_MAX_RESPONSE_BYTES = 512 * 1024
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_REQUEST_BYTES = 256 * 1024
MAX_OUTPUT_CHARS = 128 * 1024
MAX_MODEL_ID_LENGTH = 512
MAX_DISCOVERY_ENDPOINTS = 5
MAX_DISCOVERY_RESPONSE_BYTES = 128 * 1024

FAILURE_CODES = (
    "endpoint_invalid",
    "non_loopback_endpoint",
    "unsupported_scheme",
    "redirect_not_allowed",
    "timeout",
    "connection_failed",
    "http_error",
    "response_too_large",
    "invalid_json",
    "invalid_response",
    "malformed_sse",
    "empty_response",
    "model_not_available",
    "provider_error",
    "request_too_large",
)


class ObservedRuntimeError(RuntimeError):
    """An observed-runtime failure with a stable, privacy-safe code."""

    def __init__(
        self,
        code: str,
        status: Optional[int] = None,
        optional_controls_rejected: bool = False,
    ):
        if code not in FAILURE_CODES:
            code = "connection_failed"
        self.code = code
        self.status = status
        self.optional_controls_rejected = bool(optional_controls_rejected)
        # Do not include a URL, exception text, response body, or path here.
        super().__init__(code)


@dataclass(frozen=True)
class LocalEndpoint:
    """Validated endpoint metadata kept in memory for one local probe."""

    scheme: str
    host: str
    port: int
    base_path: str = ""

    @property
    def network_scope(self) -> str:
        return "loopback"

    def safe_metadata(self) -> Dict[str, Any]:
        """Return the only endpoint facts allowed into an observed receipt."""
        return {"network_scope": self.network_scope}


@dataclass(frozen=True)
class ProviderProfile:
    """A bounded local discovery profile, not a runtime identity assertion."""

    provider: str
    default_port: int
    model_paths: Tuple[str, ...]


PROVIDER_PROFILES: Tuple[ProviderProfile, ...] = (
    ProviderProfile("ollama", 11434, ("/api/tags", "/v1/models")),
    ProviderProfile("lm_studio", 1234, ("/v1/models",)),
    ProviderProfile("llama_server", 8080, ("/v1/models",)),
    ProviderProfile("vllm", 8000, ("/v1/models",)),
    ProviderProfile("tgi", 3000, ("/v1/models", "/info")),
)
_PROVIDER_BY_NAME = {item.provider: item for item in PROVIDER_PROFILES}
_PROVIDER_BY_PORT = {item.default_port: item.provider for item in PROVIDER_PROFILES}
_PROVIDER_ALIASES = {
    "lm-studio": "lm_studio",
    "lmstudio": "lm_studio",
    "llama-server": "llama_server",
    "llama.cpp": "llama_server",
    "text-generation-inference": "tgi",
}
_THINKING_CONTROL_PROVIDERS = frozenset(("llama_server", "vllm", "unknown"))


def _thinking_controls(provider: str) -> Optional[Dict[str, Any]]:
    """Return explicitly supported no-thinking request extensions."""
    if provider not in _THINKING_CONTROL_PROVIDERS:
        return None
    if provider == "llama_server":
        return {
            "chat_template_kwargs": {"enable_thinking": False},
            "thinking_budget_tokens": 0,
        }
    if provider == "vllm":
        return {"chat_template_kwargs": {"enable_thinking": False}}
    if provider == "unknown":
        # A custom-port OpenAI-compatible endpoint has no trustworthy provider
        # identity. Try the shared llama.cpp/vLLM extension once, then fall
        # back to the strict OpenAI payload if the server rejects that field.
        return {"chat_template_kwargs": {"enable_thinking": False}}
    return None


def _default_generation_profile() -> Dict[str, Any]:
    return {
        "profile_version": QUICK_GENERATION_PROFILE_VERSION,
        "temperature": 0.0,
        "max_tokens": None,
        "stream": None,
        "thinking_control": {
            "requested": False,
            "effective": "not_run",
        },
    }


def _receipt_generation_profile(profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize the bounded generation facts carried by a receipt."""
    result = _default_generation_profile()
    if not isinstance(profile, dict):
        return result
    max_tokens = profile.get("max_tokens")
    if isinstance(max_tokens, int) and not isinstance(max_tokens, bool) and 1 <= max_tokens <= 4096:
        result["max_tokens"] = max_tokens
    stream = profile.get("stream")
    if isinstance(stream, bool):
        result["stream"] = stream
    thinking_control = profile.get("thinking_control")
    if isinstance(thinking_control, dict):
        requested = thinking_control.get("requested")
        effective = thinking_control.get("effective")
        if isinstance(requested, bool):
            result["thinking_control"]["requested"] = requested
        if effective in (
            "not_run",
            "not_verified",
            "server_default_uncontrolled",
            "rejected",
            "request_failed",
        ):
            result["thinking_control"]["effective"] = effective
    return result


def _canonical_provider(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return _PROVIDER_ALIASES.get(normalized, normalized) if normalized else None


def provider_profiles() -> Tuple[ProviderProfile, ...]:
    """Return the fixed discovery set used by the local contribution path."""
    return PROVIDER_PROFILES


def _bounded_timeout(value: Any) -> float:
    if isinstance(value, bool):
        raise ObservedRuntimeError("endpoint_invalid")
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        raise ObservedRuntimeError("endpoint_invalid")
    if not math.isfinite(timeout) or timeout <= 0 or timeout > MAX_TIMEOUT_SECONDS:
        raise ObservedRuntimeError("endpoint_invalid")
    return timeout


def _bounded_generation_timeout(value: Any) -> float:
    if isinstance(value, bool):
        raise ObservedRuntimeError("endpoint_invalid")
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        raise ObservedRuntimeError("endpoint_invalid")
    if not math.isfinite(timeout) or timeout <= 0 or timeout > MAX_GENERATION_TIMEOUT_SECONDS:
        raise ObservedRuntimeError("endpoint_invalid")
    return timeout


def _bounded_response_limit(value: Any) -> int:
    if isinstance(value, bool):
        raise ObservedRuntimeError("endpoint_invalid")
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise ObservedRuntimeError("endpoint_invalid")
    if limit <= 0 or limit > MAX_RESPONSE_BYTES:
        raise ObservedRuntimeError("endpoint_invalid")
    return limit


def _host_is_loopback(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    if normalized == "localhost":
        # Resolve the conventional name and fail closed if the host mapping
        # has been altered away from loopback.  Arbitrary hostnames are never
        # accepted, avoiding DNS rebinding and accidental LAN scans.
        try:
            addresses = {
                info[4][0]
                for info in socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
            }
        except (OSError, socket.gaierror):
            return False
        return bool(addresses) and all(_host_is_loopback(address) for address in addresses)
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv4Address):
        return address.packed[0] == 127
    return address == ipaddress.IPv6Address("::1")


def _normalize_base_path(path: str) -> str:
    path = str(path or "")
    if path in ("", "/"):
        return ""
    if "\x00" in path or "\\" in path or ".." in path:
        raise ObservedRuntimeError("endpoint_invalid")
    if not path.startswith("/") or len(path) > 64:
        raise ObservedRuntimeError("endpoint_invalid")
    parts = [item for item in path.split("/") if item]
    if not parts or any(not item.replace("-", "").replace("_", "").replace(".", "").isalnum() for item in parts):
        raise ObservedRuntimeError("endpoint_invalid")
    return "/" + "/".join(parts)


def parse_local_endpoint(endpoint: str) -> LocalEndpoint:
    """Validate an explicit endpoint and require a loopback destination.

    Userinfo, queries, fragments, non-HTTP schemes, and non-loopback hosts are
    rejected before any socket is opened.  The URL is intentionally not
    retained in receipts or error messages.
    """
    raw = str(endpoint or "")
    if not raw or raw != raw.strip() or len(raw) > 512 or any(ch.isspace() for ch in raw):
        raise ObservedRuntimeError("endpoint_invalid")
    bracketed_host = re.match(r"^https?://\[([^]]+)\]", raw, re.IGNORECASE)
    if bracketed_host and bracketed_host.group(1).lower() != "::1":
        raise ObservedRuntimeError("non_loopback_endpoint")
    try:
        parsed = urllib_parse.urlsplit(raw)
        scheme = parsed.scheme.lower()
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except (ValueError, UnicodeError):
        raise ObservedRuntimeError("endpoint_invalid")
    if scheme not in ("http", "https"):
        raise ObservedRuntimeError("unsupported_scheme")
    if not host or not _host_is_loopback(host):
        raise ObservedRuntimeError("non_loopback_endpoint")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise ObservedRuntimeError("endpoint_invalid")
    if parsed.query or parsed.fragment:
        raise ObservedRuntimeError("endpoint_invalid")
    if port is None:
        port = 443 if scheme == "https" else 80
    if port < 1 or port > 65535:
        raise ObservedRuntimeError("endpoint_invalid")
    return LocalEndpoint(
        scheme=scheme,
        host=host,
        port=port,
        base_path=_normalize_base_path(parsed.path),
    )


def _endpoint_url(endpoint: LocalEndpoint, path: str) -> str:
    """Build a request URL internally; callers must not serialize this value."""
    normalized_path = "/" + str(path or "").lstrip("/")
    base = endpoint.base_path.rstrip("/")
    if base and (normalized_path == base or normalized_path.startswith(base + "/")):
        target = normalized_path
    elif base:
        target = base + normalized_path
    else:
        target = normalized_path
    host = endpoint.host
    if ":" in host and not host.startswith("["):
        host = "[" + host + "]"
    return "%s://%s:%d%s" % (endpoint.scheme, host, endpoint.port, target)


class _NoRedirectHandler(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise ObservedRuntimeError("redirect_not_allowed")


def _open_no_redirect(request: urllib_request.Request, endpoint: LocalEndpoint, timeout: float):
    handlers: List[Any] = [_NoRedirectHandler()]
    if endpoint.scheme == "https":
        handlers.append(urllib_request.HTTPSHandler(context=verified_https_context(_endpoint_url(endpoint, "/"))))
    opener = urllib_request.build_opener(*handlers)
    return opener.open(request, timeout=timeout)


def _read_bounded(response: Any, limit: int) -> bytes:
    headers = getattr(response, "headers", None)
    if headers is not None:
        content_length = headers.get("Content-Length")
        try:
            if content_length is not None and int(content_length) > limit:
                raise ObservedRuntimeError("response_too_large")
        except ValueError:
            raise ObservedRuntimeError("invalid_response")
    chunks: List[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(16 * 1024, limit - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ObservedRuntimeError("response_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


def _model_id(value: Any) -> Optional[str]:
    """Normalize a model ID for in-memory protocol use only.

    This is intentionally less restrictive than the receipt-label filter:
    llama-server can report an absolute artifact path that may still be needed
    to address a running endpoint.  Callers must use
    :func:`safe_receipt_model_label` before persisting an ID.
    """
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_MODEL_ID_LENGTH
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        return None
    return normalized


_SAFE_RECEIPT_MODEL_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:+/-"
)
_ASCII_ALPHANUMERIC = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
)
_WINDOWS_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def safe_receipt_model_label(value: Any) -> Optional[str]:
    """Return a public-safe reported model label, or ``None`` to withhold it.

    Endpoint model IDs are untrusted strings.  In particular, a llama-server
    ``/v1/models`` response may contain the local absolute GGUF path.  The
    receipt filter rejects absolute/Windows paths, URLs, traversal, controls,
    query/fragment/credential-like syntax, and whitespace while allowing
    ordinary ``owner/model`` labels and Ollama ``model:tag`` names.
    """
    if not isinstance(value, str) or value != value.strip():
        return None
    normalized = _model_id(value)
    if normalized is None or any(character not in _SAFE_RECEIPT_MODEL_CHARS for character in normalized):
        return None
    if normalized[0] not in _ASCII_ALPHANUMERIC:
        return None
    lowered = normalized.lower()
    if (
        normalized.startswith(("/", "~"))
        or _WINDOWS_DRIVE_PATH_RE.match(normalized)
        or "//" in normalized
        or "?" in normalized
        or "#" in normalized
        or "=" in normalized
        or "@" in normalized
        or "://" in normalized
        or lowered.startswith(("file:", "http:", "https:"))
    ):
        return None
    parts = normalized.split("/")
    if (
        not parts
        or normalized.count("/") > 1
        or any(part in ("", ".", "..") for part in parts)
        or any(part[0] not in _ASCII_ALPHANUMERIC for part in parts)
        or lowered.endswith((".gguf", ".bin", ".safetensors", ".pt", ".pth", ".onnx"))
    ):
        return None
    if any(
        marker in lowered
        for marker in (
            "password",
            "passwd",
            "bearer",
            "credential",
            "authorization",
            "api_key",
            "apikey",
            "auth:",
            "key=",
            "token=",
            "token:",
            "secret=",
            "secret:",
        )
    ):
        return None
    return normalized


def _parse_model_ids(payload: Any) -> Optional[List[str]]:
    """Parse common model-list/info shapes without inferring artifact facts."""
    if not isinstance(payload, dict):
        return None
    candidates: Iterable[Any]
    if isinstance(payload.get("data"), list):
        candidates = payload["data"]
        values = []
        for item in list(candidates)[:64]:
            if not isinstance(item, dict):
                return None
            values.append(_model_id(item.get("id")))
    elif isinstance(payload.get("models"), list):
        candidates = payload["models"]
        values = []
        for item in list(candidates)[:64]:
            if isinstance(item, dict):
                values.append(_model_id(item.get("name") or item.get("model") or item.get("id")))
            else:
                values.append(_model_id(item))
    else:
        values = [_model_id(payload.get("model_id") or payload.get("id"))]
    result: List[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
        if len(result) >= 64:
            break
    return result if result or values == [] or any(value is None for value in values) is False else None


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_extract_text(item) for item in value]
        return "".join(parts)
    if isinstance(value, dict):
        return _extract_text(value.get("text") or value.get("content") or "")
    return ""


def _extract_chat_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise ObservedRuntimeError("invalid_response")
    if payload.get("error"):
        raise ObservedRuntimeError("provider_error")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ObservedRuntimeError("invalid_response")
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message")
    delta = first.get("delta")
    text = _extract_text((message or {}).get("content") if isinstance(message, dict) else None)
    if not text:
        text = _extract_text((delta or {}).get("content") if isinstance(delta, dict) else None)
    return text


def _payload_has_reasoning(payload: Any) -> bool:
    """Detect reasoning-only chat content without persisting its text."""
    if not isinstance(payload, dict):
        return False
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return False
    for choice in choices[:1]:
        if not isinstance(choice, dict):
            continue
        for container_key in ("message", "delta"):
            container = choice.get(container_key)
            if not isinstance(container, dict):
                continue
            for key in ("reasoning_content", "reasoning", "thinking"):
                if container.get(key):
                    return True
    return False


def _parse_sse(body: bytes) -> str:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = body.decode("utf-8", errors="replace")
    pieces: List[str] = []
    total_chars = 0
    saw_event = False
    for line in text.splitlines():
        if len(line) > 64 * 1024:
            raise ObservedRuntimeError("response_too_large")
        if not line or line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        data = line[5:].lstrip()
        if data == "[DONE]":
            saw_event = True
            continue
        try:
            payload = json.loads(data)
        except (TypeError, ValueError):
            raise ObservedRuntimeError("malformed_sse")
        saw_event = True
        try:
            piece = _extract_chat_text(payload)
        except ObservedRuntimeError as exc:
            if exc.code == "invalid_response":
                # Some providers send a terminal chunk with no delta.
                piece = ""
            else:
                raise
        pieces.append(piece)
        total_chars += len(piece)
        if total_chars > MAX_OUTPUT_CHARS:
            raise ObservedRuntimeError("response_too_large")
    if not saw_event:
        raise ObservedRuntimeError("malformed_sse")
    result = "".join(pieces)
    if not result:
        raise ObservedRuntimeError("empty_response")
    return result


@dataclass
class ObservedRuntimeProbe:
    """Safe result of one endpoint compatibility probe."""

    endpoint: LocalEndpoint
    provider: str
    model_ids: List[str]
    model_endpoint_status: str
    chat_endpoint_status: str = "not_probed"
    failure_code: Optional[str] = None
    generation_profile: Dict[str, Any] = field(default_factory=dict)

    def to_receipt(self, selected_model_id: Optional[str] = None) -> Dict[str, Any]:
        # Keep the endpoint's raw reported IDs in this in-memory probe so the
        # adapter can address a server that uses an absolute artifact path as
        # its model selector.  Only receipt-safe labels cross this boundary.
        raw_model_ids: List[str] = []
        for value in list(self.model_ids[:64]):
            normalized = _model_id(value)
            if normalized and normalized not in raw_model_ids:
                raw_model_ids.append(normalized)
        safe_model_ids: List[str] = []
        for value in raw_model_ids:
            label = safe_receipt_model_label(value)
            if label and label not in safe_model_ids:
                safe_model_ids.append(label)
        withheld_model_id_count = len(raw_model_ids) - len(safe_model_ids)

        selected_requested = selected_model_id is not None
        selected_raw_model_id = _model_id(selected_model_id)
        selected_is_reported = (
            selected_raw_model_id is not None and selected_raw_model_id in raw_model_ids
        )
        selected_label = (
            safe_receipt_model_label(selected_raw_model_id)
            if selected_is_reported
            else None
        )
        if selected_requested:
            reported_model_id = selected_label
            selected_model_id_status = (
                "reported"
                if selected_is_reported and selected_label is not None
                else "withheld_unsafe"
                if selected_is_reported
                else "not_reported"
            )
        else:
            reported_model_id = safe_model_ids[0] if safe_model_ids else None
            selected_model_id_status = "not_selected"
        if not raw_model_ids:
            model_id_status = "unavailable"
        elif withheld_model_id_count and safe_model_ids:
            model_id_status = "reported_with_withheld"
        elif withheld_model_id_count:
            model_id_status = "withheld_unsafe"
        else:
            model_id_status = "reported"
        provider = self.provider if isinstance(self.provider, str) and self.provider in _PROVIDER_BY_NAME else "unknown"
        receipt = {
            "contract_version": OBSERVED_RUNTIME_CONTRACT_VERSION,
            "evidence_kind": "observed_runtime",
            "evidence_lane": "observed",
            "verification_status": "not_verified",
            "verified": False,
            "promotion_eligible": False,
            "provider": provider,
            "provider_status": "compatibility_hint",
            "endpoint": self.endpoint.safe_metadata(),
            "protocol": {
                "name": OPENAI_CHAT_COMPLETIONS_PROTOCOL,
                "models_endpoint": self.model_endpoint_status,
                "chat_completions": self.chat_endpoint_status,
            },
            "generation_profile": _receipt_generation_profile(self.generation_profile),
            "identity": {
                "reported_model_id": reported_model_id,
                "reported_model_ids": safe_model_ids,
                "reported_model_id_status": model_id_status,
                "reported_model_id_count": len(raw_model_ids),
                "withheld_model_id_count": withheld_model_id_count,
                "selected_model_id_status": selected_model_id_status,
                "artifact_publisher": None,
                "quantization": None,
                "artifact_sha256": None,
                "runtime_build_id": None,
                "runtime_bytes": None,
                "status": "reported_only",
            },
            "claim_boundary": {
                "artifact_publisher": "unknown",
                "quantization": "unknown",
                "artifact_checksum": "unknown",
                "runtime_build": "unknown",
                "runtime_bytes": "unknown",
            },
            "privacy": {
                "endpoint_url_recorded": False,
                "credentials_recorded": False,
                "local_paths_recorded": False,
                "raw_outputs_recorded": False,
            },
            "failure_code": self.failure_code,
        }
        validate_observed_runtime_receipt(receipt)
        return receipt

    def to_dict(self, selected_model_id: Optional[str] = None) -> Dict[str, Any]:
        return self.to_receipt(selected_model_id=selected_model_id)


def validate_observed_runtime_receipt(receipt: Dict[str, Any]) -> None:
    """Validate privacy and trust invariants before a receipt is persisted."""
    if not isinstance(receipt, dict):
        raise ValueError("observed runtime receipt must be an object")
    forbidden_keys = {
        "url",
        "endpoint_url",
        "authorization",
        "api_key",
        "token",
        "password",
        "port",
        "path",
        "local_path",
        "raw_output",
        "output",
    }
    stack: List[Any] = [receipt]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if forbidden_keys.intersection(current):
                raise ValueError("observed runtime receipt contains a private field")
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
        elif isinstance(current, str) and (current.startswith("http://") or current.startswith("https://")):
            raise ValueError("observed runtime receipt contains an endpoint URL")
    if receipt.get("contract_version") != OBSERVED_RUNTIME_CONTRACT_VERSION:
        raise ValueError("observed runtime receipt contract version is unsupported")
    if receipt.get("evidence_kind") != "observed_runtime" or receipt.get("verified") is not False:
        raise ValueError("observed runtime evidence boundary is invalid")
    if receipt.get("evidence_lane") != "observed" or receipt.get("verification_status") != "not_verified":
        raise ValueError("observed runtime receipt trust boundary is invalid")
    if receipt.get("promotion_eligible") is not False:
        raise ValueError("observed runtime receipt cannot be promotion eligible")
    if receipt.get("endpoint") != {"network_scope": "loopback"}:
        raise ValueError("observed runtime endpoint metadata is invalid")
    identity = receipt.get("identity") or {}
    if any(identity.get(key) is not None for key in ("artifact_publisher", "quantization", "artifact_sha256", "runtime_build_id", "runtime_bytes")):
        raise ValueError("observed runtime receipt contains an unverified identity claim")
    if identity.get("status") != "reported_only":
        raise ValueError("observed runtime identity must remain reported_only")
    reported_model_ids = identity.get("reported_model_ids")
    if not isinstance(reported_model_ids, list) or len(reported_model_ids) > 64:
        raise ValueError("observed runtime reported model IDs are invalid")
    if not all(isinstance(model_id, str) for model_id in reported_model_ids):
        raise ValueError("observed runtime reported model IDs are invalid")
    if len(reported_model_ids) != len(set(reported_model_ids)):
        raise ValueError("observed runtime reported model IDs are not unique")
    for model_id in reported_model_ids:
        if safe_receipt_model_label(model_id) != model_id:
            raise ValueError("observed runtime receipt contains an unsafe model ID")
    reported_model_id = identity.get("reported_model_id")
    if reported_model_id is not None and safe_receipt_model_label(reported_model_id) != reported_model_id:
        raise ValueError("observed runtime receipt contains an unsafe selected model ID")
    selected_model_id_status = identity.get("selected_model_id_status")
    if selected_model_id_status not in ("reported", "withheld_unsafe", "not_reported", "not_selected"):
        raise ValueError("observed runtime selected model ID status is invalid")
    if selected_model_id_status == "reported" and reported_model_id is None:
        raise ValueError("observed runtime selected model ID status is inconsistent")
    if selected_model_id_status in ("withheld_unsafe", "not_reported") and reported_model_id is not None:
        raise ValueError("observed runtime selected model ID must be withheld")
    if reported_model_id is not None and reported_model_id not in reported_model_ids:
        raise ValueError("observed runtime selected model ID is not reported")
    model_id_status = identity.get("reported_model_id_status")
    if model_id_status not in ("reported", "reported_with_withheld", "withheld_unsafe", "unavailable"):
        raise ValueError("observed runtime model ID status is invalid")
    model_id_count = identity.get("reported_model_id_count")
    withheld_model_id_count = identity.get("withheld_model_id_count")
    if (
        isinstance(model_id_count, bool)
        or not isinstance(model_id_count, int)
        or model_id_count < len(reported_model_ids)
        or model_id_count > 64
        or isinstance(withheld_model_id_count, bool)
        or not isinstance(withheld_model_id_count, int)
        or withheld_model_id_count < 0
        or withheld_model_id_count > model_id_count
        or model_id_count - withheld_model_id_count != len(reported_model_ids)
    ):
        raise ValueError("observed runtime model ID counts are invalid")
    expected_status = (
        "unavailable"
        if model_id_count == 0
        else "reported_with_withheld"
        if withheld_model_id_count and reported_model_ids
        else "withheld_unsafe"
        if withheld_model_id_count
        else "reported"
    )
    if model_id_status != expected_status:
        raise ValueError("observed runtime model ID status does not match counts")
    generation_profile = receipt.get("generation_profile")
    if not isinstance(generation_profile, dict):
        raise ValueError("observed runtime generation profile is missing")
    if generation_profile.get("profile_version") != QUICK_GENERATION_PROFILE_VERSION:
        raise ValueError("observed runtime generation profile is unsupported")
    if generation_profile.get("temperature") != 0.0:
        raise ValueError("observed runtime generation temperature is not bounded")
    max_tokens = generation_profile.get("max_tokens")
    if max_tokens is not None and (
        isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1 or max_tokens > 4096
    ):
        raise ValueError("observed runtime generation max_tokens is invalid")
    stream = generation_profile.get("stream")
    if stream is not None and not isinstance(stream, bool):
        raise ValueError("observed runtime generation stream state is invalid")
    thinking_control = generation_profile.get("thinking_control")
    if not isinstance(thinking_control, dict):
        raise ValueError("observed runtime thinking control is missing")
    if not isinstance(thinking_control.get("requested"), bool):
        raise ValueError("observed runtime thinking control request state is invalid")
    if thinking_control.get("effective") not in (
        "not_run",
        "not_verified",
        "server_default_uncontrolled",
        "rejected",
        "request_failed",
    ):
        raise ValueError("observed runtime thinking control effective state is invalid")
    privacy = receipt.get("privacy") or {}
    if any(privacy.get(key) is not False for key in (
        "endpoint_url_recorded",
        "credentials_recorded",
        "local_paths_recorded",
        "raw_outputs_recorded",
    )):
        raise ValueError("observed runtime privacy boundary is invalid")


class OpenAICompatibleClient(object):
    """Small bounded HTTP client for local OpenAI-compatible endpoints."""

    def __init__(
        self,
        endpoint: str,
        provider_hint: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        generation_timeout_seconds: float = DEFAULT_GENERATION_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ):
        self.endpoint = parse_local_endpoint(endpoint)
        raw_provider_hint = provider_hint
        provider_hint = _canonical_provider(provider_hint)
        if raw_provider_hint is not None and provider_hint not in _PROVIDER_BY_NAME:
            raise ObservedRuntimeError("endpoint_invalid")
        self.provider_hint = provider_hint
        # The key is used only in memory for a local request and is never
        # included in a receipt or exception.  Local runtimes normally omit it.
        self._api_key = str(api_key) if api_key else None
        if self._api_key is not None and len(self._api_key) > 4096:
            raise ObservedRuntimeError("endpoint_invalid")
        self.timeout_seconds = _bounded_timeout(timeout_seconds)
        self.generation_timeout_seconds = _bounded_generation_timeout(generation_timeout_seconds)
        self.max_response_bytes = _bounded_response_limit(max_response_bytes)
        self._last_probe: Optional[ObservedRuntimeProbe] = None
        self._last_generation_profile: Optional[Dict[str, Any]] = None

    @property
    def last_probe(self) -> Optional[ObservedRuntimeProbe]:
        return self._last_probe

    @property
    def last_generation_profile(self) -> Optional[Dict[str, Any]]:
        return self._last_generation_profile

    def reset_generation_profile(self) -> None:
        """Clear per-call generation facts before a new adapter attempt."""
        self._last_generation_profile = None

    def _effective_provider(self) -> str:
        if self._last_probe is not None and self._last_probe.provider in _PROVIDER_BY_NAME:
            return self._last_probe.provider
        if self.provider_hint in _PROVIDER_BY_NAME:
            return self.provider_hint
        return _PROVIDER_BY_PORT.get(self.endpoint.port, "unknown")

    def _record_generation_profile(self, profile: Dict[str, Any]) -> None:
        self._last_generation_profile = profile
        if self._last_probe is not None:
            self._last_probe.generation_profile = profile

    def _set_generation_effective(self, effective: str) -> None:
        profile = self._last_generation_profile
        if isinstance(profile, dict):
            thinking_control = profile.get("thinking_control")
            if isinstance(thinking_control, dict):
                thinking_control["effective"] = effective

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout_seconds: Optional[float] = None,
    ) -> Tuple[bytes, str]:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            if len(body) > MAX_REQUEST_BYTES:
                raise ObservedRuntimeError("request_too_large")
            headers["Content-Type"] = "application/json"
        if self._api_key:
            headers["Authorization"] = "Bearer " + self._api_key
        url = _endpoint_url(self.endpoint, path)
        request = urllib_request.Request(url, data=body, headers=headers, method=method.upper())
        try:
            timeout = self.timeout_seconds if timeout_seconds is None else timeout_seconds
            with _open_no_redirect(request, self.endpoint, timeout) as response:
                status = int(response.getcode() or 0)
                if status < 200 or status >= 300:
                    raise ObservedRuntimeError("http_error", status=status)
                response_body = _read_bounded(response, self.max_response_bytes)
                content_type = str(getattr(response, "headers", {}).get("Content-Type", ""))
                return response_body, content_type
        except ObservedRuntimeError:
            raise
        except urllib_error.HTTPError as exc:
            # Redirects are rejected by _NoRedirectHandler.  Other statuses
            # remain one stable code, without echoing provider error bodies.
            status = exc.code
            detail = exc.read(8192) if status in (400, 422) else b""
            exc.close()
            if status in (301, 302, 303, 307, 308):
                raise ObservedRuntimeError("redirect_not_allowed")
            normalized_detail = detail.lower()
            optional_controls_rejected = (
                b"chat_template_kwargs" in normalized_detail
                and any(
                    marker in normalized_detail
                    for marker in (
                        b"unknown",
                        b"unrecognized",
                        b"unexpected",
                        b"not permitted",
                        b"extra",
                    )
                )
            )
            raise ObservedRuntimeError(
                "http_error",
                status=status,
                optional_controls_rejected=optional_controls_rejected,
            )
        except (socket.timeout, TimeoutError):
            raise ObservedRuntimeError("timeout")
        except urllib_error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), (socket.timeout, TimeoutError)):
                raise ObservedRuntimeError("timeout")
            raise ObservedRuntimeError("connection_failed")
        except (OSError, ssl.SSLError):
            raise ObservedRuntimeError("connection_failed")
        except RuntimeError:
            # TLS trust configuration failures are local diagnostics. Never
            # expose their path-bearing messages through the observed lane.
            raise ObservedRuntimeError("connection_failed")

    def _paths_for_probe(self) -> Tuple[str, ...]:
        if self.provider_hint:
            return _PROVIDER_BY_NAME[self.provider_hint].model_paths
        by_port = _PROVIDER_BY_PORT.get(self.endpoint.port)
        if by_port:
            return _PROVIDER_BY_NAME[by_port].model_paths
        return ("/v1/models",)

    def probe(self) -> ObservedRuntimeProbe:
        last_error: Optional[ObservedRuntimeError] = None
        for path in self._paths_for_probe():
            try:
                body, _content_type = self._request("GET", path)
            except ObservedRuntimeError as exc:
                last_error = exc
                # A provider-specific fallback is useful for Ollama/TGI, while
                # a timeout/connection failure should not cause extra requests.
                if exc.code != "http_error" or exc.status != 404:
                    break
                continue
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise ObservedRuntimeError("invalid_json")
            model_ids = _parse_model_ids(payload)
            if model_ids is None:
                raise ObservedRuntimeError("invalid_response")
            provider = self.provider_hint or _PROVIDER_BY_PORT.get(self.endpoint.port) or (
                "ollama" if path == "/api/tags" else "unknown"
            )
            probe = ObservedRuntimeProbe(
                endpoint=self.endpoint,
                provider=provider,
                model_ids=model_ids,
                model_endpoint_status="compatible",
            )
            self._last_probe = probe
            return probe
        if last_error is not None:
            raise last_error
        raise ObservedRuntimeError("connection_failed")

    def complete(self, model_id: str, prompt: str, max_tokens: int, stream: bool = False) -> str:
        self._last_generation_profile = None
        normalized_model = _model_id(model_id)
        if normalized_model is None:
            raise ObservedRuntimeError("model_not_available")
        if not isinstance(prompt, str) or not prompt:
            raise ObservedRuntimeError("endpoint_invalid")
        if len(prompt.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ObservedRuntimeError("request_too_large")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1 or max_tokens > 4096:
            raise ObservedRuntimeError("endpoint_invalid")
        provider = self._effective_provider()
        controls = _thinking_controls(provider)
        generation_profile = {
            "profile_version": QUICK_GENERATION_PROFILE_VERSION,
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "stream": bool(stream),
            "thinking_control": {
                "requested": controls is not None,
                "effective": "not_verified" if controls is not None else "server_default_uncontrolled",
            },
        }
        self._record_generation_profile(generation_profile)
        request_payload = {
            "model": normalized_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0,
            "stream": bool(stream),
        }
        if controls is not None:
            request_payload.update(controls)
        try:
            body, content_type = self._request(
                "POST",
                "/v1/chat/completions",
                payload=request_payload,
                timeout_seconds=self.generation_timeout_seconds,
            )
        except ObservedRuntimeError as exc:
            if (
                provider == "unknown"
                and controls is not None
                and exc.code == "http_error"
                and exc.status in (400, 422)
                and exc.optional_controls_rejected
            ):
                fallback_payload = dict(request_payload)
                for key in controls:
                    fallback_payload.pop(key, None)
                self._set_generation_effective("rejected")
                try:
                    body, content_type = self._request(
                        "POST",
                        "/v1/chat/completions",
                        payload=fallback_payload,
                        timeout_seconds=self.generation_timeout_seconds,
                    )
                except ObservedRuntimeError:
                    self._set_generation_effective("request_failed")
                    raise
            else:
                self._set_generation_effective("request_failed")
                raise
        if stream or "text/event-stream" in content_type.lower() or body.lstrip().startswith(b"data:"):
            try:
                text = _parse_sse(body)
            except ObservedRuntimeError:
                self._set_generation_effective("request_failed")
                raise
        else:
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                self._set_generation_effective("request_failed")
                raise ObservedRuntimeError("invalid_json")
            try:
                text = _extract_chat_text(payload)
            except ObservedRuntimeError:
                self._set_generation_effective("request_failed")
                raise
            if not text:
                if _payload_has_reasoning(payload):
                    self._set_generation_effective("rejected")
                else:
                    self._set_generation_effective("request_failed")
                raise ObservedRuntimeError("empty_response")
        if len(text) > MAX_OUTPUT_CHARS:
            self._set_generation_effective("request_failed")
            raise ObservedRuntimeError("response_too_large")
        if self._last_probe is not None:
            self._last_probe.chat_endpoint_status = "compatible"
        return text


def _failed_discovery_receipt(endpoint: LocalEndpoint, provider: str, code: str) -> Dict[str, Any]:
    probe = ObservedRuntimeProbe(
        endpoint=endpoint,
        provider=provider,
        model_ids=[],
        model_endpoint_status="unavailable",
        failure_code=code if code in FAILURE_CODES else "connection_failed",
    )
    return probe.to_receipt()


def discover_local_runtimes(
    endpoints: Optional[Sequence[Any]] = None,
    timeout_seconds: float = 0.35,
    max_response_bytes: int = MAX_DISCOVERY_RESPONSE_BYTES,
) -> List[Dict[str, Any]]:
    """Probe only the five fixed loopback profiles, with a hard endpoint bound.

    ``endpoints`` is an optional test/operator seam containing either endpoint
    strings or ``(endpoint, provider_hint)`` pairs.  Every value still passes
    :func:`parse_local_endpoint`, and at most five probes are attempted.
    """
    timeout = _bounded_timeout(timeout_seconds)
    response_limit = _bounded_response_limit(max_response_bytes)
    candidates: List[Tuple[str, Optional[str]]] = []
    if endpoints is None:
        for profile in PROVIDER_PROFILES:
            candidates.append(("http://127.0.0.1:%d" % profile.default_port, profile.provider))
    else:
        for item in list(endpoints)[:MAX_DISCOVERY_ENDPOINTS]:
            if isinstance(item, (tuple, list)) and len(item) == 2:
                candidates.append((str(item[0]), item[1]))
            else:
                candidates.append((str(item), None))
    results: List[Dict[str, Any]] = []
    for raw_endpoint, provider_hint in candidates[:MAX_DISCOVERY_ENDPOINTS]:
        try:
            parsed = parse_local_endpoint(raw_endpoint)
            client = OpenAICompatibleClient(
                raw_endpoint,
                provider_hint=provider_hint,
                timeout_seconds=timeout,
                max_response_bytes=response_limit,
            )
            results.append(client.probe().to_receipt())
        except ObservedRuntimeError as exc:
            try:
                parsed = parse_local_endpoint(raw_endpoint)
            except ObservedRuntimeError:
                # There is no safe endpoint metadata to preserve when input
                # validation itself failed.
                continue
            canonical_hint = _canonical_provider(provider_hint)
            provider = (
                canonical_hint
                if canonical_hint in _PROVIDER_BY_NAME
                else _PROVIDER_BY_PORT.get(parsed.port, "unknown")
            )
            results.append(_failed_discovery_receipt(parsed, provider, exc.code))
    return results


__all__ = [
    "DEFAULT_MAX_RESPONSE_BYTES",
    "DEFAULT_GENERATION_TIMEOUT_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "FAILURE_CODES",
    "LocalEndpoint",
    "MAX_DISCOVERY_ENDPOINTS",
    "OPENAI_CHAT_COMPLETIONS_PROTOCOL",
    "OBSERVED_RUNTIME_CONTRACT_VERSION",
    "QUICK_GENERATION_PROFILE_VERSION",
    "ObservedRuntimeError",
    "ObservedRuntimeProbe",
    "OpenAICompatibleClient",
    "ProviderProfile",
    "discover_local_runtimes",
    "parse_local_endpoint",
    "provider_profiles",
    "safe_receipt_model_label",
    "validate_observed_runtime_receipt",
]
