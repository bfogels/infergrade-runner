import copy
import datetime as dt
import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "check_llama_cpp_runtime_policy.py"
POLICY_PATH = ROOT / "runtime" / "llama_cpp_release_policy.json"


def load_module():
    spec = importlib.util.spec_from_file_location("check_llama_cpp_runtime_policy", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LlamaCppRuntimePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    def test_checked_in_policy_matches_all_pin_locations(self):
        self.assertEqual(self.module.validate_policy(self.policy, root=ROOT), [])

    def test_source_pin_drift_is_a_hard_failure(self):
        policy = copy.deepcopy(self.policy)
        policy["pins"][0]["locations"][0]["needle"] = "ARG LLAMA_CPP_REF=not-the-pin"
        failures = self.module.validate_policy(policy, root=ROOT)
        self.assertTrue(any("source pin does not match" in item for item in failures))

    def test_new_upstream_release_is_advisory_candidate(self):
        latest = {
            "tag_name": "b10001",
            "published_at": "2026-07-15T05:29:11Z",
            "html_url": "https://github.com/ggml-org/llama.cpp/releases/tag/b10001",
        }
        report = self.module.build_report(
            self.policy,
            latest_release=latest,
            now=dt.datetime(2026, 7, 14, 12, tzinfo=dt.timezone.utc),
        )
        self.assertTrue(report["candidate_available"])
        self.assertFalse(report["stable_promotion_automatic"])
        self.assertFalse(report["runner_release_required"])
        self.assertFalse(any(pin["review_due"] for pin in report["pins"] if pin["channel"] == "infergrade_stable"))

    def test_stable_pin_age_triggers_review_without_forcing_latest(self):
        report = self.module.build_report(
            self.policy,
            now=dt.datetime(2026, 9, 1, 12, tzinfo=dt.timezone.utc),
        )
        self.assertTrue(any(pin["review_due"] for pin in report["pins"] if pin["channel"] == "infergrade_stable"))

    def test_default_cli_succeeds_when_upstream_is_newer(self):
        latest = {
            "tag_name": "b10001",
            "published_at": "2026-07-15T05:29:11Z",
            "html_url": "https://github.com/ggml-org/llama.cpp/releases/tag/b10001",
        }
        with tempfile.TemporaryDirectory() as tmp:
            latest_path = pathlib.Path(tmp) / "latest.json"
            report_path = pathlib.Path(tmp) / "report.json"
            latest_path.write_text(json.dumps(latest), encoding="utf-8")
            exit_code = self.module.main(
                ["--latest-release-json", str(latest_path), "--report-json", str(report_path)]
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 0)
        self.assertTrue(report["candidate_available"])

    def test_require_current_is_opt_in_and_fails_on_candidate(self):
        latest = {
            "tag_name": "b10001",
            "published_at": "2026-07-15T05:29:11Z",
            "html_url": "https://github.com/ggml-org/llama.cpp/releases/tag/b10001",
        }
        with tempfile.TemporaryDirectory() as tmp:
            latest_path = pathlib.Path(tmp) / "latest.json"
            latest_path.write_text(json.dumps(latest), encoding="utf-8")
            exit_code = self.module.main(["--latest-release-json", str(latest_path), "--require-current"])
        self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
