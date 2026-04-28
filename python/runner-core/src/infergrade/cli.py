"""Command-line entrypoints for running and inspecting InferGrade bundles."""

import argparse
import json
import socket
import sys
from typing import Optional
from urllib.error import URLError

from infergrade import __version__
from infergrade.analysis import recommend, summarize_bundle
from infergrade.artifacts import artifact_cache_status, default_artifact_cache_dir, prune_partial_artifacts
from infergrade.benchmark_catalog import load_capability_catalog
from infergrade.doctor import run_doctor
from infergrade.environment import capture_environment
from infergrade.images import install_known_images
from infergrade.pairing import (
    clear_runner_profile,
    preferred_local_execution_mode,
    resolve_runner_api_token,
    resolve_runner_api_url,
    resolve_runner_execution_mode,
    resolve_runner_id,
    runner_profile_path,
    save_runner_profile,
)
from infergrade.profiles import DEPLOYMENT_PROFILES
from infergrade.request import request_from_cli, request_from_file
from infergrade.run_configs import request_from_run_config_document
from infergrade.runner import run_infergrade
from infergrade.runtimes import install_llama_cpp_runtime, runtime_manifest, select_llama_cpp_runtime, selected_llama_cpp_runtime
from infergrade.support import build_support_export, write_support_export
from infergrade.templates import render_run_config_template, render_run_request_template
from infergrade.transport import (
    fetch_run_config,
    list_run_configs,
    publish_run_config,
    redeem_runner_pairing,
    upload_bundle,
)
from infergrade.utils import write_text
from infergrade.validators import validate_bundle
from infergrade.worker import run_worker_loop, run_worker_once


ADVANCED_COMMANDS = {
    "run",
    "run-job",
    "worker",
    "init-request",
    "init-run-config",
    "list-run-configs",
    "fetch-run-config",
    "publish-run-config",
    "run-config",
    "validate-bundle",
    "inspect-bundle",
    "recommend",
    "upload-bundle",
    "export-support",
    "install-images",
    "show-profiles",
    "show-capabilities",
}
DEFAULT_COMMANDS = ("doctor", "cache", "install-runtime", "pair", "unpair", "start")


class _InferGradeHelpFormatter(argparse.HelpFormatter):
    """Hide advanced command rows cleanly in the default command list."""

    def _format_action(self, action):  # pragma: no cover - exercised through CLI help tests
        if isinstance(action, argparse._SubParsersAction):
            action._choices_actions = [choice for choice in action._choices_actions if choice.help != argparse.SUPPRESS]
        return super()._format_action(action)


def _command_help(command: str, help_text: str, show_advanced: bool) -> str:
    """Hide non-canonical commands from default help while keeping them callable."""
    if command in ADVANCED_COMMANDS and not show_advanced:
        return argparse.SUPPRESS
    return help_text


def _add_api_token_argument(parser: argparse.ArgumentParser) -> None:
    """Add the shared hosted-API token flag to a parser."""
    parser.add_argument(
        "--api-token",
        help="Optional Hub/API token. Falls back to INFERGRADE_HUB_TOKEN, then INFERGRADE_API_TOKEN, then a paired local runner profile if unset.",
    )


