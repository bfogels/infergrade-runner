#!/usr/bin/env python3
"""Local, real hardware validation of native memory recovery; never uploads results."""
import argparse
import json
from pathlib import Path
import subprocess
import time

from infergrade.adapters.llama_cpp import LlamaCppAdapter
from infergrade.models import RunRequest
from infergrade.native_memory import effective_configuration, policy_summary
from infergrade.runtime_placement import validated_runtime_placement
from infergrade.utils import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--real-run", action="store_true", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--server-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expect", choices=("fast", "fallback"), required=True)
    parser.add_argument("--probe-only", action="store_true", help="Only unscored 8-token generation readiness; no deployment measurements")
    parser.add_argument("--measured-runs", type=int, default=5)
    parser.add_argument("--warmup-runs", type=int, default=2)
    args = parser.parse_args()
    for path in (args.model_path, args.server_path):
        if not path.is_file():
            parser.error("Missing local input: %s" % path)
    if args.output_dir.exists():
        parser.error("Use a fresh output directory to preserve the evidence")
    args.output_dir.mkdir(parents=True)
    request = RunRequest(model=args.model, quant_artifact=str(args.model_path.resolve()),
                         quant_artifact_resolved_path=str(args.model_path.resolve()), backend="llama.cpp",
                         tier="standard", use_case="general_assistant", capability="none",
                         execution_mode="local_native", simulate=False,
                         llama_cpp_server_path=str(args.server_path.resolve()),
                         llama_cpp_cli_path=str(args.server_path.resolve().with_name("llama-cli")),
                         output_dir=str(args.output_dir.resolve()), deployment_warmup_runs=args.warmup_runs,
                         deployment_measured_runs=args.measured_runs)
    events = []
    def progress(message):
        events.append(message)
        print(message, flush=True)
    request._native_memory_progress = progress
    adapter = LlamaCppAdapter()
    started = time.perf_counter()
    receipt = {"validation_kind": "local_hardware_memory_recovery", "simulate": False,
               "model": args.model, "model_path": str(args.model_path.resolve()),
               "server_path": str(args.server_path.resolve()),
               "runtime_version": subprocess.run([str(args.server_path), "--version"], capture_output=True).stderr.decode(errors="replace")[-1200:],
               "scope": "Real local preflight and interactive_chat_v1 deployment; no capability score, upload, or publication"}
    try:
        adapter.preflight_model(request)
        if args.probe_only:
            receipt.update(validation_status="passed", scope="Unscored 8-token generation readiness only; no deployment timings, capability score, upload or publication")
            if (effective_configuration(request) is not None) != (args.expect == "fallback"):
                raise RuntimeError("Unexpected recovery choice: expected %s" % args.expect)
            return
        result = adapter.run_deployment_profile(request, "interactive_chat_v1", lambda event: progress(event.get("message", "")))
        receipt.update(status=result.status, metrics=result.metrics, artifacts=result.artifacts,
                       native_memory_policy=effective_configuration(request), observations=policy_summary(request))
        fallback = effective_configuration(request) is not None
        if fallback != (args.expect == "fallback"):
            raise RuntimeError("Unexpected recovery choice: expected %s" % args.expect)
        if result.status != "completed" or len(result.artifacts["runs"]) != args.measured_runs + args.warmup_runs:
            raise RuntimeError("Profile did not complete all requested iterations")
        for sample in result.artifacts["runs"]:
            if validated_runtime_placement(sample.get("runtime_placement")) is None:
                raise RuntimeError("Invalid placement receipt")
        receipt["validation_status"] = "passed"
    except BaseException as exc:
        receipt["validation_status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        receipt["error"] = str(exc)
        raise
    finally:
        receipt["native_memory_policy"] = effective_configuration(request)
        receipt["observations"] = policy_summary(request)
        receipt["wall_seconds"] = round(time.perf_counter() - started, 3)
        receipt["events"] = events
        write_json(str(args.output_dir / "validation.json"), receipt)
        print("Receipt: %s" % (args.output_dir / "validation.json"), flush=True)


if __name__ == "__main__":
    main()
