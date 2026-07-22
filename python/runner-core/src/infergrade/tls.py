"""Verified TLS context selection for portable Runner Python environments."""

import os
import ssl
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import parse as urllib_parse


def _existing_file(value: Any) -> Optional[str]:
    path = str(value or "").strip()
    return path if path and Path(path).expanduser().is_file() else None


def tls_trust_configuration() -> Dict[str, Optional[str]]:
    """Describe the CA source without ever weakening certificate validation."""
    configured = str(os.environ.get("SSL_CERT_FILE") or "").strip()
    if configured:
        resolved = _existing_file(configured)
        return {
            "source": "ssl_cert_file" if resolved else "invalid_ssl_cert_file",
            "cafile": resolved,
        }

    defaults = ssl.get_default_verify_paths()
    default_cafile = _existing_file(defaults.cafile)
    if default_cafile:
        return {"source": "python_default", "cafile": default_cafile}

    try:
        import certifi  # type: ignore
    except ImportError:
        certifi = None
    certifi_cafile = _existing_file(certifi.where()) if certifi is not None else None
    if certifi_cafile:
        return {"source": "certifi", "cafile": certifi_cafile}

    system_cafile = _existing_file("/etc/ssl/cert.pem")
    if system_cafile:
        return {"source": "system_fallback", "cafile": system_cafile}
    return {"source": "python_default_unresolved", "cafile": None}


def verified_https_context(url: str):
    """Return an explicit verified context for HTTPS, or None for local HTTP."""
    if urllib_parse.urlsplit(str(url or "")).scheme.lower() != "https":
        return None
    trust = tls_trust_configuration()
    if trust["source"] == "invalid_ssl_cert_file":
        raise RuntimeError(
            "SSL_CERT_FILE points to a missing CA bundle. Remove it or set it to a readable PEM certificate bundle."
        )
    cafile = trust.get("cafile")
    return ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
