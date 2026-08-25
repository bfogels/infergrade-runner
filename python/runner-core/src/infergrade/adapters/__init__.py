from infergrade.adapters.llama_cpp import LlamaCppAdapter
from infergrade.adapters.openai_compatible import OpenAICompatibleAdapter
from infergrade.adapters.vllm import VLLMAdapter


def get_adapter(backend_name: str):
    if backend_name == "llama.cpp":
        return LlamaCppAdapter()
    if backend_name == "vllm":
        return VLLMAdapter()
    raise ValueError("Unsupported backend: %s" % backend_name)


def get_observed_runtime_adapter(**kwargs):
    """Construct the opt-in observed-runtime adapter without changing backend defaults."""
    return OpenAICompatibleAdapter(**kwargs)
