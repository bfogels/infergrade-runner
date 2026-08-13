import unittest
from copy import deepcopy

from infergrade.benchmark_catalog import load_capability_catalog
from infergrade.benchmark_tier_adequacy import audit_benchmark_tier_adequacy


class BenchmarkTierAdequacyTests(unittest.TestCase):
    def test_current_tier_sampling_contracts_are_complete(self):
        report = audit_benchmark_tier_adequacy(load_capability_catalog())

        self.assertTrue(report["ready"])
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["varying_tier_benchmark_count"], 14)
        self.assertEqual(report["errors"], [])
        self.assertTrue(all(item["ready"] for item in report["benchmarks"]))

    def test_missing_or_stale_policy_fails_closed(self):
        catalog = deepcopy(load_capability_catalog())
        catalog["tier_sampling_policies"].pop("ifeval")
        catalog["tier_sampling_policies"]["evalplus_mbpp"]["case_limits"][
            "canary"
        ] = 20
        catalog["tier_sampling_policies"]["bfcl_local_reference_v1"][
            "selection_identity_policy"
        ] = "source_snapshot_only"

        report = audit_benchmark_tier_adequacy(catalog)

        self.assertFalse(report["ready"])
        self.assertIn("ifeval:missing_tier_sampling_policy", report["errors"])
        self.assertIn("evalplus_mbpp:case_limits_mismatch", report["errors"])
        self.assertIn(
            "bfcl_local_reference_v1:selection_identity_not_exact",
            report["errors"],
        )

    def test_balanced_strategy_requires_declared_strata(self):
        catalog = deepcopy(load_capability_catalog())
        catalog["tier_sampling_policies"]["stateful_tool_loop_diagnostic_v1"][
            "stratification_fields"
        ] = []

        report = audit_benchmark_tier_adequacy(catalog)

        self.assertIn(
            "stateful_tool_loop_diagnostic_v1:missing_stratification_fields",
            report["errors"],
        )


if __name__ == "__main__":
    unittest.main()
