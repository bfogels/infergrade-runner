import sys
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.models import RunRequest
from infergrade.profiles import resolve_capability_behavior, resolve_deployment_profiles
from infergrade.request import request_from_dict
from infergrade.run_configs import request_from_run_config_document
from infergrade.validators import RequestValidationError, validate_request


class RequestResolutionTests(unittest.TestCase):
    def test_canary_without_use_case_can_skip_capability(self):
        request = RunRequest(model="Qwen/Qwen2.5-7B-Instruct", backend="llama.cpp", tier="canary")
        request.capability = resolve_capability_behavior(request.tier, request.use_case, request.capability)
        request.deployment_profiles = resolve_deployment_profiles(request.use_case, request.deployment_profiles)
        validate_request(request)
        self.assertEqual(request.capability, "none")
        self.assertEqual(request.deployment_profiles, ["interactive_chat_v1"])

    def test_standard_without_use_case_normalizes_to_non_capability_selection(self):
        request = RunRequest(model="Qwen/Qwen2.5-7B-Instruct", backend="llama.cpp", tier="standard")
        validate_request(request)
        self.assertEqual(request.capability, "none")
        self.assertIn("batch_generation_v1", request.deployment_profiles)

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
                    "uri": "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
                    "sha256": "abc123",
                    "filename": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
                    "revision": "main",
                }
            },
            "runtime": {
                "backend_image": "infergrade-llama-cpp:local",
                "artifact_cache_dir": "/tmp/infergrade-cache",
                "llama_cpp_cli_path": "/custom/llama-cli",
                "llama_cpp_server_path": "/custom/llama-server",
                "llama_cpp_perplexity_path": "/custom/llama-perplexity",
                "runtime_selector": {
                    "runtime_selector_version": "0.3",
                    "runtime_family": "llama.cpp",
                    "support": {
                        "tier": "best_effort",
                        "claim_boundary": "User-selected binary recorded for provenance.",
                    },
                },
            },
        }
        request = request_from_dict(payload)
        self.assertEqual(
            request.quant_artifact,
            "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        )
        self.assertEqual(request.quant_artifact_sha256, "abc123")
        self.assertEqual(request.quant_artifact_filename, "Qwen2.5-7B-Instruct-Q4_K_M.gguf")
        self.assertEqual(request.quant_artifact_revision, "main")
        self.assertEqual(request.backend_image, "infergrade-llama-cpp:local")
        self.assertEqual(request.quant_artifact_cache_dir, "/tmp/infergrade-cache")
        self.assertEqual(request.llama_cpp_cli_path, "/custom/llama-cli")
        self.assertEqual(request.llama_cpp_server_path, "/custom/llama-server")
        self.assertEqual(request.llama_cpp_perplexity_path, "/custom/llama-perplexity")
        self.assertEqual(request.runtime_selector["runtime_selector_version"], "0.3")
        self.assertEqual(request.runtime_selector["support"]["tier"], "best_effort")

    def test_hub_run_config_rejects_runtime_selector_binary_path(self):
        payload = {
            "run_config_id": "rcfg_bad_selector",
            "name": "Bad selector",
            "request": {
                "spec_version": "0.1-draft",
                "run": {
                    "model": "Qwen/Qwen2.5-7B-Instruct",
                    "backend": "llama.cpp",
                    "tier": "canary",
                },
                "runtime": {
                    "runtime_selector": {
                        "runtime_selector_version": "0.3",
                        "runtime_family": "llama.cpp",
                        "binary": {"path": "/tmp/malicious/llama-cli"},
                    }
                },
            },
        }

        with self.assertRaises(ValueError) as exc:
            request_from_run_config_document(payload)
        self.assertIn("runtime.runtime_selector.binary.path", str(exc.exception))

    def test_request_from_dict_normalizes_capability_first_selection(self):
        payload = {
            "spec_version": "0.1-draft",
            "run": {
                "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
                "backend": "llama.cpp",
                "tier": "canary",
                "capability_suite_ids": ["coding_code_editing", "quant_fidelity"],
                "benchmark_group_ids": ["coding_core", "deployment_long_context", "quant_fidelity"],
                "benchmark_check_ids": ["evalplus_humaneval", "long_context_v1", "perplexity_reference_v1"],
            },
        }
        request = request_from_dict(payload)
        self.assertEqual(request.use_case, "agentic_coding")
        self.assertEqual(request.tier, "standard")
        self.assertEqual(request.deployment_profiles, ["long_context_v1"])
        self.assertEqual(request.capability, "auto")
        self.assertIn("quant_fidelity", request.capability_suite_ids)
        self.assertIn("perplexity_reference_v1", request.benchmark_check_ids)

    def test_request_from_dict_accepts_explicit_selection_without_tier(self):
        payload = {
            "request": {
                "spec_version": "0.1-draft",
                "run": {
                    "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
                    "backend": "llama.cpp",
                    "benchmark_check_ids": ["evalplus_humaneval", "long_context_v1", "perplexity_reference_v1"],
                },
            },
            "run_config_id": "rcfg_explicit_selection",
            "name": "Explicit selection",
        }

        request = request_from_dict(payload)
        self.assertEqual(request.tier, "standard")
        self.assertEqual(request.use_case, "agentic_coding")
        self.assertEqual(request.deployment_profiles, ["long_context_v1"])
        self.assertEqual(request.capability, "auto")


if __name__ == "__main__":
    unittest.main()
