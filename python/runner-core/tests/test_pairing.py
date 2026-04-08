import os
import tempfile
import unittest

import sys

sys.path.insert(0, "python/runner-core/src")

from infergrade.pairing import (
    clear_runner_profile,
    load_runner_profile,
    resolve_runner_api_token,
    resolve_runner_api_url,
    resolve_runner_execution_mode,
    resolve_runner_id,
    runner_profile_path,
    save_runner_profile,
)


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.original = os.environ.get("INFERGRADE_CONFIG_DIR")
        os.environ["INFERGRADE_CONFIG_DIR"] = self.tempdir.name

    def tearDown(self):
        if self.original is None:
            os.environ.pop("INFERGRADE_CONFIG_DIR", None)
        else:
            os.environ["INFERGRADE_CONFIG_DIR"] = self.original

    def test_save_and_load_runner_profile(self):
        path = save_runner_profile(
            {
                "api_url": "http://localhost:8000",
                "access_token": "qbhr_pair_test",
                "label": "Brian MacBook Pro",
            }
        )
        self.assertEqual(path, runner_profile_path())
        loaded = load_runner_profile()
        self.assertEqual(loaded["api_url"], "http://localhost:8000")
        self.assertEqual(resolve_runner_api_url(None), "http://localhost:8000")
        self.assertEqual(resolve_runner_api_token(None), "qbhr_pair_test")

    def test_resolve_runner_identity_from_saved_profile(self):
        save_runner_profile(
            {
                "api_url": "http://localhost:8000",
                "access_token": "qbhr_pair_test",
                "runner_id": "runner_saved",
                "preferred_execution_mode": "local_native",
            }
        )
        self.assertEqual(resolve_runner_id(None), "runner_saved")
        self.assertEqual(resolve_runner_execution_mode(None), "local_native")

    def test_clear_runner_profile(self):
        save_runner_profile({"api_url": "http://localhost:8000", "access_token": "qbhr_pair_test"})
        self.assertTrue(clear_runner_profile())
        self.assertIsNone(load_runner_profile())
        self.assertFalse(clear_runner_profile())


if __name__ == "__main__":
    unittest.main()
