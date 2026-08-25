import json
import os
import socket
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, "python/runner-core/src")

from infergrade.adapters.openai_compatible import OpenAICompatibleAdapter
from infergrade.models import RunRequest
from infergrade.observed_runtime import (
    FAILURE_CODES,
    OBSERVED_RUNTIME_CONTRACT_VERSION,
    OpenAICompatibleClient,
    ObservedRuntimeError,
    ObservedRuntimeProbe,
    discover_local_runtimes,
    parse_local_endpoint,
    provider_profiles,
    safe_receipt_model_label,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "observed_runtime"


def _fixture(name):
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8")


class _ObservedRuntimeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    requests = []
    mode = "json"
    chat_status = 200
    reasoning_only = False
    models_fixture = "openai_models.json"

    def log_message(self, format, *args):  # pragma: no cover
        return

    def do_GET(self):  # noqa: N802
        self.__class__.requests.append((self.command, self.path, dict(self.headers)))
        if self.path == "/v1/models":
            self._send(200, "application/json", _fixture(self.__class__.models_fixture))
            return
        if self.path == "/api/tags":
            self._send(200, "application/json", _fixture("ollama_tags.json"))
            return
        if self.path == "/redirect" or self.path == "/redirect/v1/models":
            self.send_response(302)
            self.send_header("Location", "/v1/models")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/too-large" or self.path == "/too-large/v1/models":
            body = b"x" * 17
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._send(404, "application/json", "{}")

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        self.__class__.requests.append((self.command, self.path, dict(self.headers), body))
        if self.path != "/v1/chat/completions":
            self._send(404, "application/json", "{}")
            return
        if self.__class__.chat_status != 200:
            self._send(self.__class__.chat_status, "application/json", "{}")
            return
        if self.__class__.reasoning_only:
            self._send(200, "application/json", _fixture("chat_reasoning_only.json"))
            return
        payload = json.loads(body.decode("utf-8"))
        if payload.get("stream"):
            self._send(200, "text/event-stream", _fixture("chat_stream.sse"))
        else:
            self._send(200, "application/json", _fixture("chat_response.json"))

    def _send(self, status, content_type, body):
        encoded = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class _ObservedRuntimeServer(object):
    def __enter__(self):
        _ObservedRuntimeHandler.requests = []
        _ObservedRuntimeHandler.chat_status = 200
        _ObservedRuntimeHandler.reasoning_only = False
        _ObservedRuntimeHandler.models_fixture = "openai_models.json"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.server = ThreadingHTTPServer(("127.0.0.1", port), _ObservedRuntimeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = port
        self.endpoint = "http://127.0.0.1:%d" % port
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()


class ObservedRuntimeTests(unittest.TestCase):
    def test_provider_profiles_are_bounded_and_cover_required_local_servers(self):
        profiles = provider_profiles()
        self.assertEqual(len(profiles), 5)
        self.assertEqual(
            {item.provider for item in profiles},
            {"ollama", "lm_studio", "llama_server", "vllm", "tgi"},
        )
        self.assertEqual(len({item.default_port for item in profiles}), 5)

    def test_endpoint_validation_rejects_non_loopback_credentials_and_redirect_primitives(self):
        for value, code in (
            ("http://192.168.1.10:8000", "non_loopback_endpoint"),
            ("http://example.com:8000", "non_loopback_endpoint"),
            ("ftp://127.0.0.1:8000", "unsupported_scheme"),
            ("http://user:secret@127.0.0.1:8000", "endpoint_invalid"),
            ("http://127.0.0.1:8000?token=secret", "endpoint_invalid"),
            (" http://127.0.0.1:8000", "endpoint_invalid"),
        ):
            with self.subTest(value=value):
                with self.assertRaises(ObservedRuntimeError) as caught:
                    parse_local_endpoint(value)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(str(caught.exception), code)

        with self.assertRaises(ObservedRuntimeError) as bad_hint:
            OpenAICompatibleClient("http://127.0.0.1:8000", provider_hint=["vllm"])
        self.assertEqual(bad_hint.exception.code, "endpoint_invalid")

    def test_endpoint_base_path_is_not_duplicated(self):
        with _ObservedRuntimeServer() as server:
            client = OpenAICompatibleClient(server.endpoint + "/v1")
            probe = client.probe()

        self.assertEqual(probe.model_ids, ["qwen3.5:9b"])

    def test_json_probe_and_completion_are_real_http_and_receipt_is_private_and_observed(self):
        with _ObservedRuntimeServer() as server:
            client = OpenAICompatibleClient(
                server.endpoint,
                provider_hint="llama_server",
                api_key="local-secret",
            )
            probe = client.probe()
            answer = client.complete("qwen3.5:9b", "Say hello", 32)
            receipt = probe.to_receipt()

        self.assertEqual(probe.provider, "llama_server")
        self.assertEqual(probe.model_ids, ["qwen3.5:9b"])
        self.assertEqual(answer, "fixture answer")
        self.assertEqual(receipt["contract_version"], OBSERVED_RUNTIME_CONTRACT_VERSION)
        self.assertEqual(receipt["evidence_kind"], "observed_runtime")
        self.assertEqual(receipt["evidence_lane"], "observed")
        self.assertFalse(receipt["promotion_eligible"])
        self.assertEqual(receipt["provider_status"], "compatibility_hint")
        self.assertEqual(receipt["identity"]["artifact_publisher"], None)
        self.assertEqual(receipt["identity"]["quantization"], None)
        self.assertEqual(receipt["identity"]["artifact_sha256"], None)
        self.assertEqual(receipt["identity"]["runtime_build_id"], None)
        self.assertEqual(receipt["identity"]["runtime_bytes"], None)
        chat_request = next(item for item in _ObservedRuntimeHandler.requests if item[0] == "POST")
        chat_payload = json.loads(chat_request[3].decode("utf-8"))
        self.assertEqual(chat_payload["temperature"], 0)
        self.assertEqual(chat_payload["max_tokens"], 32)
        self.assertFalse(chat_payload["stream"])
        self.assertEqual(chat_payload["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(chat_payload["thinking_budget_tokens"], 0)
        self.assertEqual(receipt["generation_profile"], {
            "profile_version": "quick_generation_v1",
            "temperature": 0.0,
            "max_tokens": 32,
            "stream": False,
            "thinking_control": {"requested": True, "effective": "not_verified"},
        })
        serialized = json.dumps(receipt, sort_keys=True)
        self.assertNotIn(server.endpoint, serialized)
        self.assertNotIn("local-secret", serialized)
        self.assertNotIn("fixture answer", serialized)
        self.assertNotIn("/v1", serialized)
        self.assertEqual(receipt["privacy"], {
            "endpoint_url_recorded": False,
            "credentials_recorded": False,
            "local_paths_recorded": False,
            "raw_outputs_recorded": False,
        })
        self.assertEqual(receipt["endpoint"], {"network_scope": "loopback"})
        self.assertNotIn("port", receipt["endpoint"])

    def test_provider_hint_and_ollama_discovery_shape_do_not_infer_quant_or_publisher(self):
        with _ObservedRuntimeServer() as server:
            client = OpenAICompatibleClient(server.endpoint, provider_hint="ollama")
            probe = client.probe()
            answer = client.complete("qwen3.5:9b", "Say hello", 16)
            receipt = probe.to_receipt()

        self.assertEqual(probe.provider, "ollama")
        self.assertEqual(probe.model_ids, ["qwen3.5:9b"])
        self.assertEqual(receipt["identity"]["status"], "reported_only")
        self.assertEqual(receipt["claim_boundary"]["quantization"], "unknown")
        self.assertEqual(receipt["claim_boundary"]["artifact_publisher"], "unknown")
        self.assertEqual(answer, "fixture answer")
        self.assertEqual(receipt["generation_profile"]["thinking_control"], {
            "requested": False,
            "effective": "server_default_uncontrolled",
        })
        chat_request = next(item for item in _ObservedRuntimeHandler.requests if item[0] == "POST")
        chat_payload = json.loads(chat_request[3].decode("utf-8"))
        self.assertNotIn("chat_template_kwargs", chat_payload)
        self.assertNotIn("thinking_budget_tokens", chat_payload)

    def test_receipt_model_label_filter_withholds_paths_urls_traversal_and_credentials(self):
        unsafe_labels = (
            "/Users/alice/private/secret.gguf",
            r"C:\Users\alice\private\secret.gguf",
            "C:/Users/alice/private/secret.gguf",
            r"\\server\share\secret.gguf",
            "file:///Users/alice/private/secret.gguf",
            "http://127.0.0.1:8080/v1/models",
            "https://example.com/model",
            "../secret.gguf",
            "owner/../model",
            "owner/./model",
            "models/foo.gguf",
            "Users/name/model",
            "owner/model?token=secret",
            "owner/model#fragment",
            "user:password@host",
            "Bearer secret",
            "token=secret",
            "owner/\x00model",
            " owner/model",
        )
        for label in unsafe_labels:
            with self.subTest(label=label):
                self.assertIsNone(safe_receipt_model_label(label))

        for label in ("owner/model", "qwen3.5:9b", "owner/model:Q4_K_M"):
            with self.subTest(label=label):
                self.assertEqual(safe_receipt_model_label(label), label)

    def test_receipt_withholds_unsafe_reported_ids_but_keeps_them_in_memory_for_generation(self):
        unsafe_labels = [
            "/Users/alice/private/secret.gguf",
            r"C:\Users\alice\private\secret.gguf",
            "file:///Users/alice/private/secret.gguf",
            "http://127.0.0.1:8080/v1/models",
            "models/foo.gguf",
            "Users/name/model",
        ]
        endpoint = parse_local_endpoint("http://127.0.0.1:12345")
        probe = ObservedRuntimeProbe(
            endpoint=endpoint,
            provider="llama_server",
            model_ids=unsafe_labels + ["owner/model", "qwen3.5:9b"],
            model_endpoint_status="compatible",
        )
        receipt = probe.to_receipt(selected_model_id=unsafe_labels[0])
        identity = receipt["identity"]
        serialized = json.dumps(receipt, sort_keys=True)

        self.assertIn(unsafe_labels[0], probe.model_ids)
        self.assertEqual(identity["reported_model_ids"], ["owner/model", "qwen3.5:9b"])
        self.assertIsNone(identity["reported_model_id"])
        self.assertEqual(identity["selected_model_id_status"], "withheld_unsafe")
        self.assertEqual(identity["reported_model_id_status"], "reported_with_withheld")
        self.assertEqual(identity["reported_model_id_count"], 8)
        self.assertEqual(identity["withheld_model_id_count"], 6)
        self.assertEqual(receipt["endpoint"], {"network_scope": "loopback"})
        self.assertNotIn("port", receipt["endpoint"])
        for label in unsafe_labels:
            self.assertNotIn(label, serialized)

    def test_receipt_marks_all_unsafe_reported_ids_as_withheld(self):
        probe = ObservedRuntimeProbe(
            endpoint=parse_local_endpoint("http://127.0.0.1:12345"),
            provider="llama_server",
            model_ids=["/Users/alice/private/secret.gguf", r"C:\Models\secret.gguf"],
            model_endpoint_status="compatible",
        )
        identity = probe.to_receipt()["identity"]
        self.assertIsNone(identity["reported_model_id"])
        self.assertEqual(identity["reported_model_ids"], [])
        self.assertEqual(identity["reported_model_id_status"], "withheld_unsafe")
        self.assertEqual(identity["reported_model_id_count"], 2)
        self.assertEqual(identity["withheld_model_id_count"], 2)

    def test_unsafe_model_path_remains_in_memory_for_generation_but_never_receipt(self):
        request = RunRequest(
            model="requested/model",
            backend="openai_compatible_observed",
            tier="canary",
            simulate=False,
        )
        with _ObservedRuntimeServer() as server:
            _ObservedRuntimeHandler.models_fixture = "openai_models_unsafe.json"
            adapter = OpenAICompatibleAdapter(server.endpoint, provider_hint="llama_server")
            result = adapter.generate_text(request, "Return one answer", 16)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["text"], "fixture answer")
        chat_request = next(item for item in _ObservedRuntimeHandler.requests if item[0] == "POST")
        chat_payload = json.loads(chat_request[3].decode("utf-8"))
        self.assertEqual(chat_payload["model"], "/Users/alice/private/secret.gguf")
        identity = result["observed_runtime"]["identity"]
        self.assertIsNone(identity["reported_model_id"])
        self.assertEqual(identity["reported_model_ids"], [])
        self.assertEqual(identity["selected_model_id_status"], "withheld_unsafe")
        self.assertEqual(identity["withheld_model_id_count"], 1)
        self.assertNotIn("/Users/alice/private/secret.gguf", json.dumps(result))

    def test_sse_completion_is_bounded_and_normalized_without_receipt_output(self):
        with _ObservedRuntimeServer() as server:
            client = OpenAICompatibleClient(server.endpoint, provider_hint="llama_server")
            probe = client.probe()
            answer = client.complete("qwen3.5:9b", "Stream", 32, stream=True)
            receipt = probe.to_receipt()

        self.assertEqual(answer, "fixture stream answer")
        self.assertEqual(receipt["protocol"]["chat_completions"], "compatible")
        self.assertEqual(receipt["generation_profile"]["stream"], True)
        self.assertEqual(receipt["generation_profile"]["max_tokens"], 32)
        self.assertNotIn("stream answer", json.dumps(receipt))

    def test_vllm_generation_requests_explicit_thinking_control_without_llama_budget_extension(self):
        with _ObservedRuntimeServer() as server:
            client = OpenAICompatibleClient(server.endpoint, provider_hint="vllm")
            probe = client.probe()
            answer = client.complete("qwen3.5:9b", "Say hello", 16)
            receipt = probe.to_receipt(selected_model_id="qwen3.5:9b")

        self.assertEqual(answer, "fixture answer")
        self.assertEqual(receipt["generation_profile"]["thinking_control"], {
            "requested": True,
            "effective": "not_verified",
        })
        chat_request = next(item for item in _ObservedRuntimeHandler.requests if item[0] == "POST")
        chat_payload = json.loads(chat_request[3].decode("utf-8"))
        self.assertEqual(chat_payload["chat_template_kwargs"], {"enable_thinking": False})
        self.assertNotIn("thinking_budget_tokens", chat_payload)

    def test_post_probe_chat_failure_is_unavailable_with_actual_code_and_does_not_mutate_probe(self):
        request = RunRequest(
            model="qwen3.5:9b",
            backend="openai_compatible_observed",
            tier="canary",
            simulate=False,
        )
        with _ObservedRuntimeServer() as server:
            client = OpenAICompatibleClient(server.endpoint, provider_hint="llama_server")
            probe = client.probe()
            _ObservedRuntimeHandler.chat_status = 500
            adapter = OpenAICompatibleAdapter(client=client)
            result = adapter.generate_text(request, "Return one answer", 16)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "http_error")
        self.assertEqual(probe.chat_endpoint_status, "not_probed")
        self.assertEqual(result["observed_runtime"]["protocol"]["chat_completions"], "unavailable")
        self.assertEqual(result["observed_runtime"]["failure_code"], "http_error")
        self.assertEqual(
            result["observed_runtime"]["generation_profile"]["thinking_control"]["effective"],
            "request_failed",
        )

    def test_reasoning_only_payload_is_rejected_without_persisting_hidden_text(self):
        request = RunRequest(
            model="qwen3.5:9b",
            backend="openai_compatible_observed",
            tier="canary",
            simulate=False,
        )
        with _ObservedRuntimeServer() as server:
            client = OpenAICompatibleClient(server.endpoint, provider_hint="llama_server")
            client.probe()
            _ObservedRuntimeHandler.reasoning_only = True
            result = OpenAICompatibleAdapter(client=client).generate_text(
                request, "Return one answer", 16
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "empty_response")
        self.assertEqual(
            result["observed_runtime"]["generation_profile"]["thinking_control"]["effective"],
            "rejected",
        )
        self.assertNotIn("hidden chain content", json.dumps(result))

    def test_redirect_and_oversized_response_have_stable_codes(self):
        with _ObservedRuntimeServer() as server:
            redirect_client = OpenAICompatibleClient(server.endpoint + "/redirect")
            with self.assertRaises(ObservedRuntimeError) as redirect_error:
                redirect_client.probe()
            self.assertEqual(redirect_error.exception.code, "redirect_not_allowed")

            too_large_client = OpenAICompatibleClient(server.endpoint + "/too-large", max_response_bytes=16)
            with self.assertRaises(ObservedRuntimeError) as size_error:
                too_large_client.probe()
            self.assertEqual(size_error.exception.code, "response_too_large")

    def test_discovery_uses_explicit_loopback_fixture_and_never_emits_endpoint_url(self):
        with _ObservedRuntimeServer() as server:
            results = discover_local_runtimes(
                endpoints=[(server.endpoint, "vllm")],
                timeout_seconds=1.0,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["provider"], "vllm")
        self.assertEqual(results[0]["endpoint"]["network_scope"], "loopback")
        self.assertNotIn(server.endpoint, json.dumps(results[0]))
        self.assertNotIn("/v1", json.dumps(results[0]))

    def test_adapter_real_local_end_to_end_preserves_observed_boundary(self):
        request = RunRequest(
            model="publisher/model-q4_k_m",
            backend="openai_compatible_observed",
            tier="canary",
            simulate=False,
        )
        with _ObservedRuntimeServer() as server:
            adapter = OpenAICompatibleAdapter(server.endpoint, provider_hint="llama_server")
            result = adapter.generate_text(request, "Return one answer", 16)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["text"], "fixture answer")
        self.assertEqual(result["error"], None)
        self.assertEqual(result["observed_runtime"]["provider"], "llama_server")
        self.assertFalse(result["observed_runtime"]["promotion_eligible"])
        self.assertEqual(result["observed_runtime"]["identity"]["quantization"], None)
        self.assertEqual(result["observed_runtime"]["identity"]["artifact_publisher"], None)
        self.assertEqual(adapter.runtime_metadata(request)["endpoint_network_scope"], "loopback")
        self.assertNotIn("endpoint_port", adapter.runtime_metadata(request))
        self.assertEqual(adapter.runtime_metadata(request)["runtime_identity_status"], "unknown")

    def test_adapter_failure_returns_stable_error_without_private_data(self):
        request = RunRequest(
            model="publisher/model",
            backend="openai_compatible_observed",
            tier="canary",
            simulate=False,
        )
        with _ObservedRuntimeServer() as server:
            adapter = OpenAICompatibleAdapter(server.endpoint + "/missing", api_key="secret")
            result = adapter.generate_text(request, "Return one answer", 16)

        self.assertEqual(result["status"], "failed")
        self.assertIn(result["error"], FAILURE_CODES)
        self.assertIsNotNone(result["observed_runtime"])
        self.assertEqual(result["observed_runtime"]["verification_status"], "not_verified")
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn(server.endpoint, json.dumps(result))


if __name__ == "__main__":
    unittest.main()
