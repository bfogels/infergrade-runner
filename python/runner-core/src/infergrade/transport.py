"""HTTP transport helpers for talking to an InferGrade Hub API."""

import hashlib
import ipaddress
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from infergrade.pairing import load_runner_profile
from infergrade.run_configs import build_run_config_document
from infergrade.utils import env_value, read_json


class InsecureApiUrlError(ValueError):
    """Raised when a Hub API URL would send credentials over cleartext."""


class RunnerTokenInvalidError(RuntimeError):
    """Raised when Hub explicitly revokes or expires a paired runner token."""


RUNNER_TOKEN_INVALID_MESSAGE = "Runner token revoked or expired. Run 'infergrade pair' to re-pair."
RUNTIME_RECEIPT_ARTIFACT_PATH = "artifacts/receipts/runtime_receipt.json"
RUNTIME_RECEIPT_ARTIFACT_MAX_BYTES = 4 * 1024 * 1024


def _is_local_http_api_host(host: str) -> bool:
    """Return true when cleartext HTTP is limited to the local machine."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def require_secure_api_url(api_url: str) -> str:
    """Return a normalized API URL or refuse cleartext non-local Hub URLs."""
    resolved = str(api_url or "").strip()
    parsed = urllib_parse.urlsplit(resolved)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if scheme == "https" and host:
        return resolved
    if scheme == "http" and _is_local_http_api_host(host):
        return resolved
    raise InsecureApiUrlError(
        "Refusing Hub API URL %r. Use https:// for hosted Hub URLs; "
        "http:// is allowed only for localhost or loopback IP addresses." % resolved
    )


def _resolve_api_token(api_token: str = None) -> str:
    """Return the explicit API token or fall back to the environment."""
    profile = load_runner_profile() or {}
    return (
        api_token
        or env_value("INFERGRADE_HUB_TOKEN")
        or env_value("INFERGRADE_API_TOKEN")
        or profile.get("access_token")
        or ""
    ).strip()


def _resolve_run_token(run_token: str = None) -> str:
    """Return the explicit run token or fall back to the environment."""
    return (run_token or env_value("INFERGRADE_RUN_TOKEN") or "").strip()


def _request_headers(api_token: str = None, run_token: str = None, content_type: str = None) -> Dict[str, str]:
    """Build request headers shared by runner-to-API calls."""
    headers: Dict[str, str] = {}
    resolved_token = _resolve_run_token(run_token) or _resolve_api_token(api_token)
    if content_type:
        headers["Content-Type"] = content_type
    if resolved_token:
        headers["Authorization"] = "Bearer %s" % resolved_token
    return headers


def _json_request(
    api_url: str,
    path: str,
    method: str = "GET",
    payload: Dict[str, Any] = None,
    params: Dict[str, Any] = None,
    api_token: str = None,
    run_token: str = None,
    idempotency_key: str = None,
) -> Tuple[int, Dict[str, Any]]:
    """Send a JSON request to the InferGrade API and return status plus body."""
    url = require_secure_api_url(api_url).rstrip("/") + path
    if params:
        query = urllib_parse.urlencode({key: value for key, value in params.items() if value is not None})
        if query:
            url += ("&" if "?" in url else "?") + query
    body = None
    headers = _request_headers(api_token=api_token, run_token=run_token, content_type="application/json" if payload is not None else None)
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urllib_request.urlopen(req) as response:
            status = response.getcode()
            text = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        status = exc.code
        text = exc.read().decode("utf-8")
    try:
        parsed = json.loads(text) if text else {}
    except ValueError:
        parsed = {"error": text[:200] if text else ""}
    if status == 401 and _api_error_code(parsed) in {"runner_token_revoked", "runner_token_expired"}:
        raise RunnerTokenInvalidError(RUNNER_TOKEN_INVALID_MESSAGE)
    return status, parsed


def bundle_payload(bundle_dir: str) -> Dict[str, Any]:
    """Assemble a bundle directory into the API upload payload shape."""
    manifest = read_json(os.path.join(bundle_dir, "manifest.json"))
    validation_path = os.path.join(bundle_dir, "validation.json")
    summary_path = os.path.join(bundle_dir, "summary.json")
    validation = read_json(validation_path) if os.path.exists(validation_path) else None
    summary = read_json(summary_path) if os.path.exists(summary_path) else None
    results = []
    for relative_path in _manifest_result_paths(manifest, summary):
        results.append(read_json(os.path.join(bundle_dir, relative_path)))
    payload = {
        "manifest": manifest,
        "results": results,
    }
    if validation is not None:
        payload["validation"] = validation
    payload["summary"] = summary or _summarize_payload_results(manifest, validation, results)
    receipt_path = (manifest.get("files") or {}).get("runtime_receipt")
    if receipt_path is not None:
        if receipt_path != RUNTIME_RECEIPT_ARTIFACT_PATH:
            raise ValueError(
                "manifest files.runtime_receipt must be %s" % RUNTIME_RECEIPT_ARTIFACT_PATH
            )
        receipt = read_json(os.path.join(bundle_dir, *RUNTIME_RECEIPT_ARTIFACT_PATH.split("/")))
        _validate_runtime_receipt_artifact_for_upload(receipt)
        payload["runtime_receipt_artifact"] = receipt
    return payload


def _validate_runtime_receipt_artifact_for_upload(receipt: Any) -> None:
    """Refuse unbounded or internally inconsistent full receipts before upload."""
    if not isinstance(receipt, dict):
        raise ValueError("runtime receipt artifact must be an object")
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > RUNTIME_RECEIPT_ARTIFACT_MAX_BYTES:
        raise ValueError("runtime receipt artifact exceeds the 4 MiB upload limit")
    files = receipt.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 4096:
        raise ValueError("runtime receipt artifact files must contain between 1 and 4096 records")
    if receipt.get("content_manifest_file_count") != len(files):
        raise ValueError("runtime receipt artifact file count does not match files")
    manifest_digest = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if receipt.get("content_manifest_sha256") != manifest_digest:
        raise ValueError("runtime receipt artifact manifest digest does not match files")


def _manifest_result_paths(manifest: Dict[str, Any], summary: Optional[Dict[str, Any]] = None) -> List[str]:
    """Return manifest-declared result files, rejecting unsafe paths."""
    files = manifest.get("files") or {}
    result_paths = files.get("results") if isinstance(files, dict) else None
    if result_paths is None:
        legacy_stems = (summary or {}).get("deployment_profiles") or (summary or {}).get("result_ids") or []
        if not isinstance(legacy_stems, list) or not legacy_stems:
            raise ValueError("manifest files.results is required when summary deployment/result ids are unavailable")
        result_paths = ["results/%s.json" % item for item in legacy_stems]
    if not isinstance(result_paths, list):
        raise ValueError("manifest files.results must be a list")
    normalized = []
    for raw_path in result_paths:
        relative_path = str(raw_path or "").strip()
        if not relative_path:
            continue
        if os.path.isabs(relative_path):
            raise ValueError("manifest result path must be relative: %s" % relative_path)
        clean_path = os.path.normpath(relative_path)
        if clean_path.startswith("..%s" % os.sep) or clean_path == "..":
            raise ValueError("manifest result path escapes bundle directory: %s" % relative_path)
        parts = clean_path.split(os.sep)
        if len(parts) != 2 or parts[0] != "results" or not parts[1].endswith(".json"):
            raise ValueError("manifest result path must be results/<name>.json: %s" % relative_path)
        normalized.append(clean_path)
    return normalized


def _summarize_payload_results(
    manifest: Dict[str, Any],
    validation: Optional[Dict[str, Any]],
    results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build an upload summary from the selected payload results only."""
    return {
        "bundle_id": manifest["bundle_id"],
        "result_count": len(results),
        "result_ids": [item["result_id"] for item in results],
        "benchmark_subject_ids": sorted(
            {
                item.get("ontology", {}).get("benchmark_subject", {}).get("subject_id")
                for item in results
                if item.get("ontology", {}).get("benchmark_subject", {}).get("subject_id")
            }
        ),
        "checkpoints": sorted(
            {
                item.get("ontology", {}).get("checkpoint", {}).get("checkpoint_name")
                for item in results
                if item.get("ontology", {}).get("checkpoint", {}).get("checkpoint_name")
            }
        ),
        "model_families": sorted(
            {
                item.get("ontology", {}).get("model_family", {}).get("family_name")
                for item in results
                if item.get("ontology", {}).get("model_family", {}).get("family_name")
            }
        ),
        "deployment_profiles": [item.get("deployment", {}).get("deployment_profile_id") for item in results],
        "use_cases": sorted(
            {
                item.get("capability", {}).get("use_case")
                for item in results
                if item.get("capability", {}).get("use_case")
            }
        ),
        "verification_levels": sorted(
            {
                item.get("verification", {}).get("verification_level")
                for item in results
                if item.get("verification", {}).get("verification_level")
            }
        ),
        "comparison_grade_candidates": sorted(
            {
                item.get("verification", {}).get("local_comparison_grade_candidate")
                for item in results
                if item.get("verification", {}).get("local_comparison_grade_candidate")
            }
        ),
        "created_at": manifest.get("created_at"),
        "validation": validation,
        "results": [_brief_payload_result(item) for item in results],
    }


