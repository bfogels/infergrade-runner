import json
import unittest

from test_contracts import _validate_schema_subset
from infergrade.contracts import repo_root

from infergrade.adapters.llama_cpp import _metrics_from_server_completion
from infergrade.capabilities import _summarize_task_performance_rows
from infergrade.capability_summary import _surface_task_performance_summary


class TaskTimingObservationsTests(unittest.TestCase):
    def test_elapsed_source_preserves_zero_and_distinguishes_fallback(self):
        completion = {"final_payload": {"timings": {"prompt_ms": 3, "predicted_ms": 7}}, "elapsed_ms": 0}
        metrics = _metrics_from_server_completion(completion, {}, None, None)
        self.assertEqual(metrics["latency_ms"], 0)
        self.assertEqual(metrics["latency_measurement_source"], "request_elapsed")
        completion["elapsed_ms"] = float("inf")
        metrics = _metrics_from_server_completion(completion, {}, None, None)
        self.assertEqual(metrics["latency_ms"], 10)
        self.assertEqual(metrics["latency_measurement_source"], "compute_timing")
        metrics = _metrics_from_server_completion({"final_payload": {}}, {"total_time_ms": 42}, None, None)
        self.assertEqual(metrics["latency_measurement_source"], "parsed_timing")

    def test_observations_preserve_denominators_and_omit_private_content(self):
        rows = [
            {"benchmark_id": "bench", "case_id": "private-case", "task_revision": "a" * 64, "generation_status": "completed", "latency_ms": 2000,
             "latency_measurement_source": "request_elapsed", "natural_stop": False, "token_budget_exhausted": True,
             "direct_answer_protocol_recovery": {"status": "recovered"}, "prompt": "private-prompt", "output_text": "private-output"},
            {"benchmark_id": "bench", "case_id": "failed-case", "generation_status": "failed", "latency_ms": float("nan")},
        ]
        summary = _summarize_task_performance_rows(rows)
        self.assertTrue(summary["item_observations_complete"])
        first, failed = summary["item_observations"]
        self.assertEqual(len(first["task_key"]), 64)
        self.assertEqual(first["task_revision"], "a" * 64)
        self.assertTrue(first["protocol_recovery"])
        self.assertTrue(first["token_budget_exhausted"])
        self.assertEqual(failed["generation_status"], "failed")
        self.assertIsNone(failed["latency_ms"])
        self.assertNotIn("private-", json.dumps(summary))

    def test_rollup_transports_unequal_item_sets_without_collapsing_to_medians(self):
        artifacts = []
        for values in ([1000], [9000, 10000, 11000]):
            rows = [{"benchmark_id": "bench", "case_id": str(value), "generation_status": "completed", "latency_ms": value} for value in values]
            artifacts.append({"task_performance": _summarize_task_performance_rows(rows)})
        rollup = _surface_task_performance_summary(artifacts)
        self.assertTrue(rollup["item_observations_complete"])
        self.assertEqual([item["latency_ms"] for item in rollup["item_observations"]], [1000, 9000, 10000, 11000])
        artifacts.append({"task_performance": {"attempted_task_count": 1}})
        self.assertFalse(_surface_task_performance_summary(artifacts)["item_observations_complete"])

    def test_sample_schema_validates_payload_and_rejects_private_fields(self):
        schema = json.loads((repo_root() / "schemas/json/task_timing_sample.schema.json").read_text())
        sample = _summarize_task_performance_rows([{}])["item_observations"][0]
        _validate_schema_subset(sample, schema)
        with self.assertRaises(AssertionError):
            _validate_schema_subset(dict(sample, prompt="private"), schema)
        for name in ("capability_run", "capability_summary", "result_record"):
            source = (repo_root() / ("schemas/json/%s.schema.json" % name)).read_text()
            self.assertIn('"$ref": "task_timing_sample.schema.json"', source)

    def test_bound_is_explicit_and_missing_identity_remains_missing(self):
        summary = _summarize_task_performance_rows([{}] * 10001)
        self.assertFalse(summary["item_observations_complete"])
        self.assertEqual(len(summary["item_observations"]), 10000)
        self.assertIsNone(summary["item_observations"][0]["task_key"])


if __name__ == "__main__":
    unittest.main()
