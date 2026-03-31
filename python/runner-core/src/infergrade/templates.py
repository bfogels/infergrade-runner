from typing import Any, Dict

from infergrade.constants import DEFAULT_GENERATION_PRESET
from infergrade.run_configs import build_run_config_document
from infergrade.utils import dump_simple_yaml


def build_run_request_template(
    model: str = "Qwen/Qwen2.5-7B-Instruct",
    backend: str = "llama.cpp",
    tier: str = "canary",
    use_case: str = None,
) -> Dict[str, Any]:
    if tier in ("standard", "gold") and not use_case:
        use_case = "general_assistant"
    payload: Dict[str, Any] = {
        "spec_version": "0.1-draft",
        "run": {
            "model": model,
            "backend": backend,
            "tier": tier,
        },
    }
    if use_case:
        payload["run"]["use_case"] = use_case
    if backend == "llama.cpp":
        payload["runtime"] = {"backend_image": "infergrade-llama-cpp:local"}
        if model == "Qwen/Qwen2.5-7B-Instruct":
            payload["artifacts"] = {
                "quantized_weights": {
                    "uri": "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
                    "filename": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
                }
            }
    if tier != "canary":
        payload["overrides"] = {"generation_preset": DEFAULT_GENERATION_PRESET}
        payload["cost"] = {"source": "estimated"}
    return payload


def render_run_request_template(
    model: str = "Qwen/Qwen2.5-7B-Instruct",
    backend: str = "llama.cpp",
    tier: str = "canary",
    use_case: str = None,
    output_format: str = "yaml",
) -> str:
    payload = build_run_request_template(model=model, backend=backend, tier=tier, use_case=use_case)
    if output_format == "json":
        import json

        return json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return dump_simple_yaml(payload) + "\n"


def render_run_config_template(
    name: str = "General assistant canary run",
    model: str = "Qwen/Qwen2.5-7B-Instruct",
    backend: str = "llama.cpp",
    tier: str = "canary",
    use_case: str = None,
    output_format: str = "json",
) -> str:
    request_payload = build_run_request_template(
        model=model,
        backend=backend,
        tier=tier,
        use_case=use_case,
    )
    payload = build_run_config_document(request_payload=request_payload, name=name)
    if output_format == "json":
        import json

        return json.dumps(payload, indent=2, sort_keys=True) + "\n"
    return dump_simple_yaml(payload) + "\n"
