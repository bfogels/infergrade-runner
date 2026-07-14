import unittest

from infergrade.capability_calibration import audit_capability_observations, extract_calibration_observations


class CapabilityCalibrationTests(unittest.TestCase):
    def test_audit_blocks_small_or_saturated_corpus_without_rescaling_scores(self):
        observations = [
            {"score_version": "local_assistant_score_v4", "score": 1.0, "model_family": "A", "parameter_band": "under_3b"},
            {"score_version": "local_assistant_score_v4", "score": 1.0, "model_family": "A", "parameter_band": "under_3b"},
        ]
        report = audit_capability_observations(observations, "local_assistant_score_v4")
        self.assertEqual(report["status"], "insufficient_calibration")
        self.assertFalse(report["headline_ready"])
        self.assertEqual(report["metrics"]["maximum"], 1.0)
        self.assertIn("suite_ceiling_fraction_above_limit", report["blockers"])

    def test_audit_passes_diverse_distribution_with_headroom(self):
        scores = [0.12, 0.18, 0.24, 0.31, 0.37, 0.43, 0.49, 0.54, 0.59, 0.64,
                  0.15, 0.22, 0.29, 0.35, 0.41, 0.47, 0.52, 0.57, 0.62, 0.68]
        observations = [
            {
                "score_version": "local_assistant_score_v4",
                "score": score,
                "model_family": "family-%d" % (index % 5),
                "parameter_band": ["under_3b", "3b_to_under_8b", "8b_to_under_20b"][index % 3],
            }
            for index, score in enumerate(scores)
        ]
        report = audit_capability_observations(observations, "local_assistant_score_v4")
        self.assertEqual(report["status"], "calibrated_headroom")
        self.assertTrue(report["headline_ready"])
        self.assertEqual(report["blockers"], [])

    def test_extracts_raw_attainment_from_result_record(self):
        observations = extract_calibration_observations(
            [{
                "result_id": "result-1",
                "capability": {"capability_score_details": {
                    "score_version": "local_assistant_score_v4",
                    "surface_id": "local_assistant_capability",
                    "raw_attainment": 0.625,
                    "score_ready": True,
                }},
                "ontology": {"model_family": {"family_name": "Qwen3.5", "parameter_scale": "9B"}},
            }]
        )
        self.assertEqual(observations[0]["score"], 0.625)
        self.assertEqual(observations[0]["parameter_band"], "8b_to_under_20b")

    def test_export_file_keeps_multiple_result_ids(self):
        documents = []
        for index, score in enumerate((0.25, 0.5), start=1):
            documents.append({
                "_source": "/tmp/results-export.json",
                "result_id": "result-%d" % index,
                "capability": {"capability_score_details": {
                    "score_version": "local_assistant_score_v4",
                    "score_ready": True,
                    "raw_attainment": score,
                }},
            })

        observations = extract_calibration_observations(documents, score_version="local_assistant_score_v4")

        self.assertEqual([item["score"] for item in observations], [0.25, 0.5])

    def test_extracts_component_observation_without_mislabeling_it_as_full_score(self):
        observations = extract_calibration_observations(
            [{
                "artifact_kind": "capability_run",
                "capability_run_id": "caprun-1",
                "protocol": {
                    "task_version": "assistant_compositional_instruction_v2",
                    "fixture_revision": "2026-07-assistant-compositional-v2",
                },
                "summary": {"score": 0.458333, "state": "scored"},
                "subject": {"model": {"model": "Qwen/Qwen3.5-9B"}},
                "evidence": {"surface": "local_assistant_capability"},
            }],
            benchmark_id="assistant_compositional_instruction_v2",
        )

        self.assertEqual(observations[0]["benchmark_id"], "assistant_compositional_instruction_v2")
        self.assertEqual(observations[0]["score_version"], "benchmark:assistant_compositional_instruction_v2:2026-07-assistant-compositional-v2")


if __name__ == "__main__":
    unittest.main()
