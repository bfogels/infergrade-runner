"""Support export helpers for local operator debugging."""

import os
from typing import Any, Dict, Optional

from infergrade import __version__
from infergrade.environment import capture_environment
from infergrade.pairing import load_runner_profile, runner_profile_path
from infergrade.progress import load_progress
from infergrade.utils import read_json, utcnow_iso, write_json


def build_support_export(run_dir: Optional[str] = None, execution_mode: Optional[str] = None) -> Dict[str, Any]:
    """Return a compact, secret-free support payload for a local runner session."""
    resolved_run_dir = os.path.abspath(os.path.expanduser(run_dir)) if run_dir else None
    progress = load_progress(resolved_run_dir) if resolved_run_dir else None
    detected_mode = (
        execution_mode
        or (progress or {}).get("request_context", {}).get("execution_mode")
        or "local_container"
    )
    payload = {
        "export_kind": "infergrade_runner_support_v1",
        "generated_at": utcnow_iso(),
        "runner_version": __version__,
        "secrets_excluded": True,
        "runner_profile_path": runner_profile_path(),
        "runner_profile": _sanitized_runner_profile(load_runner_profile()),
        "environment": capture_environment(detected_mode),
        "run_dir": resolved_run_dir,
        "progress": progress,
        "manifest": _read_json_if_present(resolved_run_dir, "manifest.json"),
        "summary": _read_json_if_present(resolved_run_dir, "summary.json"),
        "validation": _read_json_if_present(resolved_run_dir, "validation.json"),
        "captured_environment": _read_json_if_present(resolved_run_dir, "artifacts", "environment.json"),
        "artifact_receipt": _read_json_if_present(resolved_run_dir, "artifacts", "receipts", "quant_artifact_resolution.json"),
        "files_present": _support_file_presence(resolved_run_dir),
    }
    return payload


def write_support_export(output_path: str, run_dir: Optional[str] = None, execution_mode: Optional[str] = None) -> str:
    """Write a support export to disk and return the normalized path."""
    resolved_output = os.path.abspath(os.path.expanduser(output_path))
    write_json(resolved_output, build_support_export(run_dir=run_dir, execution_mode=execution_mode))
    return resolved_output


def _sanitized_runner_profile(profile: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not profile:
        return None
    sanitized = dict(profile)
    if sanitized.get("access_token"):
        sanitized["access_token_present"] = True
        sanitized["access_token_prefix"] = str(sanitized["access_token"])[:6]
        sanitized.pop("access_token", None)
    return sanitized


def _read_json_if_present(base_path: Optional[str], *parts: str) -> Optional[Dict[str, Any]]:
    if not base_path:
        return None
    path = os.path.join(base_path, *parts)
    if not os.path.exists(path):
        return None
    try:
        return read_json(path)
    except Exception as exc:
        return {"error": str(exc), "path": path}


def _support_file_presence(run_dir: Optional[str]) -> Dict[str, bool]:
    if not run_dir:
        return {}
    expected = {
        "progress_json": ("progress.json",),
        "manifest_json": ("manifest.json",),
        "summary_json": ("summary.json",),
        "validation_json": ("validation.json",),
        "captured_environment": ("artifacts", "environment.json"),
        "artifact_receipt": ("artifacts", "receipts", "quant_artifact_resolution.json"),
    }
    return {
        key: os.path.exists(os.path.join(run_dir, *relative_parts))
        for key, relative_parts in expected.items()
    }
