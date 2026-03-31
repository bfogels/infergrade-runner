import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.transport import _request_headers, _resolve_api_token


class TransportTests(unittest.TestCase):
    def test_request_headers_include_bearer_token(self):
        headers = _request_headers(api_token="alpha-secret", content_type="application/json")
        self.assertEqual(headers["Authorization"], "Bearer alpha-secret")
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_api_token_falls_back_to_environment(self):
        with mock.patch.dict(os.environ, {"INFERGRADE_API_TOKEN": "env-secret"}, clear=False):
            self.assertEqual(_resolve_api_token(), "env-secret")

    def test_explicit_api_token_wins_over_environment(self):
        with mock.patch.dict(os.environ, {"INFERGRADE_API_TOKEN": "env-secret"}, clear=False):
            self.assertEqual(_resolve_api_token("direct-secret"), "direct-secret")