def _brief_payload_result(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "result_id": result.get("result_id"),
        "benchmark_subject_id": result.get("ontology", {}).get("benchmark_subject", {}).get("subject_id"),
        "checkpoint_name": result.get("ontology", {}).get("checkpoint", {}).get("checkpoint_name"),
        "model_family": result.get("ontology", {}).get("model_family", {}).get("family_name"),
        "quantization_label": result.get("ontology", {}).get("quantization", {}).get("quantization_label"),
        "backend_engine": result.get("ontology", {}).get("runtime_binding", {}).get("backend_engine"),
        "deployment_profile_id": result.get("deployment", {}).get("deployment_profile_id"),
        "use_case": result.get("capability", {}).get("use_case"),
        "verification_level": result.get("verification", {}).get("verification_level"),
        "comparison_grade_candidate": result.get("verification", {}).get("local_comparison_grade_candidate"),
        "ttft_p50_ms": result.get("deployment", {}).get("ttft_p50_ms"),
        "decode_tokens_per_second_p50": result.get("deployment", {}).get("decode_tokens_per_second_p50"),
        "capability_score": result.get("capability", {}).get("capability_score"),
        "benchmark_job_cost_usd": result.get("cost", {}).get("benchmark_job_cost_usd"),
    }


def upload_bundle(bundle_dir: str, api_url: str, api_token: str = None) -> Dict[str, Any]:
    """Upload a local bundle to the hosted catalog."""
    status, payload = _json_request(api_url, "/bundles", method="POST", payload=bundle_payload(bundle_dir), api_token=api_token)
    if status >= 400:
        detail = payload.get("detail") or payload.get("error") or ""
        if isinstance(detail, dict):
            detail = detail.get("message") or str(detail)
        raise RuntimeError("bundle upload failed (HTTP %d): %s" % (status, detail or "no detail"))
    return payload


