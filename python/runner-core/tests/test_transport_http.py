import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "python/runner-core/src")

from infergrade.transport import (
    RunnerTokenInvalidError,
    _resolve_api_token,
    bundle_payload,
    fetch_run_config,
    list_run_configs,
    publish_run_config,
    redeem_runner_pairing,
    upload_bundle,
    upload_run_bundle,
)


class _CaptureHandler(BaseHTTPRequestHandler):
    responses = {}
    response_statuses = {}
    requests = []

    def do_GET(self):  # noqa: N802
        self._record_request()
        key = (self.command, self.path)
        self._send_json(self.responses.get(key, {}), status=self.response_statuses.get(key, 200))

    def do_POST(self):  # noqa: N802
        payload = self._record_request()
        if self.path == "/bundles":
            self._send_json({"stored": True, "bundle_id": payload["manifest"]["bundle_id"]})
            return
        if self.path.startswith("/v1/runs/") and self.path.endswith("/bundle"):
            self._send_json({"stored": True, "bundle_id": payload["manifest"]["bundle_id"]})
            return
        if self.path == "/run-configs":
            self._send_json({"stored": True, "run_config_id": payload["run_config_id"]})
            return
        key = (self.command, self.path)
        self._send_json(self.responses.get(key, {}), status=self.response_statuses.get(key, 200))

    def log_message(self, format, *args):  # pragma: no cover
        return

    def _record_request(self):
        content_length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(content_length) if content_length else b""
        payload = json.loads(body.decode("utf-8")) if body else None
        self.requests.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers),
                "payload": payload,
            }
        )
        return payload

    def _send_json(self, payload, status=200):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class _HttpHarness(object):
    def __init__(self):
        self.server = None
        self.thread = None
        self.base_url = None

    def __enter__(self):
        _CaptureHandler.responses = {}
        _CaptureHandler.response_statuses = {}
        _CaptureHandler.requests = []
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.server = ThreadingHTTPServer(("127.0.0.1", port), _CaptureHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = "http://127.0.0.1:%d" % port
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)


class TransportHttpTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="infergrade-transport-")

    def tearDown(self):
        shutil.rmtree(self.tempdir)
        os.environ.pop("INFERGRADE_HUB_TOKEN", None)
        os.environ.pop("INFERGRADE_API_TOKEN", None)

    def _write_bundle(self, include_summary=True):
        bundle_dir = os.path.join(self.tempdir, "bundle")
        os.makedirs(os.path.join(bundle_dir, "results"))
        with open(os.path.join(bundle_dir, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump({"bundle_id": "bundle-http", "files": {"results": ["results/interactive_chat_v1.json"]}}, handle)
        with open(os.path.join(bundle_dir, "results", "interactive_chat_v1.json"), "w", encoding="utf-8") as handle:
            json.dump({"result_id": "result-http", "bundle_id": "bundle-http"}, handle)
        with open(os.path.join(bundle_dir, "validation.json"), "w", encoding="utf-8") as handle:
            json.dump({"server": {"valid": True}}, handle)
        if include_summary:
            with open(os.path.join(bundle_dir, "summary.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "bundle_id": "bundle-http",
                        "result_count": 1,
                        "result_ids": ["result-http"],
                        "deployment_profiles": ["interactive_chat_v1"],
                    },
                    handle,
                )
        return bundle_dir

    def test_bundle_payload_reads_results_and_existing_summary(self):
        bundle_dir = self._write_bundle(include_summary=True)
        payload = bundle_payload(bundle_dir)
        self.assertEqual(payload["manifest"]["bundle_id"], "bundle-http")
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["summary"]["result_count"], 1)

    def test_bundle_payload_uses_manifest_result_list(self):
        bundle_dir = self._write_bundle(include_summary=True)
        with open(os.path.join(bundle_dir, "results", "injected.json"), "w", encoding="utf-8") as handle:
            json.dump({"result_id": "injected", "bundle_id": "bundle-http"}, handle)

        payload = bundle_payload(bundle_dir)

        self.assertEqual([item["result_id"] for item in payload["results"]], ["result-http"])

    def test_bundle_payload_generated_summary_uses_manifest_result_list(self):
        bundle_dir = self._write_bundle(include_summary=False)
        with open(os.path.join(bundle_dir, "results", "injected.json"), "w", encoding="utf-8") as handle:
            json.dump({"result_id": "injected", "bundle_id": "bundle-http"}, handle)

        payload = bundle_payload(bundle_dir)

        self.assertEqual([item["result_id"] for item in payload["results"]], ["result-http"])
        self.assertEqual(payload["summary"]["result_count"], 1)
        self.assertEqual(payload["summary"]["result_ids"], ["result-http"])

    def test_bundle_payload_supports_legacy_summary_result_ids(self):
        bundle_dir = self._write_bundle(include_summary=True)
        with open(os.path.join(bundle_dir, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump({"bundle_id": "bundle-http"}, handle)
        with open(os.path.join(bundle_dir, "results", "injected.json"), "w", encoding="utf-8") as handle:
            json.dump({"result_id": "injected", "bundle_id": "bundle-http"}, handle)

        payload = bundle_payload(bundle_dir)

        self.assertEqual([item["result_id"] for item in payload["results"]], ["result-http"])

    def test_bundle_payload_rejects_legacy_bundle_without_result_ids(self):
        bundle_dir = self._write_bundle(include_summary=False)
        with open(os.path.join(bundle_dir, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump({"bundle_id": "bundle-http"}, handle)

        with self.assertRaises(ValueError):
            bundle_payload(bundle_dir)

    def test_bundle_payload_rejects_unsafe_manifest_result_path(self):
        bundle_dir = self._write_bundle(include_summary=True)
        with open(os.path.join(bundle_dir, "manifest.json"), "w", encoding="utf-8") as handle:
            json.dump({"bundle_id": "bundle-http", "files": {"results": ["../secret.json"]}}, handle)

        with self.assertRaises(ValueError):
            bundle_payload(bundle_dir)

    def test_transport_calls_use_expected_paths_and_auth_headers(self):
        bundle_dir = self._write_bundle(include_summary=True)
        with _HttpHarness() as server:
            _CaptureHandler.responses = {
                ("GET", "/run-configs"): {"run_configs": [{"run_config_id": "rcfg_listed"}]},
                ("GET", "/run-configs/rcfg_fetch"): {"run_config_id": "rcfg_fetch"},
            }

            published = publish_run_config(
                server.base_url,
                request_payload={
                    "spec_version": "0.1-draft",
                    "run": {"model": "TinyLlama/TinyLlama-1.1B-Chat-v1.0", "backend": "llama.cpp", "tier": "canary"},
                },
                name="TinyLlama publish",
                api_token="example-secret",
            )
            uploaded = upload_bundle(bundle_dir, server.base_url, api_token="example-secret")
            run_uploaded = upload_run_bundle(bundle_dir, server.base_url, run_id="run-http", api_token="runner-secret")
            listed = list_run_configs(server.base_url, api_token="example-secret")
            fetched = fetch_run_config(server.base_url, "rcfg_fetch", api_token="example-secret")

        self.assertTrue(published["stored"])
        self.assertEqual(uploaded["bundle_id"], "bundle-http")
        self.assertEqual(run_uploaded["bundle_id"], "bundle-http")
        self.assertEqual(listed["run_configs"][0]["run_config_id"], "rcfg_listed")
        self.assertEqual(fetched["run_config_id"], "rcfg_fetch")

        paths = [item["path"] for item in _CaptureHandler.requests]
        self.assertIn("/run-configs", paths)
        self.assertIn("/bundles", paths)
        self.assertIn("/v1/runs/run-http/bundle", paths)
        self.assertIn("/run-configs/rcfg_fetch", paths)
        auth_by_path = {item["path"]: item["headers"].get("Authorization") for item in _CaptureHandler.requests}
        self.assertEqual(auth_by_path["/run-configs"], "Bearer example-secret")
        self.assertEqual(auth_by_path["/bundles"], "Bearer example-secret")
        self.assertEqual(auth_by_path["/run-configs/rcfg_fetch"], "Bearer example-secret")
        self.assertEqual(auth_by_path["/v1/runs/run-http/bundle"], "Bearer runner-secret")

    def test_hub_token_env_is_used_before_legacy_api_token(self):
        os.environ["INFERGRADE_API_TOKEN"] = "legacy-token"
        os.environ["INFERGRADE_HUB_TOKEN"] = "hub-token"
        self.assertEqual(_resolve_api_token(), "hub-token")

    def test_redeem_runner_pairing_surfaces_api_error_code_and_message(self):
        with _HttpHarness() as server:
            _CaptureHandler.responses = {
                ("POST", "/v1/runner-pairings/redeem"): {
                    "error": {
                        "code": "pair_code_expired",
                        "message": "runner pairing code has expired",
                    }
                }
            }
            _CaptureHandler.response_statuses = {
                ("POST", "/v1/runner-pairings/redeem"): 410,
            }

            with self.assertRaises(RuntimeError) as caught:
                redeem_runner_pairing(server.base_url, "igrp_expired")

        self.assertIn("pair_code_expired", str(caught.exception))
        self.assertIn("HTTP 410", str(caught.exception))
        self.assertIn("runner pairing code has expired", str(caught.exception))

    def test_runner_token_revoked_raises_non_retryable_error(self):
        with _HttpHarness() as server:
            _CaptureHandler.responses = {
                ("POST", "/v1/runners/runner-revoked/heartbeat"): {"error": "runner_token_revoked", "runner_id": "runner-revoked"}
            }
            _CaptureHandler.response_statuses = {
                ("POST", "/v1/runners/runner-revoked/heartbeat"): 401,
            }

            from infergrade.transport import heartbeat_runner

            with self.assertRaises(RunnerTokenInvalidError) as caught:
                heartbeat_runner(server.base_url, "runner-revoked", api_token="qbhr_revoked")

        self.assertIn("re-pair", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
