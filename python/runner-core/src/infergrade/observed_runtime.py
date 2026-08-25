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
import socket
import ssl
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from infergrade.tls import verified_https_context


OBSERVED_RUNTIME_CONTRACT_VERSION = "observed_runtime_v1"
OPENAI_CHAT_COMPLETIONS_PROTOCOL = "openai_chat_completions_v1"

DEFAULT_TIMEOUT_SECONDS = 2.0
MAX_TIMEOUT_SECONDS = 10.0
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

    def __init__(self, code: str, status: Optional[int] = None):
        if code not in FAILURE_CODES:
            code = "connection_failed"
        self.code = code
        self.status = status
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
        return {"network_scope": self.network_scope, "port": self.port}


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
    normalized = str(host or "").strip().lower().rstrip(".")
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
    if address.is_loopback:
        return True
    mapped = getattr(address, "ipv4_mapped", None)
    return bool(mapped and mapped.is_loopback)


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
    try:
        parsed = urllib_parse.urlsplit(raw)
        scheme = parsed.scheme.lower()
        host = (parsed.hostname or "").lower().rstrip(".")
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
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_MODEL_ID_LENGTH:
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

    def to_receipt(self, selected_model_id: Optional[str] = None) -> Dict[str, Any]:
        reported_model_id = _model_id(selected_model_id)
        if reported_model_id not in self.model_ids:
            reported_model_id = None
        if reported_model_id is None and self.model_ids:
            reported_model_id = self.model_ids[0]
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
            "identity": {
                "reported_model_id": reported_model_id,
                "reported_model_ids": list(self.model_ids[:64]),
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
    identity = receipt.get("identity") or {}
    if any(identity.get(key) is not None for key in ("artifact_publisher", "quantization", "artifact_sha256", "runtime_build_id", "runtime_bytes")):
        raise ValueError("observed runtime receipt contains an unverified identity claim")
    if identity.get("status") != "reported_only":
        raise ValueError("observed runtime identity must remain reported_only")
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
        self.max_response_bytes = _bounded_response_limit(max_response_bytes)
        self._last_probe: Optional[ObservedRuntimeProbe] = None

    @property
    def last_probe(self) -> Optional[ObservedRuntimeProbe]:
        return self._last_probe

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Tuple[bytes, str]:
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
            with _open_no_redirect(request, self.endpoint, self.timeout_seconds) as response:
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
            if exc.code in (301, 302, 303, 307, 308):
                raise ObservedRuntimeError("redirect_not_allowed")
            raise ObservedRuntimeError("http_error", status=exc.code)
        except (socket.timeout, TimeoutError):
            raise ObservedRuntimeError("timeout")
        except urllib_error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), (socket.timeout, TimeoutError)):
                raise ObservedRuntimeError("timeout")
            raise ObservedRuntimeError("connection_failed")
        except (OSError, ssl.SSLError):
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
        normalized_model = _model_id(model_id)
        if normalized_model is None:
            raise ObservedRuntimeError("model_not_available")
        if not isinstance(prompt, str) or not prompt:
            raise ObservedRuntimeError("endpoint_invalid")
        if len(prompt.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ObservedRuntimeError("request_too_large")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1 or max_tokens > 4096:
            raise ObservedRuntimeError("endpoint_invalid")
        body, content_type = self._request(
            "POST",
            "/v1/chat/completions",
            payload={
                "model": normalized_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0,
                "stream": bool(stream),
            },
        )
        if stream or "text/event-stream" in content_type.lower() or body.lstrip().startswith(b"data:"):
            text = _parse_sse(body)
        else:
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise ObservedRuntimeError("invalid_json")
            text = _extract_chat_text(payload)
            if not text:
                raise ObservedRuntimeError("empty_response")
        if len(text) > MAX_OUTPUT_CHARS:
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
    "DEFAULT_TIMEOUT_SECONDS",
    "FAILURE_CODES",
    "LocalEndpoint",
    "MAX_DISCOVERY_ENDPOINTS",
    "OPENAI_CHAT_COMPLETIONS_PROTOCOL",
    "OBSERVED_RUNTIME_CONTRACT_VERSION",
    "ObservedRuntimeError",
    "ObservedRuntimeProbe",
    "OpenAICompatibleClient",
    "ProviderProfile",
    "discover_local_runtimes",
    "parse_local_endpoint",
    "provider_profiles",
    "validate_observed_runtime_receipt",
]