def _add_run_token_argument(parser: argparse.ArgumentParser) -> None:
    """Add the optional run-scoped execution token flag to a parser."""
    parser.add_argument(
        "--run-token",
        help="Optional short-lived run execution token. Falls back to INFERGRADE_RUN_TOKEN if unset.",
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
    parser.add_argument("--llama-cpp-cli-path", help="Explicit llama.cpp CLI binary for local_native runs.")
    parser.add_argument("--llama-cpp-server-path", help="Explicit llama.cpp server binary for local_native runs.")
    parser.add_argument("--llama-cpp-perplexity-path", help="Explicit llama.cpp perplexity binary for local_native fidelity runs.")
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


def build_parser(show_advanced: bool = False) -> argparse.ArgumentParser:
    """Build the top-level InferGrade CLI parser."""
    parser = argparse.ArgumentParser(
        prog="infergrade",
        formatter_class=_InferGradeHelpFormatter,
        epilog="Run `infergrade --all --help` to list advanced and compatibility commands.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    parser.add_argument("--all", action="store_true", help=argparse.SUPPRESS)
    metavar = None if show_advanced else "{%s}" % ",".join(DEFAULT_COMMANDS)
    subparsers = parser.add_subparsers(dest="command", required=True, metavar=metavar)

    run_parser = subparsers.add_parser("run", help=_command_help("run", "Run or simulate an InferGrade bundle.", show_advanced))
    _add_run_request_arguments(run_parser)

    doctor_parser = subparsers.add_parser("doctor", help="Check whether the current machine is ready for a InferGrade run.")
    _add_run_request_arguments(doctor_parser)
    doctor_parser.add_argument("--api-url")
    doctor_parser.add_argument("--run-config-id")
    _add_api_token_argument(doctor_parser)

    validate_parser = subparsers.add_parser("validate-bundle", help=_command_help("validate-bundle", "Validate an existing bundle.", show_advanced))
    validate_parser.add_argument("path")

    inspect_parser = subparsers.add_parser("inspect-bundle", help=_command_help("inspect-bundle", "Summarize a bundle.", show_advanced))
    inspect_parser.add_argument("path")

    recommend_parser = subparsers.add_parser("recommend", help=_command_help("recommend", "Compute local frontier-style recommendations.", show_advanced))
    recommend_parser.add_argument("paths", nargs="+")
    recommend_parser.add_argument("--use-case")
    recommend_parser.add_argument("--deployment-profile")
    recommend_parser.add_argument("--max-vram-gb", type=float)
    recommend_parser.add_argument("--verification-level", action="append")

    init_parser = subparsers.add_parser("init-request", help=_command_help("init-request", "Generate a starter run request template.", show_advanced))
    init_parser.add_argument("--format", choices=("yaml", "json"), default="yaml")
    init_parser.add_argument("--output")
    init_parser.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    init_parser.add_argument("--backend", default="llama.cpp")
    init_parser.add_argument("--tier", default="canary")
    init_parser.add_argument("--use-case")

    upload_parser = subparsers.add_parser("upload-bundle", help=_command_help("upload-bundle", "Upload a local bundle to a InferGrade API.", show_advanced))
    upload_parser.add_argument("path")
    upload_parser.add_argument("--api-url", required=True)
    _add_api_token_argument(upload_parser)

    support_parser = subparsers.add_parser(
        "export-support",
        help=_command_help("export-support", "Write a compact support export for a local run or runner session.", show_advanced),
    )
    support_parser.add_argument("--run-dir", help="Optional run output directory to include in the support export.")
    support_parser.add_argument("--execution-mode", help="Optional execution mode override for environment capture.")
    support_parser.add_argument("--output", help="Optional output path. Prints JSON to stdout when omitted.")

    install_images_parser = subparsers.add_parser(
        "install-images",
        help=_command_help("install-images", "Build the local InferGrade runtime and capability images.", show_advanced),
    )
    install_images_parser.add_argument(
        "--image",
        help="Optional specific image tag to build locally, for example infergrade-llama-cpp:local.",
    )
    install_images_parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force a rebuild of local InferGrade images even if they already exist.",
    )

    cache_parser = subparsers.add_parser("cache", help="Inspect or clean the local artifact cache.")
    cache_parser.add_argument("--artifact-cache-dir", default=default_artifact_cache_dir())
    cache_parser.add_argument("--status", action="store_true", help="Print artifact cache size and free-space details.")
    cache_parser.add_argument("--prune-partials", action="store_true", help="Remove interrupted artifact downloads.")
    cache_parser.add_argument("--dry-run", action="store_true", help="Report what would be removed without deleting files.")
    cache_parser.add_argument("--partial-min-age-seconds", type=int, default=3600, help="Only prune partial downloads at least this old.")

    runtime_parser = subparsers.add_parser("install-runtime", help="Inspect, install, or select an explicit managed runtime.")
    runtime_parser.add_argument("--runtime", choices=("llama.cpp",), default="llama.cpp")
    runtime_parser.add_argument("--runtime-id")
    runtime_parser.add_argument("--execute", action="store_true", help="Run the manifest install command after inspecting the plan.")
    runtime_parser.add_argument("--select-existing", action="store_true", help="Select existing local binaries as the managed runtime.")
    runtime_parser.add_argument("--llama-cpp-cli-path")
    runtime_parser.add_argument("--llama-cpp-server-path")
    runtime_parser.add_argument("--llama-cpp-perplexity-path")
    runtime_parser.add_argument("--list", action="store_true", help="Print the Runner-owned known-good runtime manifest.")

    pair_parser = subparsers.add_parser("pair", help="Pair this local machine with InferGrade Hub and save a reusable runner profile.")
    pair_parser.add_argument("--api-url", required=True)
    pair_parser.add_argument("--pair-code", required=True)
    pair_parser.add_argument("--label")
    pair_parser.add_argument("--hostname")

    unpair_parser = subparsers.add_parser("unpair", help="Remove the saved local runner pairing profile.")
    unpair_parser.add_argument("--print-path", action="store_true")

    init_config_parser = subparsers.add_parser(
        "init-run-config",
        help=_command_help("init-run-config", "Generate a starter server-style run config document.", show_advanced),
    )
    init_config_parser.add_argument("--format", choices=("yaml", "json"), default="json")
    init_config_parser.add_argument("--output")
    init_config_parser.add_argument("--name", default="General assistant canary run")
    init_config_parser.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    init_config_parser.add_argument("--backend", default="llama.cpp")
    init_config_parser.add_argument("--tier", default="canary")
    init_config_parser.add_argument("--use-case")

    list_configs_parser = subparsers.add_parser("list-run-configs", help=_command_help("list-run-configs", "List server-side run configs.", show_advanced))
    list_configs_parser.add_argument("--api-url", required=True)
    _add_api_token_argument(list_configs_parser)

    fetch_config_parser = subparsers.add_parser("fetch-run-config", help=_command_help("fetch-run-config", "Fetch a run config from the API.", show_advanced))
    fetch_config_parser.add_argument("--api-url", required=True)
    fetch_config_parser.add_argument("--run-config-id", required=True)
    fetch_config_parser.add_argument("--output")
    _add_api_token_argument(fetch_config_parser)

    publish_config_parser = subparsers.add_parser(
        "publish-run-config",
        help=_command_help("publish-run-config", "Publish a run config to the API.", show_advanced),
    )
    _add_run_request_arguments(publish_config_parser)
    publish_config_parser.add_argument("--api-url", required=True)
    publish_config_parser.add_argument("--name", required=True)
    publish_config_parser.add_argument("--description")
    publish_config_parser.add_argument("--created-by")
    _add_api_token_argument(publish_config_parser)

    run_config_parser = subparsers.add_parser("run-config", help=_command_help("run-config", "Fetch a run config from the API and execute it.", show_advanced))
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

    run_job_parser = subparsers.add_parser(
        "run-job",
        help=_command_help("run-job", "Claim and execute one Hub-backed run job with automatic upload.", show_advanced),
    )
    run_job_parser.add_argument("--api-url")
    run_job_parser.add_argument("--run-id")
    run_job_parser.add_argument("--run-config-id")
    run_job_parser.add_argument("--execution-mode", choices=("local_container", "local_native", "cloud_container"))
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
    _add_run_token_argument(run_job_parser)

    start_parser = subparsers.add_parser("start", help="Start a long-lived local runner that listens for Hub-backed local jobs.")
    start_parser.add_argument("--api-url")
    start_parser.add_argument("--execution-mode", choices=("local_container", "local_native"))
    start_parser.add_argument("--worker-id")
    start_parser.add_argument("--hostname")
    start_parser.add_argument("--poll-interval-seconds", type=float, default=10.0)
    start_parser.add_argument("--max-jobs", type=int)
    start_parser.add_argument("--once", action="store_true")
    start_parser.add_argument(
        "--simulate",
        action="store_true",
        help="Use simulated execution when the local runner claims jobs.",
    )
    _add_api_token_argument(start_parser)

    worker_parser = subparsers.add_parser("worker", help=_command_help("worker", "Claim and execute API-backed run jobs.", show_advanced))
    worker_parser.add_argument("--api-url")
    worker_parser.add_argument("--execution-mode", choices=("local_container", "local_native", "cloud_container"))
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

    profiles_parser = subparsers.add_parser("show-profiles", help=_command_help("show-profiles", "Show deployment profiles.", show_advanced))
    profiles_parser.set_defaults(_profiles=True)

    capabilities_parser = subparsers.add_parser("show-capabilities", help=_command_help("show-capabilities", "Show capability suites.", show_advanced))
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


def _require_runner_api_url(api_url: Optional[str]) -> str:
    """Resolve the API URL for paired-runner commands or stop with a helpful error."""
    resolved = resolve_runner_api_url(api_url)
    if resolved:
        return resolved
    raise SystemExit("No API URL provided and no paired runner profile found. Pass --api-url or run `infergrade pair` first.")


def _resolve_local_execution_mode(execution_mode: Optional[str], allow_cloud: bool = False) -> str:
    """Resolve the execution mode for paired-runner commands."""
    if execution_mode:
        return execution_mode
    resolved = resolve_runner_execution_mode(None)
    if allow_cloud:
        return resolved
    if resolved == "cloud_container":
        return preferred_local_execution_mode()
    return resolved


def _resolve_runner_worker_id(worker_id: Optional[str], execution_mode: Optional[str] = None) -> Optional[str]:
    """Resolve the durable runner identifier for paired local-runner commands."""
    if worker_id:
        return resolve_runner_id(worker_id)
    if execution_mode in (None, "local_container", "local_native"):
        return resolve_runner_id(None)
    return None


def main(argv: Optional[list] = None) -> int:
    """Run the InferGrade CLI."""
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser(show_advanced="--all" in raw_argv)
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
        print(json.dumps(load_capability_catalog(), indent=2, sort_keys=True))
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

    if args.command == "export-support":
        if args.output:
            path = write_support_export(args.output, run_dir=args.run_dir, execution_mode=args.execution_mode)
            print(json.dumps({"written": True, "path": path}, indent=2, sort_keys=True))
        else:
            print(json.dumps(build_support_export(run_dir=args.run_dir, execution_mode=args.execution_mode), indent=2, sort_keys=True))
        return 0

    if args.command == "install-images":
        payload = install_known_images(image=args.image, rebuild=args.rebuild)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.command == "cache":
        if args.prune_partials:
            payload = prune_partial_artifacts(
                cache_dir=args.artifact_cache_dir,
                dry_run=args.dry_run,
                min_age_seconds=args.partial_min_age_seconds,
            )
        else:
            payload = artifact_cache_status(cache_dir=args.artifact_cache_dir)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.command == "install-runtime":
        if args.list:
            print(json.dumps(runtime_manifest(), indent=2, sort_keys=True))
            return 0
        if args.select_existing:
            payload = select_llama_cpp_runtime(
                runtime_id=args.runtime_id,
                cli_path=args.llama_cpp_cli_path,
                server_path=args.llama_cpp_server_path,
                perplexity_path=args.llama_cpp_perplexity_path,
            )
        else:
            payload = install_llama_cpp_runtime(runtime_id=args.runtime_id, execute=args.execute)
        payload = dict(payload)
        payload["current_selection"] = selected_llama_cpp_runtime()
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.command == "pair":
        execution_mode = preferred_local_execution_mode()
        environment = capture_environment(execution_mode)
        try:
            payload = redeem_runner_pairing(
                api_url=args.api_url,
                pair_code=args.pair_code,
                label=args.label,
                hostname=args.hostname or socket.gethostname(),
                execution_mode=execution_mode,
                environment=environment,
            )
        except (URLError, RuntimeError) as exc:
            raise SystemExit("Failed to redeem runner pairing code against %s: %s" % (args.api_url, exc))
        profile = dict(payload.get("runner_profile") or {})
        if not profile:
            raise SystemExit("Hub pairing response did not include a runner profile.")
        path = save_runner_profile(profile)
        result = {
            "paired": True,
            "profile_path": path,
            "runner_profile": profile,
            "next_action": "start_runner",
            "commands": {
                "start": "infergrade start",
            },
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "unpair":
        profile_path = runner_profile_path()
        removed = clear_runner_profile()
        if args.print_path:
            print(json.dumps({"removed": removed, "profile_path": profile_path}, indent=2, sort_keys=True))
        else:
            print(json.dumps({"removed": removed}, indent=2, sort_keys=True))
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
        if request.backend_image or request.quant_artifact_cache_dir or request.llama_cpp_cli_path or request.llama_cpp_server_path or request.llama_cpp_perplexity_path:
            runtime_payload = {}
            if request.backend_image:
                runtime_payload["backend_image"] = request.backend_image
            if request.quant_artifact_cache_dir:
                runtime_payload["artifact_cache_dir"] = request.quant_artifact_cache_dir
            if request.llama_cpp_cli_path:
                runtime_payload["llama_cpp_cli_path"] = request.llama_cpp_cli_path
            if request.llama_cpp_server_path:
                runtime_payload["llama_cpp_server_path"] = request.llama_cpp_server_path
            if request.llama_cpp_perplexity_path:
                runtime_payload["llama_cpp_perplexity_path"] = request.llama_cpp_perplexity_path
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
        execution_mode = _resolve_local_execution_mode(args.execution_mode, allow_cloud=True)
        result = run_worker_once(
            api_url=_require_runner_api_url(args.api_url),
            execution_mode=execution_mode,
            worker_id=_resolve_runner_worker_id(args.worker_id, execution_mode),
            run_id=args.run_id,
            run_config_id=args.run_config_id,
            provider_id=args.provider_id,
            instance_type_id=args.instance_type_id,
            hostname=args.hostname,
            api_token=resolve_runner_api_token(args.api_token),
            run_token=args.run_token,
            simulate=bool(args.simulate),
            emit_progress=lambda message: print(message, file=sys.stderr, flush=True),
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "start":
        execution_mode = _resolve_local_execution_mode(args.execution_mode)
        worker_id = _resolve_runner_worker_id(args.worker_id, execution_mode)
        if args.once:
            result = run_worker_once(
                api_url=_require_runner_api_url(args.api_url),
                execution_mode=execution_mode,
                worker_id=worker_id,
                hostname=args.hostname,
                api_token=resolve_runner_api_token(args.api_token),
                run_token=None,
                simulate=bool(args.simulate),
                emit_progress=lambda message: print(message, file=sys.stderr, flush=True),
            )
        else:
            result = run_worker_loop(
                api_url=_require_runner_api_url(args.api_url),
                execution_mode=execution_mode,
                worker_id=worker_id,
                hostname=args.hostname,
                api_token=resolve_runner_api_token(args.api_token),
                run_token=None,
                simulate=bool(args.simulate),
                poll_interval_seconds=args.poll_interval_seconds,
                max_jobs=args.max_jobs,
                emit_progress=lambda message: print(message, file=sys.stderr, flush=True),
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if args.command == "worker":
        execution_mode = _resolve_local_execution_mode(args.execution_mode, allow_cloud=True)
        worker_id = _resolve_runner_worker_id(args.worker_id, execution_mode)
        if args.once:
            result = run_worker_once(
                api_url=_require_runner_api_url(args.api_url),
                execution_mode=execution_mode,
                worker_id=worker_id,
                run_id=args.run_id,
                run_config_id=args.run_config_id,
                provider_id=args.provider_id,
                instance_type_id=args.instance_type_id,
                hostname=args.hostname,
                api_token=resolve_runner_api_token(args.api_token),
                run_token=None,
                simulate=bool(args.simulate),
                emit_progress=lambda message: print(message, file=sys.stderr, flush=True),
            )
        else:
            result = run_worker_loop(
                api_url=_require_runner_api_url(args.api_url),
                execution_mode=execution_mode,
                worker_id=worker_id,
                run_id=args.run_id,
                run_config_id=args.run_config_id,
                provider_id=args.provider_id,
                instance_type_id=args.instance_type_id,
                hostname=args.hostname,
                api_token=resolve_runner_api_token(args.api_token),
                run_token=None,
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
