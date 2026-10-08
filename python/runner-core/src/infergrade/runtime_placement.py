"""Bounded local allocation artifacts; requested placement is never observation."""

import json
import os
import re
import shlex
import uuid
from functools import lru_cache

from infergrade.json_schema_subset import validate_json_schema
from infergrade.paths import runner_root
from infergrade.native_cuda_devices import frozen

from infergrade.utils import stable_hash, write_json


_DEVICE = r"(?:CUDA[0-9]{1,3}(?:_Mapped)?|Vulkan[0-9]{1,3}|MTL[0-9]{1,3}(?:_Mapped)?|Metal[0-9]{0,3}(?:_Mapped)?|CPU_Mapped|CPU)"
_BUFFER = re.compile(
    rf"(?:load_tensors|llama_model_load|llama_kv_cache[^ :]*):\s*(?P<device>{_DEVICE})\s+(?P<kind>model|KV)\s+buffer size\s*=\s*"
    r"(?P<size>[0-9.]+)\s*(?P<unit>[KMGT]i?B)\b", re.IGNORECASE,
)
_LAYERS = re.compile(r"(?:load_tensors|llama_model_load[^ :]*):\s*offloaded\s+([0-9]{1,10})/([0-9]{1,10})\s+layers\b")
_CONTEXT = re.compile(r"(?:llama_context|llama_new_context_with_model|generate):[^\n]*?\bn_ctx\s*=\s*([0-9]{1,10})\b")
_SEQUENCE_CONTEXT = re.compile(r"(?:llama_context|llama_new_context_with_model):[^\n]*?\bn_ctx_per_seq\s*=\s*([0-9]{1,10})\b")


def _unique_number(pattern, logs):
    values = {int(match.group(1)) for match in pattern.finditer(logs)}
    values = {value for value in values if 0 < value <= 2**31 - 1}
    return (next(iter(values)) if len(values) == 1 else None), len(values) > 1


def _arguments(command):
    # Perplexity containers use a shell entrypoint. Extract only recognized
    # placement options below; never retain commands, model paths or prompts.
    if "-lc" in command:
        index = command.index("-lc")
        try:
            command = shlex.split(command[index + 1])
        except (IndexError, ValueError):
            return []
    arguments = []
    skip = False
    for token in command:
        if skip:
            skip = False
            continue
        if token in ("--model", "-m", "--prompt", "-p", "--file", "-f", "--env", "-e"):
            skip = True
            continue
        arguments.append(token)
    return arguments


def _option(arguments, names):
    result = None
    for index, token in enumerate(arguments):
        for name in names:
            if token == name and index + 1 < len(arguments):
                result = str(arguments[index + 1])
            elif token.startswith(name + "="):
                result = token[len(name) + 1:]
    return result


