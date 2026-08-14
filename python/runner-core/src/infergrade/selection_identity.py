"""Reproducible selected-case identity digests."""

import hashlib
import json
from typing import Iterable


SORTED_JSON_STRING_ARRAY_SHA256_V1 = "sorted_json_string_array_sha256_v1"
SORTED_UTF8_NEWLINE_SHA256_V1 = "sorted_utf8_newline_sha256_v1"
SELECTION_DIGEST_ALGORITHMS = {
    SORTED_JSON_STRING_ARRAY_SHA256_V1,
    SORTED_UTF8_NEWLINE_SHA256_V1,
}


def selection_digest(case_ids: Iterable[object], algorithm: str) -> str:
    """Hash selected identities using an explicit, versioned serialization."""
    normalized = sorted(str(case_id) for case_id in case_ids)
    if algorithm == SORTED_JSON_STRING_ARRAY_SHA256_V1:
        payload = json.dumps(normalized, separators=(",", ":")).encode("utf-8")
    elif algorithm == SORTED_UTF8_NEWLINE_SHA256_V1:
        payload = "\n".join(normalized).encode("utf-8")
    else:
        raise ValueError("Unsupported selection digest algorithm: %s" % algorithm)
    return hashlib.sha256(payload).hexdigest()


def selection_digest_algorithm_for_execution_mode(execution_mode: str) -> str:
    """Return the existing digest serialization used by each execution path."""
    if execution_mode == "native":
        return SORTED_JSON_STRING_ARRAY_SHA256_V1
    if execution_mode == "container":
        return SORTED_UTF8_NEWLINE_SHA256_V1
    raise ValueError("Unsupported capability execution mode: %s" % execution_mode)
