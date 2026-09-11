import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.models import CapabilityExecution
from infergrade.reasoning_constraint_stress_v2_qualification import (
    BENCHMARK_ID as QUALIFICATION_BENCHMARK_ID,
)
from infergrade.reports import render_bundle_report


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="infergrade-report-")

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_qualification_diagnostics_render_unfiltered_counts_and_fixed_links(self):
        artifact_dir = os.path.join(
            self.tempdir,
            "artifacts",
            "capability",
            QUALIFICATION_BENCHMARK_ID,
        )
        os.makedirs(artifact_dir)
        for filename in ("summary.json", "capability_run.json"):
            with open(os.path.join(artifact_dir, filename), "w", encoding="utf-8") as handle:
                handle.write("{}\n")

        execution = self._qualification_execution(
            {
                "benchmark_id": QUALIFICATION_BENCHMARK_ID,
                "display_name": "Reasoning constraint stress v2 qualification",
                "total_cases": 5,
                "completed_cases": 5,
                "generation_failure_count": 0,
                "unscored_generation_failure_count": 0,
                "generation_policy_id": "reasoning_constraint_stress_qualification_thinking_v1",
                "generation_policy_fingerprint": "a" * 64,
                "metrics": {
                    "correct_count": 2,
                    "total_count": 5,
                    "format_invalid_count": 3,
                    "token_budget_exhaustion_count": 2,
                    "generation_failure_count": 0,
                    "unscored_generation_failure_count": 0,
                    "diagnostic_semantic_candidate_count": 3,
                    "diagnostic_semantic_correct_count": 3,
                    "diagnostic_semantic_unavailable_count": 2,
                    "diagnostic_failure_class_counts": {
                        "format_only": 1,
                        "substantive_wrong": 0,
                        "unavailable": 2,
                    },
                    "policy_enforcement_states": {"requested_unverified": 5},
                },
            }
        )

        report = render_bundle_report(
            {},
            {},
            {"valid": True},
            [{}],
            capability_execution=execution,
            output_dir=self.tempdir,
        )

        self.assertIn("## Qualification Diagnostics", report)
        self.assertIn("Strict result (diagnostic only): 2/5 correct", report)
        self.assertIn("Cases completed: 5/5", report)
        self.assertIn("Format-invalid outputs: 3", report)
        self.assertIn("Token-budget exhaustions: 2", report)
        self.assertIn("Generation failures: 0 (unscored: 0)", report)
        self.assertIn("Diagnostic semantic candidates: 3 (correct: 3; unavailable: 2)", report)
        self.assertIn(
            "Diagnostic failure classes: format-only 1; substantive wrong 0; unavailable 2",
            report,
        )
        self.assertIn("Frozen policy fingerprint: `" + ("a" * 64) + "`", report)
        self.assertIn("Enforcement truth: requested_unverified (5/5 cases)", report)
        self.assertIn(
            "Evidence role: diagnostic only; excluded from headline capability evidence and canonical promotion.",
            report,
        )
        self.assertIn(
            "[summary.json](artifacts/capability/%s/summary.json)" % QUALIFICATION_BENCHMARK_ID,
            report,
        )
        self.assertIn(
            "[capability_run.json](artifacts/capability/%s/capability_run.json)"
            % QUALIFICATION_BENCHMARK_ID,
            report,
        )
        self.assertNotIn("/private/raw", report)
        self.assertNotIn("predictions.jsonl", report)

    def test_missing_qualification_diagnostics_fail_closed_without_zero_counts(self):
        report = render_bundle_report(
            {},
            {},
            {"valid": True},
            [{}],
            capability_execution=self._qualification_execution(None),
            output_dir=self.tempdir,
        )

        self.assertIn("## Qualification Diagnostics", report)
        self.assertIn(
            "Diagnostic result: unavailable; the qualification execution did not record a benchmark result.",
            report,
        )
        self.assertIn("Strict result (diagnostic only): n/a", report)
        self.assertIn("Format-invalid outputs: n/a", report)
        self.assertIn("Token-budget exhaustions: n/a", report)
        self.assertIn("Generation failures: n/a", report)
        self.assertNotIn("0/0", report)

    def test_invalid_qualification_diagnostic_fields_render_as_unknown(self):
        report = render_bundle_report(
            {},
            {},
            {"valid": True},
            [{}],
            capability_execution=self._qualification_execution(
                {
                    "benchmark_id": QUALIFICATION_BENCHMARK_ID,
                    "display_name": "/private/raw/display-name",
                    "total_cases": 5,
                    "completed_cases": 9,
                    "generation_failure_count": "0",
                    "generation_policy_id": "/private/raw/policy",
                    "generation_policy_fingerprint": "not-a-sha256",
                    "metrics": {
                        "correct_count": "2",
                        "format_invalid_count": 6,
                        "token_budget_exhaustion_count": -1,
                        "policy_enforcement_states": {
                            "requested_unverified": 9,
                            "/private/raw/state": 1,
                        },
                    },
                }
            ),
            output_dir=self.tempdir,
        )

        self.assertIn("Strict result (diagnostic only): n/a correct", report)
        self.assertIn("Cases completed: n/a", report)
        self.assertIn("Format-invalid outputs: n/a", report)
        self.assertIn("Token-budget exhaustions: n/a", report)
        self.assertIn("Generation failures: n/a (unscored: n/a)", report)
        self.assertIn("Frozen policy fingerprint: `n/a`", report)
        self.assertIn("Enforcement truth: n/a", report)
        self.assertIn("Benchmark: Reasoning constraint stress v2 qualification", report)
        self.assertNotIn("/private/raw", report)

    def test_normal_report_without_qualification_execution_is_unchanged(self):
        manifest = {"bundle_id": "bundle", "created_at": "2026-09-11T00:00:00Z", "files": {}}
        summary = {"bundle_id": "bundle", "result_count": 1, "simulated": True}
        validation = {"valid": True}
        results = [{}]

        without_optional = render_bundle_report(manifest, summary, validation, results)
        with_explicit_none = render_bundle_report(
            manifest,
            summary,
            validation,
            results,
            capability_execution=None,
        )

        self.assertEqual(without_optional, with_explicit_none)
        self.assertNotIn("## Qualification Diagnostics", without_optional)

    @staticmethod
    def _qualification_execution(result):
        return CapabilityExecution(
            use_case="reasoning",
            suite_id=None,
            suite_ids=[],
            benchmark_tier="canary",
            benchmark_group_ids=[],
            benchmark_check_ids=[QUALIFICATION_BENCHMARK_ID],
            components=["Reasoning constraint stress v2 qualification"],
            score=None,
            score_method=None,
            component_scores={},
            confidence=None,
            status="not_comparable",
            benchmark_results=(
                {QUALIFICATION_BENCHMARK_ID: result} if result is not None else {}
            ),
            artifacts={
                QUALIFICATION_BENCHMARK_ID: {
                    "summary_path": "/private/raw/summary.json",
                    "capability_run_path": "/private/raw/capability_run.json",
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