def upload_run_bundle(bundle_dir: str, api_url: str, run_id: str, run_token: str = None, api_token: str = None) -> Dict[str, Any]:
    """Upload a local bundle through the run-scoped upload route."""
    status, payload = _json_request(
        api_url,
        "/v1/runs/%s/bundle" % run_id,
        method="POST",
        payload=bundle_payload(bundle_dir),
        api_token=api_token,
        run_token=run_token,
    )
    if status >= 400:
        detail = payload.get("detail") or payload.get("error") or ""
        if isinstance(detail, dict):
            detail = detail.get("message") or str(detail)
        raise RuntimeError("bundle upload failed (HTTP %d): %s" % (status, detail or "no detail"))
    return payload


def fetch_run_config(api_url: str, run_config_id: str, api_token: str = None) -> Dict[str, Any]:
    """Fetch one server-issued run config document."""
    _, payload = _json_request(api_url, "/run-configs/" + run_config_id, api_token=api_token)
    return payload


def list_run_configs(api_url: str, api_token: str = None) -> Dict[str, Any]:
    """List server-issued run configs from the hosted catalog."""
    _, payload = _json_request(api_url, "/run-configs", api_token=api_token)
    return payload


def fetch_agent_work_plan(api_url: str, api_token: str = None) -> Dict[str, Any]:
    """Fetch the immutable work plan attached to a paired benchmark agent."""
    status, payload = _json_request(api_url, "/v1/agent/work-plan", api_token=api_token)
    if status >= 400:
        raise RuntimeError("agent work-plan fetch failed (HTTP %d): %s" % (status, _api_error_detail(payload) or "no detail"))
    return payload


