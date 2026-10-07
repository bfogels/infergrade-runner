#!/usr/bin/env python3
"""Check CUDA package installation on a CPU host without claiming GPU execution."""
import argparse
import os
from pathlib import Path
import subprocess

from smoke_managed_native_runtime import command_json, write_json
from verify_llama_cpp_model_canary import canary_command, download_model, model_spec, LEGACY_CANARY_ID


def smoke(cli, output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = {key: value for key, value in os.environ.items() if key not in {
        "LD_LIBRARY_PATH", "INFERGRADE_HUB_TOKEN", "HF_TOKEN", "HUGGING_FACE_HUB_TOKEN",
    }}
    env["INFERGRADE_RUNTIME_CACHE_DIR"] = str(output / "managed-cache")
    runtime_id = "llama-cpp-b11429-ubuntu22-x86_64-cuda"
    manifest = command_json(cli, ["runtime", "list"], env, output, "manifest")
    entry = next(item for item in manifest["runtimes"] if item["runtime_id"] == runtime_id)
    installed = command_json(cli, ["runtime", "install", "--runtime-id", runtime_id],
                             env, output, "managed-install", timeout=900)
    selection = installed["selection"]
    if selection["archive"]["sha256"] != entry["archive"]["sha256"] or not selection["archive"]["checksum_verified"]:
        raise ValueError("CUDA package archive identity did not match its pin")
    directory = Path(selection["binaries"]["cli"]).parent
    versions = {}
    for name in ("llama-cli", "llama-server", "llama-perplexity", "llama-completion"):
        result = subprocess.run([str(directory / name), "--version"], env=env,
                                capture_output=True, text=True, timeout=60)
        versions[name] = result.stdout + result.stderr
        if result.returncode or "11429" not in versions[name]:
            raise ValueError("CUDA executable version check failed: " + name)
    write_json(output / "versions.json", versions)
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
