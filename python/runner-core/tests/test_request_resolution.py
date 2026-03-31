import sys
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.models import RunRequest
from infergrade.profiles import resolve_capability_behavior, resolve_deployment_profiles
from infergrade.request import request_from_dict
from infergrade.validators import RequestValidationError, validate_request


class RequestResolutionTests(unittest.TestCase):
    def test_canary_without_use_case_can_skip_capability(self):
        request = RunRequest(model="Qwen/Qwen2.5-7B-Instruct", backend="llama.cpp", tier="canary")
        request.capability = resolve_capability_behavior(request.tier, request.use_case, request.capability)
        request.deployment_profiles = resolve_deployment_profiles(request.use_case, request.deployment_profiles)
        validate_request(request)
        self.assertEqual(request.capability, "none")
        self.assertEqual(request.deployment_profiles, ["interactive_chat_v1"])

    def test_standard_without_use_case_requires_capability_disabled(self):
        request = RunRequest(model="Qwen/Qwen2.5-7B-Instruct", backend="llama.cpp", tier="standard")
        with self.assertRaises(RequestValidationError):
            validate_request(request)

    def test_standard_without_use_case_can_disable_capability(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            capability="none",
        )
        validate_request(request)

    def test_request_from_dict_supports_self_contained_artifact_and_runtime_blocks(self):
        payload = {
            "spec_version": "0.1-draft",
            "run": {
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "backend": "llama.cpp",
                "tier": "canary",
            },
            "artifacts": {
                "quantized_weights": {
                    "uri": "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/qwen2.5-7b-instruct-q4_k_m.gguf",
                    "sha256": "abc123",
                    "filename": "qwen2.5-7b-instruct-q4_k_m.gguf",
                    "revision": "main",
                }
            },
            "runtime": {
                "backend_image": "infergrade-llama-cpp:local",
                "artifact_cache_dir": "/tmp/infergrade-cache",
            },
        }
        request = request_from_dict(payload)
        self.assertEqual(
            request.quant_artifact,
            "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/qwen2.5-7b-instruct-q4_k_m.gguf",
        )
        self.assertEqual(request.quant_artifact_sha256, "abc123")
        self.assertEqual(request.quant_artifact_filename, "qwen2.5-7b-instruct-q4_k_m.gguf")
        self.assertEqual(request.quant_artifact_revision, "main")
        self.assertEqual(request.backend_image, "infergrade-llama-cpp:local")
        self.assertEqual(request.quant_artifact_cache_dir, "/tmp/infergrade-cache")


if __name__ == "__main__":
    unittest.main()
