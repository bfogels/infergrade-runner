#!/usr/bin/env python3
"""Exercise the real Rust managed installer and native first-run with a pinned public GGUF.

This is CPU CI evidence, not NVIDIA qualification or desktop updater evidence.
Run with a fresh output directory; no Hugging Face credentials or Docker are used.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from verify_llama_cpp_model_canary import download_model, model_spec, run_canary, LEGACY_CANARY_ID


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def command_json(cli, args, env, output, name, timeout=300):
    completed = subprocess.run([str(cli), *args], env=env, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=timeout)
    (output / f"{name}.stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (output / f"{name}.stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode:
        raise ValueError(f"{name} failed ({completed.returncode}): {completed.stderr[-2000:]}")
    value = json.loads(completed.stdout)
    write_json(output / f"{name}.json", value)
    return value


def smoke(cli, output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    # Isolate the managed cache and remove credentials from all child processes.
    env = {key: value for key, value in os.environ.items()
           if key not in {"HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "INFERGRADE_HUB_TOKEN"}}
    env["INFERGRADE_RUNTIME_CACHE_DIR"] = str(output / "managed-cache")
    manifest = command_json(cli, ["runtime", "list"], env, output, "manifest")
    plan = command_json(cli, ["runtime", "plan"], env, output, "plan")
    # Use the Rust process architecture (Python may run through Rosetta locally).
    host = plan["recommended_runtime"]["platform"]
    system, arch = host["system"], host["arch"]
    accelerator = "metal" if (system, arch) == ("macos", "aarch64") else "cpu"
    candidates = [row for row in manifest["runtimes"]
                  if row["platform"]["system"] == system and row["platform"]["arch"] == arch
                  and row["accelerator"] == accelerator and row["channel"] == "upstream_release"]
    if len(candidates) != 1:
        raise ValueError(f"Expected one pinned upstream {system}/{arch}/{accelerator} runtime")
    entry = candidates[0]
    installed = command_json(cli, ["runtime", "install", "--runtime-id", entry["runtime_id"]],
                             env, output, "managed-install", timeout=600)
    selection = installed["selection"]
    if installed["status"] != "selected" or selection["archive"]["checksum_verified"] is not True:
        raise ValueError("Managed installer did not select a checksum-verified runtime")
    if selection["archive"]["sha256"] != entry["archive"]["sha256"]:
        raise ValueError("Selected runtime archive identity does not match the pin")
    versions = {}
    for role in ("cli", "server", "perplexity"):
        binary = Path(selection["binaries"][role])
        completed = subprocess.run([str(binary), "--version"], env=env,
                                   stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        if completed.returncode:
            raise ValueError(f"Selected {role} failed version smoke: {completed.stderr[-2000:]}")
        versions[role] = {"path": str(binary), "output": (completed.stdout + completed.stderr).strip()}
    write_json(output / "selected-binary-versions.json", versions)
    expected_build = entry["upstream"]["tag"][1:]
    if expected_build not in versions["cli"]["output"]:
        raise ValueError("Selected CLI version does not report the pinned upstream binary build")
    spec = model_spec(LEGACY_CANARY_ID)
    model = output / spec["filename"]
    digest = download_model(model, spec)
    binary = Path(selection["binaries"]["cli"]).with_name("llama-completion.exe" if system == "windows" else "llama-completion")
    generation = run_canary(binary, model)
    first_run = command_json(cli, ["first-run", "--model", str(model), "--runtime", "auto",
                                  "--no-upload", "--prompt", "Once upon a time", "--max-tokens", "8",
                                  "--output-dir", str(output / "first-run"), "--json"],
                             env, output, "runner-first-run")
    if first_run["execution"] != "local_native" or first_run["result"]["status"] != "completed":
        raise ValueError("Runner first-run did not complete through the built-in native adapter")
    if first_run["result"]["runtime_id"] != selection["runtime_id"]:
        raise ValueError("Runner first-run did not use the managed selection")
    if first_run["result"]["metrics"]["generated_tokens"] <= 0:
        raise ValueError("Runner first-run reported no generated tokens")
    build_id = selection["runtime_build"]["runtime_build_id"]
    rollback = command_json(cli, ["runtime", "rollback", "--runtime-build-id", build_id], env, output, "rollback")
    if rollback["status"] != "selected" or rollback["runtime_build_id"] != build_id:
        raise ValueError("Exact installed-build reselection failed")
    receipt = {"schema_version": "infergrade.managed_native_smoke.v1", "status": "passed",
               "candidate_only": True, "platform": {"system": system, "arch": arch},
               "accelerator": accelerator, "runtime_id": entry["runtime_id"],
               "runtime_build_id": build_id, "upstream": selection["upstream"],
               "model": {"repository": spec["repository"], "revision": spec["revision"],
                         "sha256": digest, "size_bytes": model.stat().st_size},
               "generation": generation, "runner_first_run": "passed",
               "exact_build_reselection": "passed", "docker_required": False,
               "claim_boundary": "Exact host installer, binary load, tiny legacy GGUF generation and Rust native first-run only. CPU CI does not qualify NVIDIA hardware. No broad model support, desktop package, signing or updater qualification."}
    write_json(output / "receipt.json", receipt)
    print(json.dumps(receipt, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        smoke(args.cli.resolve(), args.output)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"Managed native runtime smoke failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
