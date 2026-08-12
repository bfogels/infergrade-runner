#!/usr/bin/env python3
"""Run a pinned GGUF load/generation canary against one verified llama.cpp runtime."""

import argparse
import hashlib
import json
import os
import pathlib
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


MODEL_REPOSITORY = "ggml-org/tiny-llamas"
MODEL_REVISION = "def3e2dd70df35ecbf6403ea347de4c5977220c1"
MODEL_FILENAME = "stories260K.gguf"
MODEL_SHA256 = "047bf46455a544931cff6fef14d7910154c56afbc23ab1c5e56a72e69912c04b"
MODEL_SIZE_BYTES = 1185376
DEFAULT_POLICY = pathlib.Path(__file__).resolve().parents[1] / "runtime" / "llama_cpp_release_policy.json"
LEGACY_CANARY_ID = "legacy_llama_tiny_generation_v1"
RECENT_CANARY_IDS = {"minicpm5_tokenizer"}


def load_json(path: pathlib.Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def model_spec(canary_id: str, policy_path: pathlib.Path = DEFAULT_POLICY) -> Dict[str, Any]:
    if canary_id == LEGACY_CANARY_ID:
        return {
            "canary_id": LEGACY_CANARY_ID,
            "family": "Synthetic legacy llama",
            "repository": MODEL_REPOSITORY,
            "revision": MODEL_REVISION,
            "filename": MODEL_FILENAME,
            "sha256": MODEL_SHA256,
            "size_bytes": MODEL_SIZE_BYTES,
            "timeout_seconds": 60,
            "proof_scope": "legacy_llama_model_load_and_generation",
            "model_compatibility": "legacy_control_only",
            "claim_boundary": (
                "This tiny synthetic llama-architecture canary proves one GGUF load and generation path only. "
                "It does not prove recent architectures, chat templates, benchmark behavior, performance, or support promotion."
            ),
        }
    if canary_id not in RECENT_CANARY_IDS:
        raise ValueError(f"unsupported automated model canary: {canary_id}")
    policy = load_json(policy_path)
    row = next(
        (item for item in policy.get("model_canaries", []) if item.get("id") == canary_id),
        None,
    )
    if not isinstance(row, dict):
        raise ValueError(f"model canary is missing from runtime policy: {canary_id}")
    artifact = str(row.get("artifact") or "")
    if not artifact.startswith("hf://") or "/" not in artifact[5:]:
        raise ValueError(f"{canary_id}: policy artifact must be a pinned Hugging Face file")
    repository, filename = artifact[5:].rsplit("/", 1)
    revision = str(row.get("revision") or "")
    sha256 = str(row.get("sha256") or "")
    size_bytes = int(row.get("size_bytes") or 0)
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise ValueError(f"{canary_id}: policy revision must be an exact commit")
    if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
        raise ValueError(f"{canary_id}: policy SHA-256 is invalid")
    if size_bytes <= 0 or size_bytes > 1024 * 1024 * 1024:
        raise ValueError(f"{canary_id}: automated canary must be positive and at most 1 GiB")
    return {
        "canary_id": canary_id,
        "family": str(row.get("family") or canary_id),
        "repository": repository,
        "revision": revision,
        "filename": filename,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "timeout_seconds": 180,
        "proof_scope": "recent_architecture_model_load_and_generation",
        "model_compatibility": "exact_model_artifact_only",
        "claim_boundary": (
            f"This canary proves only {row.get('family') or canary_id} load and short generation for the exact "
            "pinned artifact on this candidate runtime and CI platform. It does not prove chat-template behavior, "
            "benchmark correctness, performance, another artifact, another platform, or support promotion."
        ),
    }


def validate_archive_receipt(receipt: Dict[str, Any]) -> None:
    if receipt.get("receipt_version") != 1 or receipt.get("candidate_only") is not True:
        raise ValueError("model canary requires a version-1 candidate archive receipt")
    if receipt.get("platform") not in {"ubuntu-x64", "macos-arm64"}:
        raise ValueError("model canary requires a native macos-arm64 or ubuntu-x64 candidate archive")
    version_smoke = receipt.get("version_smoke")
    if not isinstance(version_smoke, dict) or version_smoke.get("status") != "passed":
        raise ValueError("model canary requires a passed native version smoke")
    artifact = receipt.get("artifact")
    if not isinstance(artifact, dict) or artifact.get("github_asset_sha256") != artifact.get(
        "downloaded_sha256"
    ):
        raise ValueError("model canary requires a digest-verified runtime archive")


def locate_generation_binary(runtime_dir: pathlib.Path) -> pathlib.Path:
    matches = [item for item in runtime_dir.rglob("llama-completion") if item.is_file()]
    if len(matches) != 1:
        raise ValueError(
            f"runtime directory must contain exactly one llama-completion; found {len(matches)}"
        )
    binary = matches[0].resolve()
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    return binary


def download_model(destination: pathlib.Path, spec: Dict[str, Any]) -> str:
    url = (
        f"https://huggingface.co/{spec['repository']}/resolve/"
        f"{spec['revision']}/{spec['filename']}"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "InferGrade-Runtime-Canary/1"})
    configured_ca = os.environ.get("SSL_CERT_FILE")
    ca_candidates = [configured_ca, "/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"]
    ca_file = next((item for item in ca_candidates if item and pathlib.Path(item).is_file()), None)
    context = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
    digest = hashlib.sha256()
    observed = 0
    with urllib.request.urlopen(request, timeout=120, context=context) as response, destination.open(
        "wb"
    ) as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            observed += len(chunk)
            if observed > spec["size_bytes"]:
                raise ValueError("model canary download exceeded the pinned size")
            digest.update(chunk)
            handle.write(chunk)
    if observed != spec["size_bytes"]:
        raise ValueError(
            f"model canary size mismatch: expected {spec['size_bytes']}, observed {observed}"
        )
    observed_digest = digest.hexdigest()
    if observed_digest != spec["sha256"]:
        raise ValueError("model canary digest does not match the pinned Hugging Face artifact")
    return observed_digest


