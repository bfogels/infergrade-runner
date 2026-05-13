"""Load and normalize InferGrade run requests from multiple entrypoints."""

import argparse
import copy
import json
import os
import re
from typing import Any, Dict, List
from urllib import request as urllib_request

from infergrade.benchmark_catalog import normalize_request_selection
from infergrade.models import RunRequest


# Conservative regex for a docker-style image reference. Accepts the common
# forms we use (``ubuntu:latest``, ``registry/project/image:tag``,
# ``image@sha256:...``) while rejecting references that would be parsed as
# flags by ``docker run`` (leading ``-``) or that contain whitespace or
# other characters that have no business inside an image name.
_IMAGE_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,255}$")

# Runtime fields that must never be supplied by a remote hub. These steer the
# runner at specific local binaries, so letting a hub populate them would
# allow a compromised or malicious hub to run arbitrary executables on the
# runner via ``shutil.which`` + ``subprocess.run``. Operators can still set
# them via CLI flags, env vars, or a locally-authored request file.
_HUB_FORBIDDEN_RUNTIME_FIELDS = (
    "llama_cpp_cli_path",
    "llama_cpp_cli",
    "llama_cpp_server_path",
    "llama_cpp_server",
    "llama_cpp_perplexity_path",
    "llama_cpp_perplexity",
)


def sanitize_hub_supplied_payload(data: Any) -> Any:
    """Reject hub-originated run config fields that could hijack subprocess argv.

    Applied to payloads sourced from the hub (``request_from_url``,
    ``request_from_run_config_document``). Mutates a deep copy so callers can
    still hold the original response for logging. Raises ``ValueError`` when a
    forbidden field is present or when ``backend_image`` is not a plain image
    reference — failing loud surfaces hub-side bugs instead of silently
    dropping a field an operator might actually need.
    """
    if not isinstance(data, dict):
        return data
    sanitized = copy.deepcopy(data)
    nested = sanitized.get("request") if isinstance(sanitized.get("request"), dict) else sanitized
    runtime = nested.get("runtime")
    if isinstance(runtime, dict):
        for key in _HUB_FORBIDDEN_RUNTIME_FIELDS:
            value = runtime.get(key)
            if value:
                raise ValueError(
                    "Hub-supplied run config must not set runtime.%s; native binary "
                    "paths are operator-owned." % key
                )
        image = runtime.get("backend_image")
        if image is not None and image != "":
            if not isinstance(image, str) or not _IMAGE_REFERENCE_RE.match(image):
                raise ValueError(
                    "Hub-supplied backend_image %r is not a valid image reference." % image
                )
        selector = runtime.get("runtime_selector")
        if isinstance(selector, dict):
            binary = selector.get("binary")
            if isinstance(binary, dict) and binary.get("path"):
                raise ValueError(
                    "Hub-supplied run config must not set runtime.runtime_selector.binary.path; "
                    "native binary paths are operator-owned."
                )
    return sanitized


def _optional_import_yaml():
    """Import PyYAML lazily so JSON-only setups keep working without extras."""
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None
    return yaml


def request_from_cli(args: argparse.Namespace) -> RunRequest:
    """Build a run request from parsed CLI arguments."""
    request = RunRequest(
        model=args.model,
        backend=args.backend,
        tier=args.tier,
        capability_suite_ids=[],
        benchmark_group_ids=[],
        benchmark_check_ids=[],
        benchmark_shortcut_id=None,
        quant_artifact=args.quant_artifact,
        quant_artifact_sha256=args.quant_artifact_sha256,
        quant_artifact_filename=args.quant_artifact_filename,
        quant_artifact_revision=args.quant_artifact_revision,
        quant_artifact_cache_dir=args.artifact_cache_dir,
        backend_image=args.backend_image,
        llama_cpp_cli_path=getattr(args, "llama_cpp_cli_path", None),
        llama_cpp_server_path=getattr(args, "llama_cpp_server_path", None),
        llama_cpp_perplexity_path=getattr(args, "llama_cpp_perplexity_path", None),
        runtime_selector={},
        ontology_hints={},
        use_case=args.use_case,
        deployment_profiles=list(args.deployment_profiles or []),
        execution_mode=args.execution_mode,
        output_dir=args.output,
        resume=bool(getattr(args, "resume", False)),
        upload=args.upload,
        backend_flags=list(args.backend_flags or []),
        generation_preset=args.generation_preset,
        cloud_provider=args.cloud_provider,
        cloud_instance_type=args.cloud_instance_type,
        cost_source=args.cost_source,
        hourly_rate_usd=args.hourly_rate_usd,
        capability=args.capability,
        submitter=args.submitter,
        notes=args.notes,
        run_config_id=getattr(args, "run_config_id", None),
        run_config_name=getattr(args, "run_config_name", None),
        run_config_source=getattr(args, "run_config_source", None),
        simulate=not args.real_run,
    )
    return normalize_request_selection(request)


def request_from_file(path: str, simulate: bool = True) -> RunRequest:
    """Load a request document from disk and normalize it into a RunRequest."""
    suffix = os.path.splitext(path)[1].lower()
    with open(path, "r", encoding="utf-8") as handle:
        raw = handle.read()
    if suffix in (".json",):
        data = json.loads(raw)
    else:
        yaml = _optional_import_yaml()
        if yaml is None:
            raise ValueError("PyYAML is required to load YAML request files.")
        data = yaml.safe_load(raw)
    return request_from_dict(data, simulate=simulate, run_config_source=path)


