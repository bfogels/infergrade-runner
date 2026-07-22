import os
import ssl
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.tls import tls_trust_configuration, verified_https_context


class TlsTrustTests(unittest.TestCase):
    def test_explicit_ca_bundle_is_used_for_https(self):
        with tempfile.TemporaryDirectory() as tempdir:
            cafile = Path(tempdir) / "ca.pem"
            cafile.write_text("fixture", encoding="utf-8")
            with mock.patch.dict(os.environ, {"SSL_CERT_FILE": str(cafile)}, clear=False):
                with mock.patch("infergrade.tls.ssl.create_default_context", return_value="context") as context_mock:
                    self.assertEqual(verified_https_context("https://infergrade.com"), "context")

        context_mock.assert_called_once_with(cafile=str(cafile))

    def test_missing_explicit_ca_bundle_fails_closed(self):
        with mock.patch.dict(os.environ, {"SSL_CERT_FILE": "/missing/infergrade-ca.pem"}, clear=False):
            self.assertEqual(tls_trust_configuration()["source"], "invalid_ssl_cert_file")
            with self.assertRaisesRegex(RuntimeError, "missing CA bundle"):
                verified_https_context("https://infergrade.com")

    def test_certifi_is_used_when_python_default_cafile_is_absent(self):
        defaults = ssl.DefaultVerifyPaths(None, None, None, None, None, None)
        with tempfile.TemporaryDirectory() as tempdir:
            cafile = Path(tempdir) / "certifi.pem"
            cafile.write_text("fixture", encoding="utf-8")
            certifi = mock.Mock()
            certifi.where.return_value = str(cafile)
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("infergrade.tls.ssl.get_default_verify_paths", return_value=defaults):
                    with mock.patch.dict(sys.modules, {"certifi": certifi}):
                        self.assertEqual(tls_trust_configuration(), {"source": "certifi", "cafile": str(cafile)})

    def test_local_http_does_not_create_tls_context(self):
        with mock.patch("infergrade.tls.ssl.create_default_context") as context_mock:
            self.assertIsNone(verified_https_context("http://127.0.0.1:8000"))
        context_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
