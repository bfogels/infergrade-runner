import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.transport import (
    InsecureApiUrlError,
    _json_request,
    _request_headers,
    _resolve_api_token,
    _resolve_run_token,
    require_secure_api_url,
)


class TransportTests(unittest.TestCase):
    def test_request_headers_include_bearer_token(self):
        headers = _request_headers(api_token="example-secret", content_type="application/json")
        self.assertEqual(headers["Authorization"], "Bearer example-secret")
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_run_token_takes_precedence_over_api_token(self):
        headers = _request_headers(api_token="example-secret", run_token="run-secret")
        self.assertEqual(headers["Authorization"], "Bearer run-secret")

    def test_api_token_falls_back_to_environment(self):
        with mock.patch.dict(os.environ, {"INFERGRADE_API_TOKEN": "env-secret"}, clear=False):
            self.assertEqual(_resolve_api_token(), "env-secret")

    def test_run_token_falls_back_to_environment(self):
        with mock.patch.dict(os.environ, {"INFERGRADE_RUN_TOKEN": "run-env-secret"}, clear=False):
            self.assertEqual(_resolve_run_token(), "run-env-secret")

    def test_explicit_api_token_wins_over_environment(self):
        with mock.patch.dict(os.environ, {"INFERGRADE_API_TOKEN": "env-secret"}, clear=False):
            self.assertEqual(_resolve_api_token("direct-secret"), "direct-secret")

    def test_secure_api_url_allows_https_and_local_http(self):
        self.assertEqual(require_secure_api_url("https://hub.infergrade.dev"), "https://hub.infergrade.dev")
        self.assertEqual(require_secure_api_url("http://localhost:8000"), "http://localhost:8000")
        self.assertEqual(require_secure_api_url("http://127.0.0.1:8000"), "http://127.0.0.1:8000")
        self.assertEqual(require_secure_api_url("http://127.1.2.3:8000"), "http://127.1.2.3:8000")
        self.assertEqual(require_secure_api_url("http://[::1]:8000"), "http://[::1]:8000")

    def test_secure_api_url_refuses_remote_http(self):
        for api_url in ("http://hub.example.com", "http://192.168.1.25:8000", "http://localhost.example.com:8000"):
            with self.subTest(api_url=api_url):
                with self.assertRaises(InsecureApiUrlError) as caught:
                    require_secure_api_url(api_url)

                self.assertIn("https://", str(caught.exception))
                self.assertIn("localhost", str(caught.exception))

    def test_json_request_refuses_remote_http_before_urlopen(self):
        with mock.patch("infergrade.transport.urllib_request.urlopen") as urlopen_mock:
            with self.assertRaises(InsecureApiUrlError):
                _json_request("http://hub.example.com", "/run-configs", api_token="secret-token")

        urlopen_mock.assert_not_called()
