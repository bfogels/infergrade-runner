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
    discover_local_runtimes,
    parse_local_endpoint,
    provider_profiles,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "observed_runtime"


def _fixture(name):
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8")


class _ObservedRuntimeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    requests = []
    mode = "json"

    def log_message(self, format, *args):  # pragma: no cover
        return

    def do_GET(self):  # noqa: N802
        self.__class__.requests.append((self.command, self.path, dict(self.headers)))
        if self.path == "/v1/models":
            self._send(200, "application/json", _fixture("openai_models.json"))
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
            client = OpenAICompatibleClient(server.endpoint, api_key="local-secret")
            probe = client.probe()
            answer = client.complete("qwen3.5:9b", "Say hello", 32)
            receipt = probe.to_receipt()

        self.assertEqual(probe.provider, "unknown")
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

    def test_provider_hint_and_ollama_discovery_shape_do_not_infer_quant_or_publisher(self):
        with _ObservedRuntimeServer() as server:
            client = OpenAICompatibleClient(server.endpoint, provider_hint="ollama")
            probe = client.probe()
            receipt = probe.to_receipt()

        self.assertEqual(probe.provider, "ollama")
        self.assertEqual(probe.model_ids, ["qwen3.5:9b"])
        self.assertEqual(receipt["identity"]["status"], "reported_only")
        self.assertEqual(receipt["claim_boundary"]["quantization"], "unknown")
        self.assertEqual(receipt["claim_boundary"]["artifact_publisher"], "unknown")

    def test_sse_completion_is_bounded_and_normalized_without_receipt_output(self):
        with _ObservedRuntimeServer() as server:
            client = OpenAICompatibleClient(server.endpoint)
            probe = client.probe()
            answer = client.complete("qwen3.5:9b", "Stream", 32, stream=True)
            receipt = probe.to_receipt()

        self.assertEqual(answer, "fixture stream answer")
        self.assertEqual(receipt["protocol"]["chat_completions"], "compatible")
        self.assertNotIn("stream answer", json.dumps(receipt))

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