def materialize_agent_work_candidate(
    api_url: str,
    *,
    candidate_id: str,
    grant_id: str = None,
    api_token: str = None,
    max_attempts: int = 4,
) -> Dict[str, Any]:
    """Materialize one immutable candidate, retrying transient Hub contention."""
    idempotency_key = "agent-work-%s-%s" % ((grant_id or "grant")[-12:], uuid.uuid4().hex)
    attempts = max(1, int(max_attempts))
    for attempt in range(attempts):
        status, payload = _json_request(
            api_url,
            "/v1/agent/work-plan/%s/materialize" % urllib_parse.quote(candidate_id, safe=""),
            method="POST",
            payload={},
            api_token=api_token,
            idempotency_key=idempotency_key,
        )
        if status < 400:
            return payload
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        if status == 503 and error.get("retryable") is True and attempt + 1 < attempts:
            time.sleep(0.25 * (2 ** attempt))
            continue
        raise RuntimeError(
            "agent work materialization failed (HTTP %d%s): %s"
            % (
                status,
                " %s" % error.get("code") if error.get("code") else "",
                _api_error_detail(payload) or "no detail",
            )
        )
    raise RuntimeError("agent work materialization retry budget exhausted")


def publish_run_config(
    api_url: str,
    request_payload: Dict[str, Any],
    name: str,
    description: str = None,
    created_by: str = None,
    api_token: str = None,
) -> Dict[str, Any]:
    """Publish a run config derived from a local request payload."""
    payload = build_run_config_document(
        request_payload=request_payload,
        name=name,
        description=description,
        created_by=created_by,
    )
    _, response = _json_request(api_url, "/run-configs", method="POST", payload=payload, api_token=api_token)
    return response


def claim_run_job(
    api_url: str,
    worker_id: str,
    execution_mode: str,
    api_token: str = None,
    run_token: str = None,
    run_id: str = None,
    run_config_id: str = None,
    provider_id: str = None,
    instance_type_id: str = None,
    hostname: str = None,
) -> Dict[str, Any]:
    """Claim the next awaiting run job for a worker."""
    _, payload = _json_request(
        api_url,
        "/v1/runs/claim",
        method="POST",
        payload={
            "worker_id": worker_id,
            "execution_mode": execution_mode,
            "run_id": run_id,
            "run_config_id": run_config_id,
            "provider_id": provider_id,
            "instance_type_id": instance_type_id,
            "hostname": hostname,
        },
        api_token=api_token,
        run_token=run_token,
    )
    return payload


