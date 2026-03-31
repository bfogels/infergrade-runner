from infergrade.adapters.base import BaseAdapter


class VLLMAdapter(BaseAdapter):
    backend_name = "vllm"

    def default_backend_flags(self):
        return ["--tensor-parallel-size=1"]