def request_from_url(url: str, simulate: bool = True) -> RunRequest:
    """Load a JSON request document from a remote URL."""
    with urllib_request.urlopen(url) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    data = sanitize_hub_supplied_payload(data)
    return request_from_dict(data, simulate=simulate, run_config_source=url)


def request_from_dict(data: Dict[str, Any], simulate: bool = True, run_config_source: str = None) -> RunRequest:
    """Normalize raw request or run-config payloads into a RunRequest."""
    run_config = None
    if "request" in data and "run_config_id" in data:
        run_config = data
        data = data["request"]
    run = data.get("run", {})
    overrides = data.get("overrides", {})
    cost = data.get("cost", {})
    runtime = data.get("runtime", {})
    artifacts = data.get("artifacts", {})
    quantized_weights = artifacts.get("quantized_weights", {})
    metadata = data.get("metadata", {})
    ontology_hints = data.get("ontology_hints", {})
    quant_artifact = run.get("quant_artifact") or quantized_weights.get("uri")
    request = RunRequest(
        model=run["model"],
        backend=run["backend"],
        tier=run.get("tier", "canary"),
        capability_suite_ids=list(run.get("capability_suite_ids", [])),
        benchmark_group_ids=list(run.get("benchmark_group_ids", [])),
        benchmark_check_ids=list(run.get("benchmark_check_ids", [])),
        benchmark_shortcut_id=run.get("benchmark_shortcut_id"),
        quant_artifact=quant_artifact,
        quant_artifact_sha256=quantized_weights.get("sha256"),
        quant_artifact_filename=quantized_weights.get("filename"),
        quant_artifact_revision=quantized_weights.get("revision"),
        quant_artifact_cache_dir=runtime.get("artifact_cache_dir"),
        backend_image=runtime.get("backend_image"),
        llama_cpp_cli_path=runtime.get("llama_cpp_cli_path") or runtime.get("llama_cpp_cli"),
        llama_cpp_server_path=runtime.get("llama_cpp_server_path") or runtime.get("llama_cpp_server"),
        llama_cpp_perplexity_path=runtime.get("llama_cpp_perplexity_path") or runtime.get("llama_cpp_perplexity"),
        runtime_selector=dict(runtime.get("runtime_selector") or {}),
        ontology_hints=dict(ontology_hints or {}),
        use_case=run.get("use_case"),
        deployment_profiles=list(run.get("deployment_profiles", [])),
        execution_mode=run.get("execution_mode", "local_container"),
        output_dir=run.get("output_dir"),
        resume=bool(run.get("resume", False)),
        upload=bool(run.get("upload", False)),
        backend_flags=list(overrides.get("backend_flags", [])),
        generation_preset=overrides.get("generation_preset"),
        cloud_provider=run.get("cloud_provider"),
        cloud_instance_type=run.get("cloud_instance_type"),
        cost_source=cost.get("source"),
        hourly_rate_usd=cost.get("hourly_rate_usd"),
        capability=run.get("capability", "auto"),
        submitter=metadata.get("submitter"),
        notes=metadata.get("notes"),
        run_config_id=run_config.get("run_config_id") if run_config else None,
        run_config_name=run_config.get("name") if run_config else None,
        run_config_source=run_config_source,
        simulate=simulate,
    )
    return normalize_request_selection(request)


def request_to_dict(request: RunRequest) -> Dict[str, Any]:
    """Serialize a RunRequest into a stable dictionary for hashing and logging."""
    return {
        "model": request.model,
        "backend": request.backend,
        "tier": request.tier,
        "capability_suite_ids": request.capability_suite_ids,
        "benchmark_group_ids": request.benchmark_group_ids,
        "benchmark_check_ids": request.benchmark_check_ids,
        "benchmark_shortcut_id": request.benchmark_shortcut_id,
        "quant_artifact": request.quant_artifact,
        "quant_artifact_sha256": request.quant_artifact_sha256,
        "quant_artifact_filename": request.quant_artifact_filename,
        "quant_artifact_revision": request.quant_artifact_revision,
        "backend_image": request.backend_image,
        "llama_cpp_cli_path": request.llama_cpp_cli_path,
        "llama_cpp_server_path": request.llama_cpp_server_path,
        "llama_cpp_perplexity_path": request.llama_cpp_perplexity_path,
        "runtime_selector": request.runtime_selector,
        "quant_artifact_cache_dir": request.quant_artifact_cache_dir,
        "ontology_hints": request.ontology_hints,
        "use_case": request.use_case,
        "deployment_profiles": request.deployment_profiles,
        "execution_mode": request.execution_mode,
        "output_dir": request.output_dir,
        "resume": request.resume,
        "upload": request.upload,
        "backend_flags": request.backend_flags,
        "generation_preset": request.generation_preset,
        "cloud_provider": request.cloud_provider,
        "cloud_instance_type": request.cloud_instance_type,
        "cost_source": request.cost_source,
        "hourly_rate_usd": request.hourly_rate_usd,
        "capability": request.capability,
        "submitter": request.submitter,
        "notes": request.notes,
        "run_config_id": request.run_config_id,
        "run_config_name": request.run_config_name,
        "run_config_source": request.run_config_source,
        "simulate": request.simulate,
    }
