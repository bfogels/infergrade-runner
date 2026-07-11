SUPPORTED_BACKENDS = ("llama.cpp", "vllm")
SUPPORTED_TIERS = ("canary", "standard", "gold")
SUPPORTED_USE_CASES = ("agentic_coding", "general_assistant", "reasoning")
SUPPORTED_DEPLOYMENT_PROFILES = (
    "interactive_chat_v1",
    "batch_generation_v1",
    "long_context_v1",
)
SUPPORTED_EXECUTION_MODES = ("local_container", "local_native", "cloud_container", "manual_external")
SUPPORTED_CAPABILITY_MODES = ("auto", "none")
SUPPORTED_COST_SOURCES = ("observed", "billing_import", "user_provided", "estimated", "none")
DEFAULT_GENERATION_PRESET = "deterministic_v1"
