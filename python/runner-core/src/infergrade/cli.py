"""Command-line entrypoints for running and inspecting InferGrade bundles."""

import argparse
import json
import sys
from typing import Optional
from urllib.error import URLError

from infergrade import __version__
from infergrade.analysis import recommend, summarize_bundle
from infergrade.doctor import run_doctor
from infergrade.profiles import CAPABILITY_SUITES, DEPLOYMENT_PROFILES
from infergrade.request import request_from_cli, request_from_file
from infergrade.run_configs import request_from_run_config_document
from infergrade.runner import run_infergrade
from infergrade.templates import render_run_config_template, render_run_request_template
from infergrade.transport import fetch_run_config, list_run_configs, publish_run_config, upload_bundle
from infergrade.utils import write_text
from infergrade.validators import validate_bundle
from infergrade.worker import run_worker_loop, run_worker_once


def _add_api_token_argument(parser: argparse.ArgumentParser) -> None:
    """Add the shared hosted-API token flag to a parser."""
    parser.add_argument(
        "--api-token",
        help="Optional Hub/API token. Falls back to INFERGRADE_HUB_TOKEN, then INFERGRADE_API_TOKEN if unset.",
    )


def _add_run_request_arguments(parser: argparse.ArgumentParser) -> None:
    """Attach the common run-request arguments used by multiple commands."""
    parser.add_argument("--request-file")
    parser.add_argument("--model")
    parser.add_argument("--backend")
    parser.add_argument("--tier")
    parser.add_argument("--quant-artifact")
    parser.add_argument("--quant-artifact-sha256")
    parser.add_argument("--quant-artifact-filename")
    parser.add_argument("--quant-artifact-revision")
    parser.add_argument("--use-case")
    parser.add_argument("--deployment-profile", dest="deployment_profiles", action="append")
    parser.add_argument("--execution-mode", default="local_container")
    parser.add_argument("--output")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--backend-flags", action="append")
    parser.add_argument("--generation-preset")
    parser.add_argument("--cloud-provider")
    parser.add_argument("--cloud-instance-type")
    parser.add_argument("--backend-image")
    parser.add_argument("--artifact-cache-dir")
    parser.add_argument("--cost-source")
    parser.add_argument("--hourly-rate-usd", type=float)
    parser.add_argument("--capability", default="auto")
    parser.add_argument("--submitter")
    parser.add_argument("--notes")
    parser.add_argument(
        "--real-run",
        action="store_true",
        help="Attempt real backend execution. Initial implementation still focuses on simulated mode.",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level InferGrade CLI parser."""
    parser = argparse.ArgumentParser(prog="infergrade")
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run or simulate an InferGrade bundle.")
    _add_run_request_arguments(run_parser)

    doctor_parser = subparsers.add_parser("doctor", help="Check whether the current machine is ready for a InferGrade run.")
    _add_run_request_arguments(doctor_parser)
    doctor_parser.add_argument("--api-url")
    doctor_parser.add_argument("--run-config-id")
    _add_api_token_argument(doctor_parser)

    validate_parser = subparsers.add_parser("validate-bundle", help="Validate an existing bundle.")
    validate_parser.add_argument("path")

    inspect_parser = subparsers.add_parser("inspect-bundle", help="Summarize a bundle.")
    inspect_parser.add_argument("path")

    recommend_parser = subparsers.add_parser("recommend", help="Compute local frontier-style recommendations.")
    recommend_parser.add_argument("paths", nargs="+")
    recommend_parser.add_argument("--use-case")
    recommend_parser.add_argument("--deployment-profile")
    recommend_parser.add_argument("--max-vram-gb", type=float)
    recommend_parser.add_argument("--verification-level", action="append")

    init_parser = subparsers.add_parser("init-request", help="Generate a starter run request template.")
    init_parser.add_argument("--format", choices=("yaml", "json"), default="yaml")
    init_parser.add_argument("--output")
    init_parser.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    init_parser.add_argument("--backend", default="llama.cpp")
    init_parser.add_argument("--tier", default="canary")
    init_parser.add_argument("--use-case")

    upload_parser = subparsers.add_parser("upload-bundle", help="Upload a local bundle to a InferGrade API.")
    upload_parser.add_argument("path")
    upload_parser.add_argument("--api-url", required=True)
    _add_api_token_argument(upload_parser)

    init_config_parser = subparsers.add_parser("init-run-config", help="Generate a starter server-style run config document.")
    init_config_parser.add_argument("--format", choices=("yaml", "json"), default="json")
    init_config_parser.add_argument("--output")
    init_config_parser.add_argument("--name", default="General assistant canary run")
    init_config_parser.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    init_config_parser.add_argument("--backend", default="llama.cpp")
    init_config_parser.add_argument("--tier", default="canary")
    init_config_parser.add_argument("--use-case")

    list_configs_parser = subparsers.add_parser("list-run-configs", help="List server-side run configs.")
    list_configs_parser.add_argument("--api-url", required=True)
    _add_api_token_argument(list_configs_parser)

    fetch_config_parser = subparsers.add_parser("fetch-run-config", help="Fetch a run config from the API.")
    fetch_config_parser.add_argument("--api-url", required=True)
    fetch_config_parser.add_argument("--run-config-id", required=True)
    fetch_config_parser.add_argument("--output")
    _add_api_token_argument(fetch_config_parser)

    publish_config_parser = subparsers.add_parser("publish-run-config", help="Publish a run config to the API.")
    _add_run_request_arguments(publish_config_parser)
    publish_config_parser.add_argument("--api-url", required=True)
    publish_config_parser.add_argument("--name", required=True)
    publish_config_parser.add_argument("--description")
    publish_config_parser.add_argument("--created-by")
    _add_api_token_argument(publish_config_parser)

    run_config_parser = subparsers.add_parser("run-config", help="Fetch a run config from the API and execute it.")
    run_config_parser.add_argument("--api-url", required=True)
    run_config_parser.add_argument("--run-config-id", required=True)
    run_config_parser.add_argument("--output")
    run_config_parser.add_argument(
        "--real-run",
        action="store_true",
        help="Attempt real backend execution. Initial implementation still focuses on simulated mode.",
    )
    run_config_parser.add_argument("--resume", action="store_true")
    _add_api_token_argument(run_config_parser)

    run_job_parser = subparsers.add_parser("run-job", help="Claim and execute one Hub-backed run job with automatic upload.")
    run_job_parser.add_argument("--api-url", required=True)
    run_job_parser.add_argument("--run-id")
    run_job_parser.add_argument("--run-config-id")
    run_job_parser.add_argument("--execution-mode", choices=("local_container", "cloud_container"), default="local_container")
    run_job_parser.add_argument("--worker-id")
    run_job_parser.add_argument("--provider-id")
    run_job_parser.add_argument("--instance-type-id")
    run_job_parser.add_argument("--hostname")
    run_job_parser.add_argument(
        "--simulate",
        action="store_true",
        help="Use simulated execution for this run job instead of real execution.",
    )
    _add_api_token_argument(run_job_parser)

    worker_parser = subparsers.add_parser("worker", help="Claim and execute API-backed run jobs.")
    worker_parser.add_argument("--api-url", required=True)
    worker_parser.add_argument("--execution-mode", choices=("local_container", "cloud_container"), default="local_container")
    worker_parser.add_argument("--worker-id")
    worker_parser.add_argument("--run-id")
    worker_parser.add_argument("--run-config-id")
    worker_parser.add_argument("--provider-id")
    worker_parser.add_argument("--instance-type-id")
    worker_parser.add_argument("--hostname")
    worker_parser.add_argument("--poll-interval-seconds", type=float, default=10.0)
    worker_parser.add_argument("--max-jobs", type=int)
    worker_parser.add_argument("--once", action="store_true")
    worker_parser.add_argument(
        "--simulate",
        action="store_true",
        help="Use simulated execution when the worker runs claimed jobs.",
    )
    _add_api_token_argument(worker_parser)

    profiles_parser = subparsers.add_parser("show-profiles", help="Show deployment profiles.")
    profiles_parser.set_defaults(_profiles=True)

    capabilities_parser = subparsers.add_parser("show-capabilities", help="Show capability suites.")
    capabilities_parser.set_defaults(_capabilities=True)

    return parser


def _request_from_args(args: argparse.Namespace):
    """Resolve a RunRequest from either a request file or direct CLI flags."""
    if args.request_file:
        return request_from_file(args.request_file, simulate=not args.real_run)
    missing = [name for name in ("model", "backend", "tier") if getattr(args, name) is None]
    if missing:
        raise SystemExit("Missing required arguments for run: %s" % ", ".join(missing))
    return request_from_cli(args)


def _request_for_doctor(args: argparse.Namespace):
    """Resolve the optional request context used by the doctor command."""
    if args.run_config_id:
        if not args.api_url:
            raise SystemExit("--api-url is required when --run-config-id is provided to doctor.")
        try:
            payload = fetch_run_config(args.api_url, args.run_config_id, api_token=args.api_token)
        except URLError as exc:
            raise SystemExit("Failed to fetch run config %s from %s: %s" % (args.run_config_id, args.api_url, exc))
        return request_from_run_config_document(payload, simulate=False)
    if args.request_file:
        return request_from_file(args.request_file, simulate=False)
    provided = any(getattr(args, name, None) is not None for name in ("model", "backend", "tier"))
    if provided:
        missing = [name for name in ("model", "backend", "tier") if getattr(args, name) is None]
        if missing:
            raise SystemExit("Missing required arguments for doctor request context: %s" % ", ".join(missing))
        request = request_from_cli(args)
        request.simulate = False
        return request
    return None


def main(argv: Optional[list] = None) -> int:
    """Run the InferGrade CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "show-profiles":
        payload = {
            key: {
                "description": profile.description,
                "primary_metrics": profile.primary_metrics,
            }
            for key, profile in DEPLOYMENT_PROFILES.items()
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.command == "show-capabilities":
        print(json.dumps(CAPABILITY_SUITES, indent=2, sort_keys=True))
        return 0

    if args.command == "doctor":
        report = run_doctor(request=_request_for_doctor(args), api_url=args.api_url)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1

    if args.command == "validate-bundle":
        validation = validate_bundle(args.path)
        print(json.dumps(validation.to_dict(), indent=2, sort_keys=True))
        return 0 if validation.valid else 1

    if args.command == "inspect-bundle":
        print(json.dumps(summarize_bundle(args.path), indent=2, sort_keys=True))
        return 0

    if args.command == "recommend":
        payload = recommend(
            args.paths,
            use_case=args.use_case,
            deployment_profile=args.deployment_profile,
            max_vram_gb=args.max_vram_gb,
            verification_levels=args.verification_level or (),
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.command == "init-request":
        payload = render_run_request_template(
            model=args.model,
            backend=args.backend,
            tier=args.tier,
            use_case=args.use_case,
            output_format=args.format,
        )
        if args.output:
            write_text(args.output, payload)
        else:
            print(payload, end="")
        return 0

    if args.command == "upload-bundle":
        try:
            payload = upload_bundle(args.path, args.api_url, api_token=args.api_token)
        except URLError as exc:
            raise SystemExit("Failed to upload bundle to %s: %s" % (args.api_url, exc))
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.command == "init-run-config":
        payload = render_run_config_template(
            name=args.name,
            model=args.model,
            backend=args.backend,
            tier=args.tier,
            use_case=args.use_case,
            output_format=args.format,
        )
        if args.output:
            write_text(args.output, payload)
        else:
            print(payload, end="")
        return 0

    if args.command == "list-run-configs":
        try:
            payload = list_run_configs(args.api_url, api_token=args.api_token)
        except URLError as exc:
            raise SystemExit("Failed to list run configs from %s: %s" % (args.api_url, exc))
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.command == "fetch-run-config":
        try:
            payload = fetch_run_config(args.api_url, args.run_config_id, api_token=args.api_token)
        except URLError as exc:
            raise SystemExit("Failed to fetch run config %s from %s: %s" % (args.run_config_id, args.api_url, exc))
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if args.output:
            write_text(args.output, text)
        else:
            print(text, end="")
        return 0

    if args.command == "publish-run-config":
        request = _request_from_args(args)
        request_payload = {
            "spec_version": "0.1-draft",
            "run": {
                "model": request.model,
                "backend": request.backend,
                "tier": request.tier,
                "use_case": request.use_case,
                "deployment_profiles": request.deployment_profiles,
                "execution_mode": request.execution_mode,
                "upload": request.upload,
                "capability": request.capability,
            },
            "overrides": {
                "backend_flags": request.backend_flags,
                "generation_preset": request.generation_preset,
            },
            "cost": {
                "source": request.cost_source,
                "hourly_rate_usd": request.hourly_rate_usd,
            },
            "metadata": {
                "submitter": request.submitter,
                "notes": request.notes,
            },
        }
        if request.quant_artifact:
            request_payload["run"]["quant_artifact"] = request.quant_artifact
            quantized_weights = {"uri": request.quant_artifact}
            if request.quant_artifact_sha256:
                quantized_weights["sha256"] = request.quant_artifact_sha256
            if request.quant_artifact_filename:
                quantized_weights["filename"] = request.quant_artifact_filename
            if request.quant_artifact_revision:
                quantized_weights["revision"] = request.quant_artifact_revision
            request_payload["artifacts"] = {"quantized_weights": quantized_weights}
        if request.backend_image or request.quant_artifact_cache_dir:
            runtime_payload = {}
            if request.backend_image:
                runtime_payload["backend_image"] = request.backend_image
            if request.quant_artifact_cache_dir:
                runtime_payload["artifact_cache_dir"] = request.quant_artifact_cache_dir
            request_payload["runtime"] = runtime_payload
        if request.ontology_hints:
            request_payload["ontology_hints"] = request.ontology_hints
        try:
            payload = publish_run_config(
                args.api_url,
                request_payload=request_payload,
                name=args.name,
                description=args.description,
                created_by=args.created_by,
                api_token=args.api_token,
            )
        except URLError as exc:
            raise SystemExit("Failed to publish run config to %s: %s" % (args.api_url, exc))
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.command == "run-config":
        try:
            payload = fetch_run_config(args.api_url, args.run_config_id, api_token=args.api_token)
        except URLError as exc:
            raise SystemExit("Failed to fetch run config %s from %s: %s" % (args.run_config_id, args.api_url, exc))
        request = request_from_run_config_document(payload, simulate=not args.real_run)
        if args.output:
            request.output_dir = args.output
        request.resume = bool(args.resume)
        result = run_infergrade(request, emit_progress=lambda message: print(message, file=sys.stderr, flush=True))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "run-job":
        result = run_worker_once(
            api_url=args.api_url,
            execution_mode=args.execution_mode,
            worker_id=args.worker_id,
            run_id=args.run_id,
            run_config_id=args.run_config_id,
            provider_id=args.provider_id,
            instance_type_id=args.instance_type_id,
            hostname=args.hostname,
            api_token=args.api_token,
            simulate=bool(args.simulate),
            emit_progress=lambda message: print(message, file=sys.stderr, flush=True),
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "worker":
        if args.once:
            result = run_worker_once(
                api_url=args.api_url,
                execution_mode=args.execution_mode,
                worker_id=args.worker_id,
                run_id=args.run_id,
                run_config_id=args.run_config_id,
                provider_id=args.provider_id,
                instance_type_id=args.instance_type_id,
                hostname=args.hostname,
                api_token=args.api_token,
                simulate=bool(args.simulate),
                emit_progress=lambda message: print(message, file=sys.stderr, flush=True),
            )
        else:
            result = run_worker_loop(
                api_url=args.api_url,
                execution_mode=args.execution_mode,
                worker_id=args.worker_id,
                run_id=args.run_id,
                run_config_id=args.run_config_id,
                provider_id=args.provider_id,
                instance_type_id=args.instance_type_id,
                hostname=args.hostname,
                api_token=args.api_token,
                simulate=bool(args.simulate),
                poll_interval_seconds=args.poll_interval_seconds,
                max_jobs=args.max_jobs,
                emit_progress=lambda message: print(message, file=sys.stderr, flush=True),
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    request = _request_from_args(args)
    result = run_infergrade(request, emit_progress=lambda message: print(message, file=sys.stderr, flush=True))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
