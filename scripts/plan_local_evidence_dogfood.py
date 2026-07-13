#!/usr/bin/env python3
"""Generate local evidence dogfood request files without storing secrets.

The script is intentionally a planner, not an uploader. It writes request files
and a command sheet under ``runs/`` so maintainers can execute real local GGUF
runs while keeping pairing codes, tokens, model weights, and large artifacts out
of git.
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
PYTHON_SRC = ROOT_DIR / "python" / "runner-core" / "src"
if str(PYTHON_SRC) not in sys.path:
    sys.path.insert(0, str(PYTHON_SRC))

from infergrade import __version__  # noqa: E402
from infergrade.benchmark_catalog import check_index, load_capability_catalog  # noqa: E402
from infergrade.constants import DEFAULT_GENERATION_PRESET  # noqa: E402


DOGFOOD_PLAN_VERSION = "infergrade.local_evidence_dogfood.v1"
DEFAULT_OUTPUT_ROOT = ROOT_DIR / "runs" / "local_evidence_dogfood"

LANE_PLANS = [
    {
        "lane_id": "deployment_interactive_measurement",
        "label": "Interactive deployment speed, output length, and stop semantics",
        "use_case": None,
        "capability": "none",
        "deployment_warmup_runs": 2,
        "deployment_measured_runs": 5,
        "capability_suite_ids": [],
        "benchmark_check_ids": ["interactive_chat_v1"],
        "claim_boundary": "Fixed-prompt deployment throughput and output-length evidence; natural stopping is not semantic correctness or scored task completion.",
    },
    {
        "lane_id": "local_core_decision",
        "label": "Deployment plus thin local assistant/coding/reasoning samples",
        "use_case": "general_assistant",
        "capability_suite_ids": ["chat_instruction_following", "coding_code_editing"],
        "benchmark_check_ids": [
            "interactive_chat_v1",
            "multiturn_chat_memory_v1",
            "coding_static_repair_v1",
            "reasoning_exact_answer_v1",
        ],
        "claim_boundary": "Real local development evidence for setup guidance; thin local samples are not reference, gold, or leaderboard evidence.",
    },
    {
        "lane_id": "mmlu_pro_sampled_reference",
        "label": "MMLU-Pro sampled reference",
        "use_case": "general_assistant",
        "capability_suite_ids": ["chat_instruction_following"],
        "benchmark_check_ids": ["mmlu_pro_reference_v1"],
        "claim_boundary": "Sampled MMLU-Pro reference evidence; not gold evidence, leaderboard-grade evidence, or global intelligence proof.",
    },
    {
        "lane_id": "evalplus_humaneval_reference",
        "label": "EvalPlus HumanEval+ executable coding reference",
        "use_case": "agentic_coding",
        "capability_suite_ids": ["coding_code_editing"],
        "benchmark_check_ids": ["evalplus_humaneval"],
        "claim_boundary": "HumanEval+ pass@1 reference evidence; not LiveCodeBench, SWE-bench, repo-edit proof, gold, or broad agentic coding proof.",
    },
    {
        "lane_id": "evalplus_mbpp_reference",
        "label": "EvalPlus MBPP+ executable coding reference",
        "use_case": "agentic_coding",
        "capability_suite_ids": ["coding_code_editing"],
        "benchmark_check_ids": ["evalplus_mbpp"],
        "claim_boundary": "MBPP+ pass@1 reference evidence; not LiveCodeBench, SWE-bench, repo-edit proof, gold, or broad agentic coding proof.",
    },
    {
        "lane_id": "quant_fidelity_reference",
        "label": "Same-family quant-fidelity reference",
        "use_case": None,
        "capability_suite_ids": ["quant_fidelity"],
        "benchmark_check_ids": ["perplexity_reference_v1"],
        "claim_boundary": "Same-family quant-fidelity reference evidence only; not a cross-family model-quality or general capability score.",
    },
]


MATRIX_TEMPLATE = {
    "matrix_id": "apple_silicon_dogfood_YYYYMMDD",
    "hardware_label": "Apple Silicon maintainer machine",
    "notes": "Keep this file local if it contains absolute paths.",
    "models": [
        {
            "slot": "small_fast",
            "model_family": "replace-me",
            "checkpoint": "replace-me",
            "gguf_path": "/absolute/path/to/model.gguf",
            "quantization_scheme": "Q4_K_M",
            "source_uri": "hf://publisher/repo/file.gguf",
            "source_revision": None,
            "include_lanes": ["local_core_decision", "mmlu_pro_sampled_reference"],
        },
        {
            "slot": "same_family_q5",
            "model_family": "replace-me",
            "checkpoint": "replace-me",
            "gguf_path": "/absolute/path/to/model-q5_k_m.gguf",
            "quantization_scheme": "Q5_K_M",
            "source_uri": "hf://publisher/repo/file-q5_k_m.gguf",
            "source_revision": None,
            "include_lanes": ["local_core_decision", "quant_fidelity_reference"],
        },
    ],
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-._")
    return normalized or "item"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_filename_from_uri(uri: Optional[str]) -> Optional[str]:
    if not uri:
        return None
    normalized = str(uri).rstrip("/")
    if not normalized:
        return None
    return normalized.rsplit("/", 1)[-1] or None


def clean_optional_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text or text in {"pinned-or-unspecified", "replace-me"}:
        return None
    return text


def load_matrix(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Dogfood matrix must be a JSON object.")
    models = payload.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("Dogfood matrix must include a non-empty models list.")
    return payload


def requested_lanes(model: Dict[str, Any]) -> List[Dict[str, Any]]:
    requested = model.get("include_lanes") or [item["lane_id"] for item in LANE_PLANS]
    requested_ids = {str(item) for item in requested}
    lanes = [item for item in LANE_PLANS if item["lane_id"] in requested_ids]
    unknown = sorted(requested_ids - {item["lane_id"] for item in LANE_PLANS})
    if unknown:
        raise ValueError("Unknown dogfood lane(s) for %s: %s" % (model.get("slot") or model.get("gguf_path"), ", ".join(unknown)))
    return lanes


def validate_lane_plans() -> None:
    checks = check_index(load_capability_catalog(ROOT_DIR))
    missing = sorted(
        check_id
        for lane in LANE_PLANS
        for check_id in lane["benchmark_check_ids"]
        if check_id not in checks
    )
    if missing:
        raise ValueError("Dogfood lane references unknown benchmark check(s): %s" % ", ".join(missing))


def model_provenance(model: Dict[str, Any], compute_sha256: bool) -> Dict[str, Any]:
    raw_gguf_path = str(model.get("gguf_path") or "").strip()
    source_uri = clean_optional_text(model.get("source_uri"))
    if not raw_gguf_path and not source_uri:
        raise ValueError("Dogfood model %s must set gguf_path or source_uri." % (model.get("slot") or model.get("checkpoint") or "unknown"))
    gguf_path = Path(raw_gguf_path).expanduser() if raw_gguf_path else Path()
    exists = bool(raw_gguf_path) and gguf_path.exists()
    artifact_uri = str(gguf_path) if exists else (source_uri or str(gguf_path))
    artifact_filename = gguf_path.name if exists else artifact_filename_from_uri(artifact_uri)
    sha256 = None
    if compute_sha256 and exists and gguf_path.is_file():
        sha256 = sha256_file(gguf_path)
    return {
        "slot": model.get("slot"),
        "model_family": model.get("model_family"),
        "checkpoint": model.get("checkpoint"),
        "gguf_path": str(gguf_path),
        "gguf_filename": artifact_filename,
        "gguf_exists": exists,
        "artifact_uri_for_request": artifact_uri,
        "artifact_sha256": sha256 or clean_optional_text(model.get("artifact_sha256")),
        "quantization_scheme": model.get("quantization_scheme"),
        "source_uri": source_uri,
        "source_revision": clean_optional_text(model.get("source_revision")),
    }


def request_payload(model: Dict[str, Any], provenance: Dict[str, Any], lane: Dict[str, Any], output_dir: Path) -> Dict[str, Any]:
    run_payload: Dict[str, Any] = {
        "model": model.get("model") or provenance.get("checkpoint") or provenance.get("model_family") or "local-gguf",
        "backend": "llama.cpp",
        "tier": "standard",
        "capability": lane.get("capability", "auto"),
        "capability_suite_ids": list(lane["capability_suite_ids"]),
        "benchmark_check_ids": list(lane["benchmark_check_ids"]),
        "execution_mode": "local_native",
        "output_dir": str(output_dir),
    }
    if lane.get("use_case"):
        run_payload["use_case"] = lane["use_case"]
    if lane.get("deployment_warmup_runs") is not None:
        run_payload["deployment_warmup_runs"] = lane["deployment_warmup_runs"]
    if lane.get("deployment_measured_runs") is not None:
        run_payload["deployment_measured_runs"] = lane["deployment_measured_runs"]
    artifacts = {
        "quantized_weights": {
            "uri": provenance["artifact_uri_for_request"],
            "filename": provenance["gguf_filename"],
            "sha256": provenance.get("artifact_sha256"),
            "revision": provenance.get("source_revision"),
        }
    }
    return {
        "spec_version": "0.1-draft",
        "run": run_payload,
        "artifacts": artifacts,
        "runtime": {
            "artifact_cache_dir": "~/.cache/infergrade/artifacts",
        },
        "overrides": {
            "generation_preset": model.get("generation_preset") or DEFAULT_GENERATION_PRESET,
        },
        "ontology_hints": {
            "family_name": provenance.get("model_family"),
            "checkpoint_name": provenance.get("checkpoint"),
            "quantization_family": "gguf",
            "quantization_scheme": provenance.get("quantization_scheme"),
        },
        "metadata": {
            "evidence_source": "agent_dogfood",
            "notes": "Maintainer-run evidence. %s" % lane["claim_boundary"],
        },
    }


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def command_for_request(request_path: Path, repo_root: Path) -> str:
    rel_request = os.path.relpath(request_path, repo_root)
    return "PYTHONPATH=python/runner-core/src python3 -m infergrade run --request-file %s --real-run" % shlex.quote(rel_request)


def upload_command_for_bundle(bundle_dir: Path, repo_root: Path) -> str:
    rel_bundle = os.path.relpath(bundle_dir, repo_root)
    return "PYTHONPATH=python/runner-core/src python3 -m infergrade upload-bundle %s --api-url \"${INFERGRADE_API_URL:-https://api.infergrade.com}\"" % shlex.quote(rel_bundle)


def generate_plan(matrix: Dict[str, Any], output_root: Path, compute_sha256: bool) -> Dict[str, Any]:
    output_root = Path(output_root)
    validate_lane_plans()
    created_at = utcnow_iso()
    plan_root = output_root / slugify(str(matrix.get("matrix_id") or "local-evidence-dogfood"))
    request_root = plan_root / "requests"
    bundle_root = plan_root / "bundles"
    commands: List[str] = []
    upload_commands: List[str] = []
    model_entries: List[Dict[str, Any]] = []

    for model in list(matrix.get("models") or []):
        provenance = model_provenance(model, compute_sha256=compute_sha256)
        model_slug = slugify("%s-%s-%s" % (provenance.get("slot") or "model", provenance.get("checkpoint") or "checkpoint", provenance.get("quantization_scheme") or "quant"))
        lane_entries = []
        for lane in requested_lanes(model):
            lane_slug = slugify(lane["lane_id"])
            bundle_dir = bundle_root / model_slug / lane_slug
            request_path = request_root / model_slug / ("%s.json" % lane_slug)
            payload = request_payload(model, provenance, lane, bundle_dir)
            write_json(request_path, payload)
            commands.append(command_for_request(request_path, ROOT_DIR))
            upload_commands.append(upload_command_for_bundle(bundle_dir, ROOT_DIR))
            lane_entries.append(
                {
                    "lane_id": lane["lane_id"],
                    "label": lane["label"],
                    "benchmark_check_ids": list(lane["benchmark_check_ids"]),
                    "request_path": os.path.relpath(request_path, plan_root),
                    "bundle_output_dir": os.path.relpath(bundle_dir, plan_root),
                    "claim_boundary": lane["claim_boundary"],
                }
            )
        model_entries.append({"provenance": provenance, "lanes": lane_entries})

    manifest = {
        "artifact_kind": "local_evidence_dogfood_plan",
        "plan_version": DOGFOOD_PLAN_VERSION,
        "created_at": created_at,
        "runner_version": __version__,
        "matrix_id": matrix.get("matrix_id"),
        "hardware_label": matrix.get("hardware_label"),
        "evidence_honesty": [
            "Maintainer-run evidence is real local evidence from the named machine, not official validation.",
            "Thin local samples are setup guidance, not broad capability proof.",
            "Reference samples remain reference evidence, not gold or leaderboard-grade evidence.",
            "Quant-fidelity evidence is comparable only within the same family/checkpoint/tokenizer/corpus/protocol boundary.",
        ],
        "secret_policy": [
            "Do not put pairing codes, runner tokens, bearer tokens, or upload tokens in this plan.",
            "Do not commit generated requests or bundles if they contain local paths, raw outputs, or large artifacts.",
        ],
        "models": model_entries,
    }
    write_json(plan_root / "dogfood_manifest.json", manifest)
    (plan_root / "commands.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n\ncd %s\n\n%s\n" % (shlex.quote(str(ROOT_DIR)), "\n".join(commands)),
        encoding="utf-8",
    )
    (plan_root / "upload_commands.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n\ncd %s\n\n%s\n" % (shlex.quote(str(ROOT_DIR)), "\n".join(upload_commands)),
        encoding="utf-8",
    )
    return {
        "plan_root": str(plan_root),
        "manifest_path": str(plan_root / "dogfood_manifest.json"),
        "request_count": len(commands),
        "commands_path": str(plan_root / "commands.sh"),
        "upload_commands_path": str(plan_root / "upload_commands.sh"),
    }


def write_template(path: Path) -> Dict[str, str]:
    path = Path(path)
    write_json(path, MATRIX_TEMPLATE)
    return {"template_path": str(path)}


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate local evidence dogfood request files.")
    parser.add_argument("--matrix-file", help="JSON file describing local GGUFs to dogfood.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="Directory for generated plan files. Default stays under ignored runs/.")
    parser.add_argument("--init-matrix", help="Write a starter matrix JSON template and exit.")
    parser.add_argument("--skip-sha256", action="store_true", help="Do not hash GGUF files while generating requests.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    if args.init_matrix:
        print(json.dumps(write_template(Path(args.init_matrix)), indent=2, sort_keys=True))
        return 0
    if not args.matrix_file:
        raise SystemExit("--matrix-file is required unless --init-matrix is used.")
    matrix = load_matrix(Path(args.matrix_file))
    result = generate_plan(matrix, Path(args.output_root), compute_sha256=not args.skip_sha256)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
