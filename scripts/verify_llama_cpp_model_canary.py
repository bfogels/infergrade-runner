#!/usr/bin/env python3
"""Run a tiny pinned GGUF load/generation canary against one verified llama.cpp runtime."""

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
MODEL_URL = (
    f"https://huggingface.co/{MODEL_REPOSITORY}/resolve/{MODEL_REVISION}/{MODEL_FILENAME}"
)


def load_json(path: pathlib.Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


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


def locate_llama_cli(runtime_dir: pathlib.Path) -> pathlib.Path:
    matches = [item for item in runtime_dir.rglob("llama-cli") if item.is_file()]
    if len(matches) != 1:
        raise ValueError(f"runtime directory must contain exactly one llama-cli; found {len(matches)}")
    binary = matches[0]
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    return binary


def download_model(destination: pathlib.Path) -> str:
    request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "InferGrade-Runtime-Canary/1"})
    configured_ca = os.environ.get("SSL_CERT_FILE")
    ca_candidates = [configured_ca, "/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"]
    ca_file = next((item for item in ca_candidates if item and pathlib.Path(item).is_file()), None)
    context = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
    digest = hashlib.sha256()
    observed = 0
    with urllib.request.urlopen(request, timeout=60, context=context) as response, destination.open(
        "wb"
    ) as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            observed += len(chunk)
            if observed > MODEL_SIZE_BYTES:
                raise ValueError("model canary download exceeded the pinned size")
            digest.update(chunk)
            handle.write(chunk)
    if observed != MODEL_SIZE_BYTES:
        raise ValueError(
            f"model canary size mismatch: expected {MODEL_SIZE_BYTES}, observed {observed}"
        )
    observed_digest = digest.hexdigest()
    if observed_digest != MODEL_SHA256:
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
        "--no-conversation",
        "--single-turn",
        "--simple-io",
        "--no-warmup",
        "-t",
        "2",
    ]


def run_canary(binary: pathlib.Path, model: pathlib.Path) -> Dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(
        canary_command(binary, model),
        cwd=binary.parent,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    elapsed = round(time.monotonic() - started, 3)
    generated = completed.stdout.strip()
    if completed.returncode != 0:
        detail = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
        raise ValueError(
            f"legacy model canary failed with exit {completed.returncode}: {detail[-500:]}"
        )
    if not generated:
        raise ValueError("legacy model canary produced no generated text")
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
) -> Dict[str, Any]:
    validate_archive_receipt(archive_receipt)
    binary = locate_llama_cli(runtime_dir)
    with tempfile.TemporaryDirectory(prefix="infergrade-llama-model-canary-") as tmp:
        model_path = pathlib.Path(tmp) / MODEL_FILENAME
        downloaded_digest = download_model(model_path)
        execution = run_canary(binary, model_path)
    receipt = {
        "receipt_version": 1,
        "candidate_only": True,
        "canary_id": "legacy_llama_tiny_generation_v1",
        "status": "passed",
        "proof_scope": "legacy_llama_model_load_and_generation",
        "model_compatibility": "legacy_control_only",
        "claim_boundary": (
            "This tiny synthetic llama-architecture canary proves one GGUF load and generation path only. "
            "It does not prove recent architectures, chat templates, benchmark behavior, performance, or support promotion."
        ),
        "runtime": {
            "release": archive_receipt.get("upstream", {}).get("release"),
            "platform": archive_receipt.get("platform"),
            "archive_sha256": archive_receipt.get("artifact", {}).get("downloaded_sha256"),
            "version_smoke": archive_receipt.get("version_smoke", {}).get("status"),
        },
        "model": {
            "repository": MODEL_REPOSITORY,
            "revision": MODEL_REVISION,
            "filename": MODEL_FILENAME,
            "size_bytes": MODEL_SIZE_BYTES,
            "expected_sha256": MODEL_SHA256,
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
    parser.add_argument("--output", type=pathlib.Path, required=True)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        receipt = verify(args.runtime_dir, load_json(args.archive_receipt), args.output)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError, urllib.error.URLError) as exc:
        print(f"llama.cpp model canary failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