def parse_runtime_placement(logs, command):
    """Read complete invocation logs, retaining only bounded numeric evidence."""
    logs = str(logs or "")
    reasons = []
    pairs = {(int(a), int(b)) for a, b in _LAYERS.findall(logs)}
    valid_layers = len(pairs) == 1 and all(0 <= a <= b <= 2**31 - 1 and b > 0 for a, b in pairs)
    offloaded, total = next(iter(pairs)) if valid_layers else (None, None)
    if pairs and not valid_layers:
        reasons.append("contradictory_layer_evidence")
    context, context_conflict = _unique_number(_CONTEXT, logs)
    sequence_context, sequence_conflict = _unique_number(_SEQUENCE_CONTEXT, logs)
    if context_conflict or sequence_conflict:
        reasons.append("contradictory_context_evidence")
    allocations = set()
    for match in _BUFFER.finditer(logs):
        unit = match.group("unit")
        exponent = "KMGT".index(unit[0].upper()) + 1
        try:
            size = float(match.group("size")) * (1024 if "i" in unit.lower() else 1000)**exponent
        except ValueError:
            continue
        if not 0 <= size <= 2**63 - 1:
            continue
        raw_device = match.group("device")
        device = re.sub(r"(?i)^metal", "Metal", raw_device) if raw_device.lower().startswith("metal") else raw_device.upper()
        device = re.sub(r"(?i)_mapped$", "_Mapped", device)
        if device == "CPU_MAPPED":
            device = "CPU_Mapped"
        allocations.add((device, match.group("kind").lower(), int(round(size))))
    truncated = len(allocations) > 128
    buffers = [
        {"device": device, "kind": kind, "bytes": size}
        for device, kind, size in sorted(allocations)[:128]
    ]
    devices = sorted({re.sub(r"_Mapped$", "", item["device"]) for item in buffers
                      if item["kind"] == "model" and item["bytes"] > 0
                      and not item["device"].startswith("CPU")})
    classification = "unknown"
    if valid_layers:
        if offloaded == 0 and devices:
            reasons.append("contradictory_device_layer_evidence")
        elif offloaded == 0:
            classification = "no_reported_layers_offloaded"
        elif offloaded == total:
            classification = "all_reported_layers_offloaded"
        else:
            classification = "partial_layer_offload"
    if truncated:
        reasons.append("allocation_evidence_truncated")
    if not devices:
        reasons.append("gpu_model_allocation_devices_unknown")
    if offloaded is None:
        reasons.append("layer_counts_unknown")
    if context is None:
        reasons.append("runtime_context_unknown")
    arguments = _arguments(command)
    fit = _option(arguments, ("--fit",))
    requested_context = _option(arguments, ("--ctx-size", "-c"))
    requested_layers = _option(arguments, ("--n-gpu-layers", "--gpu-layers", "-ngl"))
    device_option = _option(arguments, ("--device", "-dev"))
    requested_devices = None
    if device_option and len(device_option) <= 256:
        labels = device_option.split(",")
        if len(labels) <= 16 and all(re.fullmatch(_DEVICE + r"|none", label) for label in labels):
            requested_devices = labels
    split = _option(arguments, ("--split-mode", "-sm"))
    main_gpu = _option(arguments, ("--main-gpu", "-mg"))
    tensor_split = _option(arguments, ("--tensor-split", "-ts"))
    if not (tensor_split and len(tensor_split) <= 128 and
            re.fullmatch(r"[0-9]+(?:\.[0-9]+)?(?:,[0-9]+(?:\.[0-9]+)?){0,15}", tensor_split)):
        tensor_split = None
    return {
        "artifact_format": "llama_cpp_placement_artifact_v1",
        "evidence_source": "runtime_log_buffer_and_layer_markers",
        "fit_argument": fit if fit in ("on", "off") else None,
        "requested_context_tokens": int(requested_context)
        if requested_context and re.fullmatch(r"[0-9]{1,9}", requested_context) else None,
        "requested_gpu_layers": int(requested_layers)
        if requested_layers and re.fullmatch(r"-?[0-9]{1,9}", requested_layers) else None,
        "requested_devices": requested_devices,
        "requested_split_mode": split if split in ("none", "layer", "row") else None,
        "requested_main_gpu_index": int(main_gpu)
        if main_gpu and re.fullmatch(r"[0-9]{1,3}", main_gpu) else None,
        "requested_tensor_split": tensor_split,
        "observed_context_tokens": context,
        "observed_context_per_sequence_tokens": sequence_context,
        "offloaded_layers": offloaded,
        "total_layers": total,
        "layer_placement": classification,
        "gpu_devices_with_positive_model_buffers": devices or None,
        "allocations": buffers,
        "allocation_evidence_truncated": truncated,
        "reason_codes": reasons,
        "claim_boundary": "Runtime buffer sizes are not RSS or VRAM. All layers offloaded does not prove zero CPU/RAM use.",
    }


def record_runtime_placement(request, command, logs, role):
    """Persist a separate receipt for each invocation, including unknown evidence."""
    receipt = parse_runtime_placement(logs, command)
    receipt["role"] = role
    accelerator = (request.runtime_selector or {}).get("accelerator") or {}
    receipt["requested_accelerator_api"] = accelerator.get("api") if accelerator.get("api") in (
        "cpu", "cuda", "metal", "vulkan", "rocm", "opencl", "sycl",
    ) else None
    selection = frozen(request)
    if selection:
        receipt["native_device_policy_fingerprint"] = selection.fingerprint
        receipt["requested_accelerator_api"] = "cuda"
    receipt["placement_fingerprint"] = stable_hash(receipt, length=64)
    receipt["invocation_id"] = uuid.uuid4().hex
    relative_path = os.path.join("artifacts", "runtime-placement", receipt["invocation_id"] + ".json")
    if request.output_dir:
        path = os.path.join(request.output_dir, relative_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_json(path, receipt)
    return receipt


@lru_cache(maxsize=1)
def _runtime_placement_schema():
    path = runner_root() / "schemas" / "json" / "runtime_placement.schema.json"
    return json.loads(path.read_text()), path


def validated_runtime_placement(receipt):
    """Return the exact path-free local shape only when its digest validates."""
    if not isinstance(receipt, dict):
        return None
    try:
        schema, path = _runtime_placement_schema()
    except (OSError, ValueError):
        return None
    if validate_json_schema(receipt, schema, path):
        return None
    payload = {key: value for key, value in receipt.items()
               if key not in ("invocation_id", "placement_fingerprint")}
    if stable_hash(payload, length=64) != receipt["placement_fingerprint"]:
        return None
    return json.loads(json.dumps(receipt))


def merge_runtime_placement_receipts(groups):
    """Bound deduplicated invocations, excluding conflicting ID reuse."""
    receipts, conflicts = {}, set()
    complete = True
    for group in groups:
        for candidate in group:
            receipt = validated_runtime_placement(candidate)
            if receipt is None:
                complete = False
                continue
            invocation = receipt["invocation_id"]
            if invocation in conflicts:
                continue
            if invocation in receipts and receipts[invocation] != receipt:
                conflicts.add(invocation)
                receipts.pop(invocation)
                complete = False
                continue
            receipts[invocation] = receipt
    if len(receipts) > 128:
        complete = False
    return [receipts[key] for key in sorted(receipts)[:128]], complete
