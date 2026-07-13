import sys
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.models import RunRequest
from infergrade.profiles import resolve_capability_behavior, resolve_deployment_profiles
from infergrade.request import request_from_dict, request_to_dict
from infergrade.run_configs import request_from_run_config_document
from infergrade.validators import RequestValidationError, validate_request


class RequestResolutionTests(unittest.TestCase):
    def test_default_deployment_counts_do_not_change_legacy_request_shape(self):
        payload = request_to_dict(RunRequest(model="model", backend="llama.cpp", tier="canary"))
        self.assertNotIn("deployment_warmup_runs", payload)
        self.assertNotIn("deployment_measured_runs", payload)
        self.assertNotIn("quant_artifact_download_size_bytes", payload)

    def test_explicit_deployment_counts_are_fingerprinted(self):
        payload = request_to_dict(
            RunRequest(
                model="model",
                backend="llama.cpp",
                tier="canary",
                deployment_warmup_runs=0,
                deployment_measured_runs=3,
            )
        )
        self.assertEqual(payload["deployment_warmup_runs"], 0)
        self.assertEqual(payload["deployment_measured_runs"], 3)

    def test_deployment_count_bounds_are_enforced_by_shared_validator(self):
        for field_name, invalid_values in (
            ("deployment_warmup_runs", (-1, 6, 1.0, True, "1")),
            ("deployment_measured_runs", (0, 21, 1.0, True, "1")),
        ):
            for invalid in invalid_values:
                request = RunRequest(model="model", backend="llama.cpp", tier="canary")
                setattr(request, field_name, invalid)
                with self.subTest(field_name=field_name, invalid=invalid):
                    with self.assertRaises(RequestValidationError):
                        validate_request(request)

    def test_reasoning_use_case_is_valid_and_gets_interactive_defaults(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="canary",
            use_case="reasoning",
        )
        request.capability = resolve_capability_behavior(request.tier, request.use_case, request.capability)
        request.deployment_profiles = resolve_deployment_profiles(request.use_case, request.deployment_profiles)

        validate_request(request)

        self.assertEqual(request.capability, "auto")
        self.assertEqual(request.deployment_profiles, ["interactive_chat_v1"])

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
                "deployment_warmup_runs": 2,
                "deployment_measured_runs": 7,
            },
                "artifacts": {
                    "quantized_weights": {
                    "uri": "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
                    "sha256": "abc123",
                    "filename": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
                    "revision": "main",
                    "download_size_bytes": 123456,
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
            "metadata": {"evidence_source": "agent_dogfood"},
        }
        request = request_from_dict(payload)
        self.assertEqual(
            request.quant_artifact,
            "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        )
        self.assertEqual(request.quant_artifact_sha256, "abc123")
        self.assertEqual(request.quant_artifact_filename, "Qwen2.5-7B-Instruct-Q4_K_M.gguf")
        self.assertEqual(request.quant_artifact_revision, "main")
        self.assertEqual(request.quant_artifact_download_size_bytes, 123456)
        self.assertEqual(request.deployment_warmup_runs, 2)
        self.assertEqual(request.deployment_measured_runs, 7)
        self.assertEqual(request.backend_image, "infergrade-llama-cpp:local")
        self.assertEqual(request.quant_artifact_cache_dir, "/tmp/infergrade-cache")
        self.assertEqual(request.llama_cpp_cli_path, "/custom/llama-cli")
        self.assertEqual(request.llama_cpp_server_path, "/custom/llama-server")
        self.assertEqual(request.llama_cpp_perplexity_path, "/custom/llama-perplexity")
        self.assertEqual(request.runtime_selector["runtime_selector_version"], "0.3")
        self.assertEqual(request.runtime_selector["support"]["tier"], "best_effort")
        self.assertEqual(request.evidence_source, "agent_dogfood")

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
