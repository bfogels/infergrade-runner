import copy
import sys
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.request import request_from_dict, sanitize_hub_supplied_payload
from infergrade.run_configs import build_run_config_document, request_from_run_config_document


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
                        "uri": "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
                        "filename": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
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
            "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        )
        self.assertEqual(request.backend_image, "infergrade-llama-cpp:local")


def _hub_payload(runtime_overrides=None):
    """Build a minimal hub-style run config document for sanitization tests."""
    runtime = {"backend_image": "infergrade-llama-cpp:local"}
    if runtime_overrides:
        runtime.update(runtime_overrides)
    return build_run_config_document(
        request_payload={
            "spec_version": "0.1-draft",
            "run": {
                "model": "Qwen/Qwen2.5-7B-Instruct",
                "backend": "llama.cpp",
                "tier": "canary",
            },
            "artifacts": {
                "quantized_weights": {
                    "uri": "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/file.gguf",
                    "filename": "file.gguf",
                }
            },
            "runtime": runtime,
        },
        name="Canary config",
    )


class HubSuppliedPayloadSanitizationTests(unittest.TestCase):
    def test_sanitize_rejects_hub_supplied_native_cli_path(self):
        payload = _hub_payload({"llama_cpp_cli_path": "/bin/sh"})
        with self.assertRaises(ValueError) as ctx:
            sanitize_hub_supplied_payload(payload)
        self.assertIn("llama_cpp_cli_path", str(ctx.exception))

    def test_sanitize_rejects_hub_supplied_native_server_path(self):
        payload = _hub_payload({"llama_cpp_server_path": "/usr/local/bin/evil"})
        with self.assertRaises(ValueError):
            sanitize_hub_supplied_payload(payload)

    def test_sanitize_rejects_hub_supplied_native_perplexity_path(self):
        payload = _hub_payload({"llama_cpp_perplexity_path": "/tmp/evil"})
        with self.assertRaises(ValueError):
            sanitize_hub_supplied_payload(payload)

    def test_sanitize_rejects_legacy_alias_keys(self):
        # ``request_from_dict`` accepts the shorter aliases too, so the
        # sanitizer must reject them to close the loophole.
        for alias in ("llama_cpp_cli", "llama_cpp_server", "llama_cpp_perplexity"):
            payload = _hub_payload({alias: "/bin/sh"})
            with self.assertRaises(ValueError):
                sanitize_hub_supplied_payload(payload)

    def test_sanitize_rejects_backend_image_starting_with_dash(self):
        payload = _hub_payload({"backend_image": "--privileged"})
        with self.assertRaises(ValueError) as ctx:
            sanitize_hub_supplied_payload(payload)
        self.assertIn("backend_image", str(ctx.exception))

    def test_sanitize_rejects_backend_image_with_whitespace(self):
        payload = _hub_payload({"backend_image": "ubuntu:latest --privileged"})
        with self.assertRaises(ValueError):
            sanitize_hub_supplied_payload(payload)

    def test_sanitize_preserves_valid_backend_image(self):
        payload = _hub_payload({"backend_image": "gcr.io/project/image:tag"})
        cleaned = sanitize_hub_supplied_payload(payload)
        # Returns a deep copy, leaving the caller's payload untouched.
        self.assertIsNot(cleaned, payload)
        self.assertEqual(cleaned["request"]["runtime"]["backend_image"], "gcr.io/project/image:tag")

    def test_sanitize_is_a_noop_on_trustworthy_payload(self):
        payload = _hub_payload()
        original = copy.deepcopy(payload)
        cleaned = sanitize_hub_supplied_payload(payload)
        self.assertEqual(cleaned, original)
        self.assertEqual(payload, original)  # original is not mutated

    def test_request_from_run_config_document_strips_attack_vectors(self):
        # End-to-end: a hub payload carrying an attack must not produce a RunRequest.
        payload = _hub_payload({"llama_cpp_cli_path": "/bin/sh"})
        with self.assertRaises(ValueError):
            request_from_run_config_document(payload)
