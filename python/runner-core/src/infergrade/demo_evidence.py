"""Runner-owned demo evidence fixtures for report and contract tests."""

from typing import Any, Dict, List


DEMO_SOURCE_ORIGIN = "infergrade_demo_fixture"
DEMO_SUBMITTER = "infergrade-demo"


def tinyllama_demo_quant_ladder_results(bundle_id: str = "demo_tinyllama_assistant_quant_ladder") -> List[Dict[str, Any]]:
    """Return a small synthetic TinyLlama quant ladder using the result-record contract."""
    return [
        _result(bundle_id, "demo_tinyllama_q4_k_m", "Q4_K_M", "q4_k_m", 4, 24.0, 880.0, 1350.0, 0.74, 5.7),
        _result(bundle_id, "demo_tinyllama_q5_k_m", "Q5_K_M", "q5_k_m", 5, 21.5, 940.0, 1480.0, 0.77, 5.35),
        _result(bundle_id, "demo_tinyllama_q8_0", "Q8_0", "q8_0", 8, 14.0, 1180.0, 1820.0, 0.79, 5.05),
    ]


def _result(
    bundle_id: str,
    result_id: str,
    quantization_label: str,
    quantization_scheme: str,
    weight_precision_bits: int,
    decode_tokens_per_second_p50: float,
    ttft_p50_ms: float,
    load_time_ms: float,
    capability_score: float,
    perplexity: float,
) -> Dict[str, Any]:
    return {
        "spec_version": "0.1-draft",
        "bundle_id": bundle_id,
        "result_id": result_id,
        "ontology": {
            "model_family": {"family_name": "TinyLlama", "parameter_scale": "1.1B"},
            "checkpoint": {"checkpoint_name": "TinyLlama-1.1B-Chat-v1.0", "training_stage": "instruction_tuned"},
            "quantization": {
                "quantization_label": quantization_label,
                "quantization_family": "k_quant",
                "quantization_scheme": quantization_scheme,
                "weight_precision_bits": weight_precision_bits,
            },
            "artifact": {"artifact_id": "artifact-%s" % result_id},
            "runtime_binding": {"runtime_binding_id": "binding-%s" % result_id},
            "benchmark_subject": {"subject_id": "subject-%s" % result_id},
        },
        "configuration": {
            "configuration_id": "cfg-%s" % result_id,
            "model_base": "tinyllama-1.1b-chat-v1.0",
            "model_source": "demo_fixture",
            "backend_engine": "llama.cpp",
            "backend_version": "version: demo-fixture",
            "benchmark_selection": {
                "benchmark_scope": {
                    "scope": "decision",
                    "scope_label": "Decision suite",
                    "metadata_confidence": "unknown",
                    "metadata_sources": {
                        "duration": "estimated",
                        "token_volume": "estimated",
                        "failure_rate": "unknown",
                        "calibration_status": "estimated_static_catalog_v1",
                    },
                },
                "benchmark_check_ids": ["interactive_chat_v1"],
            },
        },
        "hardware": {
            "hardware_id": "hw-%s" % result_id,
            "environment_class": "local_workstation",
            "accelerator_type": "gpu",
            "accelerator_count": 1,
            "hardware_class": "nvidia_gpu",
            "accelerator_vendor": "nvidia",
            "accelerator_model": "RTX 4090 demo lane",
            "accelerator_vram_gb": 24.0,
            "memory_gb": 64.0,
            "system_ram_gb": 64.0,
            "cpu_model": "demo fixture",
            "os": "Linux",
        },
        "verification": {
            "verification_level": "experimental",
            "artifact_pinned": True,
            "backend_version_pinned": True,
            "hardware_captured": True,
            "missing_requirements": [],
            "local_comparison_grade_candidate": "informational_only",
        },
        "execution": {
            "execution_profile_id": "local_container_v1",
            "execution_mode": "local_container",
            "started_at": "2026-04-21T00:00:00Z",
            "completed_at": "2026-04-21T00:01:00Z",
            "benchmark_job_runtime_seconds": 60,
            "execution_cost_source": "none",
            "simulated": True,
        },
        "deployment": {
            "deployment_profile_id": "interactive_chat_v1",
            "deployment_status": "simulated",
            "ttft_p50_ms": ttft_p50_ms,
            "decode_tokens_per_second_p50": decode_tokens_per_second_p50,
            "load_time_ms": load_time_ms,
            "peak_vram_mb": None,
            "oom_or_failure_rate": 0.0,
        },
        "capability": {
            "use_case": "general_assistant",
            "capability_suite_id": "demo_decision_suite",
            "benchmark_tier": "canary",
            "capability_state": "scored",
            "capability_score": capability_score,
            "capability_status": "completed",
        },
        "cost": {
            "cost_source": "none",
            "benchmark_job_cost_included": False,
            "benchmark_job_cost_usd": None,
        },
        "fidelity": {
            "fidelity_state": "measured",
            "perplexity": {"metric_name": "perplexity", "value": perplexity, "status": "measured"},
        },
        "derived": {"comparison_grade": "informational_only", "demo_evidence": True},
        "provenance": {
            "submitter": DEMO_SUBMITTER,
            "source_bundle_origin": DEMO_SOURCE_ORIGIN,
            "normalized_at": "2026-04-21T00:01:00Z",
            "normalizer_version": "0.1.0",
        },
    }
