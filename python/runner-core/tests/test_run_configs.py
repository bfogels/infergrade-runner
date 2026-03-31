import sys
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.request import request_from_dict
from infergrade.run_configs import build_run_config_document


class RunConfigTests(unittest.TestCase):
    def test_request_can_be_loaded_from_run_config_document(self):
        payload = build_run_config_document(
            request_payload={
                "spec_version": "0.1-draft",
                "run": {
                    "model": "Qwen/Qwen2.5-7B-Instruct",
                    "backend": "llama.cpp",
                    "tier": "canary",
                },
                "artifacts": {
                    "quantized_weights": {
                        "uri": "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/qwen2.5-7b-instruct-q4_k_m.gguf",
                        "filename": "qwen2.5-7b-instruct-q4_k_m.gguf",
                    }
                },
                "runtime": {
                    "backend_image": "infergrade-llama-cpp:local",
                },
            },
            name="Canary config",
        )
        request = request_from_dict(payload)
        self.assertEqual(request.run_config_id, payload["run_config_id"])
        self.assertEqual(request.run_config_name, "Canary config")
        self.assertEqual(request.model, "Qwen/Qwen2.5-7B-Instruct")
        self.assertEqual(
            request.quant_artifact,
            "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/qwen2.5-7b-instruct-q4_k_m.gguf",
        )
        self.assertEqual(request.backend_image, "infergrade-llama-cpp:local")
