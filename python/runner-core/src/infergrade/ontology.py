import hashlib
import os
import re
from typing import Any, Dict, Optional, Tuple

from infergrade.models import RunRequest
from infergrade.quant_identity import (
    ONTOLOGY_IDENTITY_VERSION,
    artifact_source_identity_payload,
    infer_artifact_source,
    quantization_identity,
)
from infergrade.utils import slugify, stable_hash


_PARAMETER_SCALE_RE = re.compile(r"-(\d+(?:\.\d+)?)b(?:-|$)", re.IGNORECASE)
_WEIGHT_PRECISION_RE = re.compile(
    r"(?:i?q|int|w|(?:nv|mx)?fp|bf)(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
def resolve_quant_format(artifact: str, backend: str) -> Optional[str]:
    if artifact:
        lowered = artifact.lower()
        if lowered.endswith(".gguf"):
            return "gguf"
        if ".awq" in lowered or "awq" in lowered:
            return "awq"
        if ".gptq" in lowered or "gptq" in lowered:
            return "gptq"
        if lowered.endswith(".safetensors"):
            return "safetensors"
    if backend == "vllm":
        return "safetensors"
    return None


def resolve_artifact_sha256(artifact: Optional[str]) -> Optional[str]:
    if not artifact or not os.path.isfile(artifact):
        return None
    digest = hashlib.sha256()
    with open(artifact, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _split_model_ref(model_ref: str) -> Tuple[Optional[str], str]:
    cleaned = model_ref.replace("hf://", "").strip("/")
    parts = [part for part in cleaned.split("/") if part]
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    if parts:
        return None, parts[-1]
    return None, model_ref


def _infer_family_name(checkpoint_name: str) -> str:
    match = _PARAMETER_SCALE_RE.search(checkpoint_name)
    if not match:
        return checkpoint_name
    family = checkpoint_name[: match.start()].rstrip("-_ /")
    return family or checkpoint_name


def _infer_parameter_scale(checkpoint_name: str) -> Optional[str]:
    match = _PARAMETER_SCALE_RE.search(checkpoint_name)
    if not match:
        return None
    return "%sB" % match.group(1).upper()


def _infer_training_stage(checkpoint_name: str) -> str:
    lowered = checkpoint_name.lower()
    if "reason" in lowered or "-r1" in lowered or "-r2" in lowered:
        return "reasoning_tuned"
    if "instruct" in lowered or "chat" in lowered:
        return "instruction_tuned"
    if "-base" in lowered or lowered.endswith("base"):
        return "base"
    if "coder" in lowered or "code" in lowered:
        return "domain_tuned"
    return "unknown"


def _infer_weight_precision_bits(quant_label: Optional[str]) -> Optional[float]:
    if not quant_label:
        return None
    match = _WEIGHT_PRECISION_RE.search(quant_label)
    if not match:
        return None
    return float(match.group(1))


def _infer_quantization_family(quant_label: Optional[str], quant_format: Optional[str]) -> Optional[str]:
    lowered = (quant_label or "").lower()
    if "awq" in lowered:
        return "awq"
    if "gptq" in lowered:
        return "gptq"
    if re.search(r"(?:^|_)q?\d+_k(?:_|$)", lowered):
        return "k_quant"
    if "iq" in lowered:
        return "i_quant"
    if lowered.startswith("int"):
        return "int_quant"
    if lowered.startswith("w") and "a" in lowered:
        return "weight_activation_quant"
    if lowered.startswith(("fp", "bf", "nvfp", "mxfp")):
        return "floating_point_quant"
    if quant_format == "gguf":
        return "gguf"
    return None


def _stable_named_id(prefix: str, primary_label: Optional[str], payload: Dict[str, Any]) -> str:
    label = slugify(primary_label or "")
    digest = stable_hash(payload, length=10)
    if label:
        return "%s_%s_%s" % (prefix, label, digest)
    return "%s_%s" % (prefix, digest)


def build_ontology(request: RunRequest, adapter_version: str) -> Dict[str, Any]:
    hints = dict(request.ontology_hints or {})
    publisher, checkpoint_name = _split_model_ref(request.model)
    family_name = hints.get("family_name") or _infer_family_name(checkpoint_name)
    parameter_scale = hints.get("parameter_scale") or _infer_parameter_scale(checkpoint_name)
    training_stage = hints.get("training_stage") or _infer_training_stage(checkpoint_name)
    quant_input = (
        request.quant_artifact_filename
        or request.quant_artifact
        or request.quant_artifact_resolved_path
        or (request.model if request.backend == "vllm" else "")
    )
    quant_label = hints.get("quantization_label") or (os.path.basename(quant_input) if quant_input else None)
    inferred_quant_format = next(
        (
            resolved
            for value in (
                request.quant_artifact,
                request.quant_artifact_filename,
                request.quant_artifact_resolved_path,
                request.model if request.backend == "vllm" else None,
            )
            for resolved in (resolve_quant_format(str(value), "") if value else None,)
            if resolved
        ),
        resolve_quant_format("", request.backend),
    )
    quant_format = hints.get("quantization_format") or inferred_quant_format
    quantization_status = "quantized" if request.quant_artifact else "unknown"
    quant_identity = quantization_identity(
        hints.get("quantization_scheme"),
        quant_label,
        quant_format,
        inferred_quant_format,
    )
    quantization_scheme = quant_identity["quantization_scheme"]
    quantization_family = hints.get("quantization_family") or _infer_quantization_family(
        quantization_scheme or quant_label,
        quant_format,
    )
    if quant_identity["quantization_id"]:
        quantization_status = "quantized"
    weight_precision_bits = hints.get("weight_precision_bits")
    if weight_precision_bits is None:
        weight_precision_bits = _infer_weight_precision_bits(quantization_scheme or quant_label)

    family_id = hints.get("family_id") or _stable_named_id(
        "fam",
        family_name,
        {"family_name": family_name, "publisher": hints.get("publisher") or publisher},
    )
    checkpoint_id = hints.get("checkpoint_id") or _stable_named_id(
        "ckpt",
        checkpoint_name,
        {"model_ref": request.model, "checkpoint_name": checkpoint_name},
    )
    artifact_reference = request.quant_artifact or request.model
    artifact_sha256 = (
        request.quant_artifact_sha256
        or resolve_artifact_sha256(request.quant_artifact_resolved_path)
        or resolve_artifact_sha256(request.quant_artifact)
    )
    artifact_source = infer_artifact_source(
        artifact_reference,
        request.quant_artifact_source,
        request.quant_artifact_revision,
        allow_plain_hf_repo=not request.quant_artifact and request.backend == "vllm",
    )
    artifact_source_id = _stable_named_id(
        "src",
        artifact_source.get("repository_id") or artifact_source.get("publisher"),
        artifact_source_identity_payload(artifact_source),
    ) if any(artifact_source.values()) else None
    artifact_id = _stable_named_id(
        "art",
        quant_label or checkpoint_name,
        {
            "artifact": artifact_reference,
            "quant_label": quant_label,
            "artifact_source": artifact_source_identity_payload(artifact_source),
        },
    )
    runtime_binding_id = _stable_named_id(
        "rt",
        request.backend,
        {
            "backend": request.backend,
            "backend_version": adapter_version,
            "execution_mode": request.execution_mode,
            "backend_flags": list(request.backend_flags or []),
            "generation_preset": request.generation_preset,
        },
    )
    subject_id = _stable_named_id(
        "subj",
        checkpoint_name,
        {
            "checkpoint_id": checkpoint_id,
            "artifact_id": artifact_id,
            "runtime_binding_id": runtime_binding_id,
        },
    )

    return {
        "ontology_version": "0.1-draft",
        "ontology_identity_version": ONTOLOGY_IDENTITY_VERSION,
        "model_family": {
            "family_id": family_id,
            "family_name": family_name,
            "publisher": hints.get("publisher") or publisher,
            "parameter_scale": parameter_scale,
            "primary_modality": hints.get("primary_modality") or "text",
        },
        "checkpoint": {
            "checkpoint_id": checkpoint_id,
            "checkpoint_name": hints.get("checkpoint_name") or checkpoint_name,
            "upstream_model_ref": request.model,
            "upstream_revision": hints.get("upstream_revision") or "unspecified",
            "training_stage": training_stage,
        },
        "quantization": {
            "quantization_status": quantization_status,
            "quantization_format": quant_format,
            "quantization_label": quant_label,
            "quantization_family": quantization_family,
            "quantization_scheme": quantization_scheme,
            "quantization_scheme_raw": quant_identity["quantization_scheme_raw"],
            "quantization_id": quant_identity["quantization_id"],
            "canonicalization_status": quant_identity["canonicalization_status"],
            "canonicalization_version": quant_identity["canonicalization_version"],
            "weight_precision_bits": weight_precision_bits,
        },
        "artifact": {
            "artifact_id": artifact_id,
            "artifact_kind": "quantized_weights" if request.quant_artifact or quant_identity["quantization_id"] else "model_reference",
            "artifact_uri": artifact_reference,
            "artifact_filename": request.quant_artifact_filename or (os.path.basename(quant_input) if request.quant_artifact else None),
            "artifact_sha256": artifact_sha256,
            "artifact_source_id": artifact_source_id,
            "source": artifact_source,
            "artifact_resolved_by": "server_policy" if request.quant_artifact and request.run_config_id else ("operator" if request.quant_artifact else "runner_default"),
        },
        "runtime_binding": {
            "runtime_binding_id": runtime_binding_id,
            "backend_engine": request.backend,
            "backend_version": adapter_version,
            "backend_wrapper": None,
            "execution_mode": request.execution_mode,
            "backend_flags_hash": stable_hash(list(request.backend_flags or [])),
            "generation_preset_id": request.generation_preset,
        },
        "benchmark_subject": {
            "subject_id": subject_id,
            "subject_kind": "artifact_runtime_binding",
            "family_id": family_id,
            "checkpoint_id": checkpoint_id,
            "artifact_id": artifact_id,
            "runtime_binding_id": runtime_binding_id,
            "comparison_scope": "deployable_quantized_model",
        },
    }
