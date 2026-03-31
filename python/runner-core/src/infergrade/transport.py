"""HTTP transport helpers for talking to a InferGrade API."""

import json
import os
from typing import Any, Dict, Optional, Tuple
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from infergrade.analysis import summarize_bundle
from infergrade.run_configs import build_run_config_document
from infergrade.utils import env_value, read_json


def _resolve_api_token(api_token: str = None) -> str:
    """Return the explicit API token or fall back to the environment."""
    return (
        api_token
        or env_value("INFERGRADE_HUB_TOKEN", "QUANTBENCH_HUB_TOKEN")
        or env_value("INFERGRADE_API_TOKEN", "QUANTBENCH_API_TOKEN")
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
    url = api_url.rstrip("/") + path
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
    return status, (json.loads(text) if text else {})


def bundle_payload(bundle_dir: str) -> Dict[str, Any]:
    """Assemble a bundle directory into the API upload payload shape."""
    manifest = read_json(os.path.join(bundle_dir, "manifest.json"))
    validation_path = os.path.join(bundle_dir, "validation.json")
    summary_path = os.path.join(bundle_dir, "summary.json")
    results_dir = os.path.join(bundle_dir, "results")
    results = []
    for filename in sorted(os.listdir(results_dir)):
        if filename.endswith(".json"):
            results.append(read_json(os.path.join(results_dir, filename)))
    payload = {
        "manifest": manifest,
        "results": results,
    }
    if os.path.exists(validation_path):
        payload["validation"] = read_json(validation_path)
    if os.path.exists(summary_path):
        payload["summary"] = read_json(summary_path)
    else:
        payload["summary"] = summarize_bundle(bundle_dir)
    return payload


def upload_bundle(bundle_dir: str, api_url: str, api_token: str = None) -> Dict[str, Any]:
    """Upload a local bundle to the hosted catalog."""
    _, payload = _json_request(api_url, "/bundles", method="POST", payload=bundle_payload(bundle_dir), api_token=api_token)
    return payload


def upload_run_bundle(bundle_dir: str, api_url: str, run_id: str, run_token: str = None, api_token: str = None) -> Dict[str, Any]:
    """Upload a local bundle through the run-scoped upload route."""
    _, payload = _json_request(
        api_url,
        "/v1/runs/%s/bundle" % run_id,
        method="POST",
        payload=bundle_payload(bundle_dir),
        api_token=api_token,
        run_token=run_token,
    )
    return payload


def fetch_run_config(api_url: str, run_config_id: str, api_token: str = None) -> Dict[str, Any]:
    """Fetch one server-issued run config document."""
    _, payload = _json_request(api_url, "/run-configs/" + run_config_id, api_token=api_token)
    return payload


def list_run_configs(api_url: str, api_token: str = None) -> Dict[str, Any]:
    """List server-issued run configs from the hosted catalog."""
    _, payload = _json_request(api_url, "/run-configs", api_token=api_token)
    return payload


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
    label: str = None,
    runner_kind: str = None,
    hostname: str = None,
    provider_id: str = None,
    instance_type_id: str = None,
    capabilities: Dict[str, Any] = None,
    version: str = None,
) -> Dict[str, Any]:
    """Register a long-lived runner with the Hub."""
    _, payload = _json_request(
        api_url,
        "/v1/runners/register",
        method="POST",
        payload={
            "runner_id": runner_id,
            "execution_modes": list(execution_modes or []),
            "label": label,
            "runner_kind": runner_kind,
            "hostname": hostname,
            "provider_id": provider_id,
            "instance_type_id": instance_type_id,
            "capabilities": capabilities or {},
            "version": version,
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
        },
        api_token=api_token,
    )
    return payload
