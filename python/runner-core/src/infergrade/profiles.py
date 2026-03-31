from dataclasses import dataclass
from typing import Dict, List, Optional

from infergrade.capabilities import CAPABILITY_SUITES, resolve_capability_suite
from infergrade.constants import DEFAULT_GENERATION_PRESET


@dataclass(frozen=True)
class DeploymentProfile:
    profile_id: str
    description: str
    primary_metrics: List[str]


DEPLOYMENT_PROFILES: Dict[str, DeploymentProfile] = {
    "interactive_chat_v1": DeploymentProfile(
        profile_id="interactive_chat_v1",
        description="Interactive assistant responsiveness.",
        primary_metrics=[
            "ttft_p50_ms",
            "latency_p50_ms",
            "decode_tokens_per_second_p50",
            "peak_vram_mb",
            "load_time_ms",
        ],
    ),
    "batch_generation_v1": DeploymentProfile(
        profile_id="batch_generation_v1",
        description="Sustained throughput and batch cost efficiency.",
        primary_metrics=[
            "request_throughput_per_minute",
            "decode_tokens_per_second_p50",
            "peak_vram_mb",
            "latency_p50_ms",
        ],
    ),
    "long_context_v1": DeploymentProfile(
        profile_id="long_context_v1",
        description="Latency and memory pressure under longer contexts.",
        primary_metrics=[
            "ttft_p50_ms",
            "latency_p50_ms",
            "peak_vram_mb",
            "decode_tokens_per_second_p50",
        ],
    ),
}

DEFAULT_DEPLOYMENT_PROFILES = {
    "agentic_coding": ["interactive_chat_v1", "long_context_v1"],
    "general_assistant": ["interactive_chat_v1"],
    None: ["interactive_chat_v1"],
}

def resolve_deployment_profiles(use_case: Optional[str], requested: List[str]) -> List[str]:
    if requested:
        return requested
    return list(DEFAULT_DEPLOYMENT_PROFILES.get(use_case, DEFAULT_DEPLOYMENT_PROFILES[None]))


def resolve_generation_preset(requested: Optional[str]) -> str:
    return requested or DEFAULT_GENERATION_PRESET


def resolve_capability_behavior(tier: str, use_case: Optional[str], requested_mode: str) -> str:
    if requested_mode == "none":
        return "none"
    if tier == "canary" and not use_case:
        return "none"
    return "auto"
