#!/usr/bin/env python3
"""Check CUDA package installation on a CPU host without claiming GPU execution."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from smoke_managed_native_runtime import command_json, write_json
from verify_linux_cuda_package import verify_package
from verify_llama_cpp_model_canary import canary_command, download_model, model_spec, LEGACY_CANARY_ID


def smoke(cli, output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = {key: value for key, value in os.environ.items() if key not in {
        "LD_LIBRARY_PATH", "INFERGRADE_HUB_TOKEN", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN",
    }}
    env["INFERGRADE_RUNTIME_CACHE_DIR"] = str(output / "managed-cache")
    manifest = command_json(cli, ["runtime", "list"], env, output, "manifest")
    # Match the managed default's manifest ordering rather than continuing to
    # qualify a superseded Ubuntu archive after the portable CUDA pin changes.
    entry = next(item for item in manifest["runtimes"]
                 if item["platform"]["system"] == "linux" and item["platform"]["arch"] == "x86_64"
                 and item["accelerator"] == "cuda" and item["download"]["enabled"])
    runtime_id = entry["runtime_id"]
    installed = command_json(cli, ["runtime", "install", "--runtime-id", runtime_id],
                             env, output, "managed-install", timeout=900)
    selection = installed["selection"]
    if selection["archive"]["sha256"] != entry["archive"]["sha256"] or not selection["archive"]["checksum_verified"]:
        raise ValueError("CUDA package archive identity did not match its pin")
    directory = Path(selection["binaries"]["cli"]).parent
    verify_package(directory, output / "dependency-closure")
    if any(directory.rglob("libcuda.so*")):
        raise ValueError("CUDA package must use the host NVIDIA driver, not a bundled driver or stub")
    if not (directory / "libggml-cuda.so").is_file():
        raise ValueError("CUDA package did not contain its dynamic backend")
    origin = json.loads((directory / "build-origin.json").read_text())
    required_targets = {"50-virtual", "61-virtual", "70-virtual", "75-virtual", "80-virtual",
                        "86-real", "89-real", "90-virtual", "120a-real"}
    if not required_targets.issubset(origin.get("cuda_architecture_targets", [])):
        raise ValueError("CUDA default package narrowed the pinned upstream GPU target policy")
    for key in ("upstream_commit", "source_archive_sha256", "cuda_architecture_targets",
                "cccl_commit", "cccl_source_sha256"):
        if key in {"upstream_commit", "source_archive_sha256"} and key not in entry["build_origin"]:
            raise ValueError("CUDA manifest is missing source provenance: " + key)
        if key in entry["build_origin"] and entry["build_origin"][key] != origin.get(key):
            raise ValueError("CUDA package provenance did not match manifest: " + key)
    versions = {}
    for name in ("llama-cli", "llama-server", "llama-perplexity", "llama-completion"):
        result = subprocess.run([str(directory / name), "--version"], env=env,
                                capture_output=True, text=True, timeout=60)
        versions[name] = result.stdout + result.stderr
        if result.returncode or "11429" not in versions[name]:
            raise ValueError("CUDA executable version check failed: " + name)
    write_json(output / "versions.json", versions)
    setup_env = dict(env, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "python/runner-core/src"))
    unavailable = subprocess.run([sys.executable, "-c",
                                  "from infergrade.runtimes import prepare_native_listener_runtime; prepare_native_listener_runtime()"],
                                 env=setup_env, capture_output=True, text=True, timeout=90)
    (output / "cuda-listener-not-ready.txt").write_text(unavailable.stdout + unavailable.stderr)
    if unavailable.returncode == 0 or "could not detect a usable NVIDIA device" not in unavailable.stderr:
        raise ValueError("CUDA setup did not reject an unavailable GPU before listening")
    spec = model_spec(LEGACY_CANARY_ID)
    model = output / spec["filename"]
    digest = download_model(model, spec)
    # Deliberately run CPU generation from the CUDA package on CPU-only CI.
    result = subprocess.run(canary_command(directory / "llama-completion", model) + ["--n-gpu-layers", "0"],
                            env=env, capture_output=True, text=True, timeout=60)
    (output / "cpu-canary.txt").write_text(result.stdout + result.stderr)
    if result.returncode or not result.stdout.strip():
        raise ValueError("CUDA package CPU canary failed")
    rejected = subprocess.run([str(cli), "first-run", "--model", str(model), "--runtime", "auto",
                               "--no-upload", "--prompt", "Once upon a time", "--max-tokens", "8",
                               "--output-dir", str(output / "rejected-gpu-run"), "--json"],
                              env=env, capture_output=True, text=True, timeout=60)
    diagnostic = rejected.stdout + rejected.stderr
    (output / "cuda-request-rejected.txt").write_text(diagnostic)
    if rejected.returncode == 0 or "Requested CUDA runtime did not prove CUDA" not in diagnostic:
        raise ValueError("CUDA request did not fail closed on a CPU-only host: " + diagnostic[-1500:])
    write_json(output / "receipt.json", {
        "status": "passed", "runtime_id": runtime_id,
        "archive_sha256": entry["archive"]["sha256"],
        "runtime_build_id": selection["runtime_build"]["runtime_build_id"],
        "build_origin": entry["build_origin"], "version_loader_smokes": "passed",
        "cpu_generation_from_cuda_package": "passed", "model_sha256": digest,
        "cuda_request_without_gpu": "rejected", "gpu_execution_verified": False,
        "listener_without_cuda_device": "blocked_before_registration",
        "driver_library_bundled": False,
        "claim_boundary": "Ubuntu 22 CUDA archive installation, binary loading and CPU-only generation. CUDA request correctly rejects absent GPU proof. Physical NVIDIA execution unverified.",
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    smoke(args.cli.resolve(), args.output)


if __name__ == "__main__":
    main()