def canary_command(binary: pathlib.Path, model: pathlib.Path) -> List[str]:
    return [
        str(binary),
        "-m",
        str(model),
        "-p",
        "Once upon a time",
        "-n",
        "8",
        "--seed",
        "1",
        "--no-display-prompt",
        "-no-cnv",
        "--no-warmup",
        "--no-perf",
        "-t",
        "2",
    ]


def run_canary(binary: pathlib.Path, model: pathlib.Path, timeout_seconds: int = 60) -> Dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(
        canary_command(binary, model),
        cwd=binary.parent,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    elapsed = round(time.monotonic() - started, 3)
    generated = completed.stdout.strip()
    if completed.returncode != 0:
        detail = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
        raise ValueError(
            f"model canary failed with exit {completed.returncode}: {detail[-500:]}"
        )
    if not generated:
        raise ValueError("model canary produced no generated text")
    return {
        "status": "passed",
        "elapsed_seconds": elapsed,
        "generated_output_chars": len(generated),
        "generated_output_sha256": hashlib.sha256(generated.encode("utf-8")).hexdigest(),
    }


def verify(
    runtime_dir: pathlib.Path,
    archive_receipt: Dict[str, Any],
    output: pathlib.Path,
    canary_id: str = LEGACY_CANARY_ID,
    policy_path: pathlib.Path = DEFAULT_POLICY,
) -> Dict[str, Any]:
    validate_archive_receipt(archive_receipt)
    spec = model_spec(canary_id, policy_path)
    binary = locate_generation_binary(runtime_dir)
    with tempfile.TemporaryDirectory(prefix="infergrade-llama-model-canary-") as tmp:
        model_path = pathlib.Path(tmp) / spec["filename"]
        downloaded_digest = download_model(model_path, spec)
        execution = run_canary(binary, model_path, spec["timeout_seconds"])
    receipt = {
        "receipt_version": 1,
        "candidate_only": True,
        "canary_id": spec["canary_id"],
        "status": "passed",
        "proof_scope": spec["proof_scope"],
        "model_compatibility": spec["model_compatibility"],
        "claim_boundary": spec["claim_boundary"],
        "runtime": {
            "release": archive_receipt.get("upstream", {}).get("release"),
            "platform": archive_receipt.get("platform"),
            "archive_sha256": archive_receipt.get("artifact", {}).get("downloaded_sha256"),
            "version_smoke": archive_receipt.get("version_smoke", {}).get("status"),
            "generation_binary": binary.name,
        },
        "model": {
            "family": spec["family"],
            "repository": spec["repository"],
            "revision": spec["revision"],
            "filename": spec["filename"],
            "size_bytes": spec["size_bytes"],
            "expected_sha256": spec["sha256"],
            "downloaded_sha256": downloaded_digest,
        },
        "execution": execution,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=pathlib.Path, required=True)
    parser.add_argument("--archive-receipt", type=pathlib.Path, required=True)
    parser.add_argument("--canary-id", default=LEGACY_CANARY_ID)
    parser.add_argument("--policy", type=pathlib.Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        receipt = verify(
            args.runtime_dir,
            load_json(args.archive_receipt),
            args.output,
            canary_id=args.canary_id,
            policy_path=args.policy,
        )
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError, urllib.error.URLError) as exc:
        print(f"llama.cpp model canary failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