def redeem_runner_pairing(
    api_url: str,
    pair_code: str,
    label: str = None,
    hostname: str = None,
    execution_mode: str = None,
    environment: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Redeem a one-time runner pairing code for a long-lived runner token."""
    status, payload = _json_request(
        api_url,
        "/v1/runner-pairings/redeem",
        method="POST",
        payload={
            "pair_code": pair_code,
            "label": label,
            "hostname": hostname,
            "preferred_execution_mode": execution_mode,
            "environment": environment or {},
        },
    )
    if status >= 400:
        detail = _api_error_detail(payload)
        code = _api_error_code(payload)
        code_text = " (%s)" % code if code else ""
        raise RuntimeError("runner pairing failed%s: HTTP %d: %s" % (code_text, status, detail or "no detail"))
    return payload


def _api_error_detail(payload: Dict[str, Any]) -> str:
    """Extract a useful API error message from common Hub error envelopes."""
    detail = payload.get("detail")
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        return "; ".join(str(item.get("msg") or item.get("message") or item) if isinstance(item, dict) else str(item) for item in detail)
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("detail") or error)
    if isinstance(error, str):
        return error
    return ""


def _api_error_code(payload: Dict[str, Any]) -> str:
    """Extract a stable API error code from common Hub error envelopes."""
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("code") or "").strip()
    if isinstance(error, str):
        return error.strip()
    return ""


def heartbeat_run_job(
    api_url: str,
    run_id: str,
    worker_id: str,
    stage: str = None,
    detail: str = None,
    message: str = None,
    progress_percent: float = None,
    api_token: str = None,
    run_token: str = None,
) -> Dict[str, Any]:
    """Send a worker heartbeat for a running job."""
    _, payload = _json_request(
        api_url,
        "/v1/runs/%s/heartbeat" % run_id,
        method="POST",
        payload={
            "worker_id": worker_id,
            "stage": stage,
            "detail": detail,
            "message": message,
            "progress_percent": progress_percent,
        },
        api_token=api_token,
        run_token=run_token,
    )
    return payload


def complete_run_job(
    api_url: str,
    run_id: str,
    worker_id: str,
    bundle_id: str,
    upload: Dict[str, Any] = None,
    api_token: str = None,
    run_token: str = None,
) -> Dict[str, Any]:
    """Mark a run job as completed."""
    _, payload = _json_request(
        api_url,
        "/v1/runs/%s/complete" % run_id,
        method="POST",
        payload={
            "worker_id": worker_id,
            "bundle_id": bundle_id,
            "upload": upload,
        },
        api_token=api_token,
        run_token=run_token,
    )
    return payload


def fail_run_job(
    api_url: str,
    run_id: str,
    worker_id: str,
    message: str,
    error_code: str = None,
    recovery: Any = None,
    details: Dict[str, Any] = None,
    api_token: str = None,
    run_token: str = None,
) -> Dict[str, Any]:
    """Mark a run job as failed."""
    _, payload = _json_request(
        api_url,
        "/v1/runs/%s/fail" % run_id,
        method="POST",
        payload={
            "worker_id": worker_id,
            "message": message,
            "error_code": error_code,
            "recovery": recovery,
            "details": details,
        },
        api_token=api_token,
        run_token=run_token,
    )
    return payload


def get_run_job(api_url: str, run_id: str, api_token: str = None) -> Dict[str, Any]:
    """Fetch one persisted run job."""
    _, payload = _json_request(api_url, "/v1/runs/%s" % run_id, api_token=api_token)
    return payload


def list_run_jobs(api_url: str, api_token: str = None, **params: Any) -> Dict[str, Any]:
    """List run jobs from the API."""
    _, payload = _json_request(api_url, "/v1/runs", params=params, api_token=api_token)
    return payload


def register_runner(
    api_url: str,
    runner_id: str,
    execution_modes: Any,
    api_token: str = None,
    status: str = None,
    label: str = None,
    runner_kind: str = None,
    hostname: str = None,
    provider_id: str = None,
    instance_type_id: str = None,
    capabilities: Dict[str, Any] = None,
    version: str = None,
    environment: Dict[str, Any] = None,
    contract: Dict[str, Any] = None,
    diagnostics: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Register a long-lived runner with the Hub."""
    _, payload = _json_request(
        api_url,
        "/v1/runners/register",
        method="POST",
        payload={
            "runner_id": runner_id,
            "execution_modes": list(execution_modes or []),
            "status": status,
            "label": label,
            "runner_kind": runner_kind,
            "hostname": hostname,
            "provider_id": provider_id,
            "instance_type_id": instance_type_id,
            "capabilities": capabilities or {},
            "version": version,
            "environment": environment or {},
            "contract": contract or {},
            "diagnostics": diagnostics or {},
        },
        api_token=api_token,
    )
    return payload


def heartbeat_runner(
    api_url: str,
    runner_id: str,
    api_token: str = None,
    status: str = None,
    current_run_id: str = None,
    hostname: str = None,
    provider_id: str = None,
    instance_type_id: str = None,
    metadata: Dict[str, Any] = None,
    environment: Dict[str, Any] = None,
    contract: Dict[str, Any] = None,
    diagnostics: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Send a runner readiness heartbeat to the Hub."""
    _, payload = _json_request(
        api_url,
        "/v1/runners/%s/heartbeat" % runner_id,
        method="POST",
        payload={
            "status": status,
            "current_run_id": current_run_id,
            "hostname": hostname,
            "provider_id": provider_id,
            "instance_type_id": instance_type_id,
            "metadata": metadata or {},
            "environment": environment or {},
            "contract": contract or {},
            "diagnostics": diagnostics or {},
        },
        api_token=api_token,
    )
    return payload
