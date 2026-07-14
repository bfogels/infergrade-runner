import json
import sys
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.capability_contract import (
    CAPABILITY_STATES,
    CONFIDENCE_LABELS,
    EVIDENCE_LANES,
    capability_run_schema_path,
    capability_summary_schema_path,
    load_capability_run_schema,
    load_capability_summary_schema,
    validate_capability_run_artifact,
    validate_capability_summary_artifact,
)
from infergrade.contracts import load_contract_manifest


def _artifact():
    return {
        "artifact_spec_version": "0.1.0",
        "artifact_kind": "capability_run",
        "capability_run_id": "caprun_20260507_example",
        "created_at": "2026-05-07T12:00:00Z",
        "runner": {"name": "infergrade-runner", "version": "0.2.7-dev", "contract_version": "0.1.0"},
        "evidence": {
            "lane": "decision",
            "surface": "local_assistant_capability",
            "grade": "thin_local_sample",
            "experimental": True,
            "confidence_label": "thin_local_sample",
        },
        "subject": {
            "model": {"model_base": "example-local-model", "quant_artifact_sha256": "abc123"},
            "runtime": {"backend_engine": "llama.cpp", "backend_version": "example"},
            "hardware": {"os": "macOS", "accelerator_type": "metal"},
            "generation_preset": {"temperature": 0.0, "max_tokens": 128},
        },
        "protocol": {
            "task_family": "assistant_instruction_following",
            "prompt_version": "assistant_decision_v1",
            "task_version": "assistant_decision_v1",
            "fixture_revision": "fixtures-assistant-v1",
            "dataset_revision": None,
            "scorer_type": "exact_match",
            "scoring_policy": "instruction_following_primary_accuracy_v1",
            "repetitions": 1,
        },
        "summary": {
            "state": "scored",
            "score": 1.0,
            "score_dimension": "instruction_following",
            "passed_count": 1,
            "failed_count": 0,
            "partial_count": 0,
            "skipped_count": 0,
            "not_comparable_count": 0,
            "duration_seconds": 2.4,
            "time_to_first_token_ms": 120.0,
            "tokens_per_second": 32.0,
            "input_tokens": 42,
            "output_tokens": 12,
        },
        "tasks": [
            {
                "task_id": "assistant_fixture_001",
                "task_family": "assistant_instruction_following",
                "state": "scored",
                "score": 1.0,
                "score_dimension": "instruction_following",
                "scorer_type": "exact_match",
                "scoring_policy": "instruction_following_primary_accuracy_v1",
                "output_artifact": "raw_outputs/assistant_fixture_001.json",
                "error_class": None,
                "latency_ms": 2400.0,
                "time_to_first_token_ms": 120.0,
                "tokens_per_second": 32.0,
                "input_tokens": 42,
                "output_tokens": 12,
            }
        ],
        "artifacts": {
            "manifest": "manifest.json",
            "raw_outputs": ["raw_outputs/assistant_fixture_001.json"],
            "scoring_outputs": ["scoring/assistant_fixture_001.json"],
            "supporting_files": [],
        },
        "claim_boundary": {
            "supported_claims": ["This setup completed one pinned local assistant task."],
            "unsupported_claims": ["This is not a global model ranking."],
        },
    }


class CapabilityContractTests(unittest.TestCase):
    def test_capability_run_schema_is_declared_in_contract_manifest(self):
        schema = load_capability_run_schema()
        self.assertEqual(schema["properties"]["artifact_kind"]["const"], "capability_run")
        self.assertEqual(schema["properties"]["evidence"]["properties"]["lane"]["enum"], list(EVIDENCE_LANES))
        self.assertIn("repeated_local_sample", schema["properties"]["evidence"]["properties"]["confidence_label"]["enum"])
        self.assertIn("sampled_reference", schema["properties"]["evidence"]["properties"]["confidence_label"]["enum"])
        self.assertIn("scorer_type", schema["properties"]["protocol"]["required"])
        self.assertTrue(schema["properties"]["summary"]["allOf"])
        self.assertTrue(schema["properties"]["tasks"]["items"]["allOf"])
        self.assertTrue(capability_run_schema_path().exists())
        manifest = load_contract_manifest()
        self.assertIn("schemas/json/capability_run.schema.json", manifest["schema_files"])

    def test_capability_summary_schema_is_declared_in_contract_manifest(self):
        schema = load_capability_summary_schema()
        self.assertEqual(schema["properties"]["artifact_kind"]["const"], "capability_summary")
        labels = schema["$defs"]["confidence_label"]["enum"]
        self.assertIn("repeated_local_sample", labels)
        self.assertIn("sampled_reference", labels)
        self.assertIn("reference_sample", labels)
        self.assertTrue(capability_summary_schema_path().exists())
        manifest = load_contract_manifest()
        self.assertIn("schemas/json/capability_summary.schema.json", manifest["schema_files"])

    def test_valid_capability_run_artifact_passes_semantic_validation(self):
        self.assertEqual(validate_capability_run_artifact(_artifact()), [])

    def test_confidence_labels_use_v0_3_2_canonical_names_with_legacy_aliases_accepted(self):
        self.assertIn("repeated_local_sample", CONFIDENCE_LABELS)
        self.assertIn("sampled_reference", CONFIDENCE_LABELS)
        artifact = _artifact()
        artifact["evidence"]["lane"] = "reference"
        artifact["evidence"]["confidence_label"] = "reference_sample"

        self.assertEqual(validate_capability_run_artifact(artifact), [])

    def test_failed_partial_skipped_and_not_comparable_states_stay_distinct(self):
        states = set(CAPABILITY_STATES)
        self.assertEqual(states, {"scored", "partial", "failed", "skipped", "not_yet_benchmarked", "not_comparable"})
        artifact = _artifact()
        artifact["summary"]["state"] = "partial"
        artifact["summary"]["score"] = 0.5
        artifact["tasks"] = [
            {
                "task_id": "scored",
                "task_family": "assistant_instruction_following",
                "state": "scored",
                "score": 1.0,
                "scorer_type": "exact_match",
                "scoring_policy": "instruction_following_primary_accuracy_v1",
                "output_artifact": "raw/scored.json",
            },
            {
                "task_id": "failed",
                "task_family": "assistant_instruction_following",
                "state": "failed",
                "score": None,
                "output_artifact": "raw/failed.json",
                "error_class": "runtime_failure",
            },
            {
                "task_id": "skipped",
                "task_family": "assistant_instruction_following",
                "state": "skipped",
                "score": None,
                "output_artifact": None,
            },
            {
                "task_id": "not_comparable",
                "task_family": "assistant_instruction_following",
                "state": "not_comparable",
                "score": None,
                "output_artifact": None,
            },
        ]

        self.assertEqual(validate_capability_run_artifact(artifact), [])
        self.assertEqual([task["state"] for task in artifact["tasks"]], ["scored", "failed", "skipped", "not_comparable"])

    def test_failed_states_require_failure_metadata_and_do_not_accept_scores(self):
        artifact = _artifact()
        artifact["summary"]["state"] = "failed"
        artifact["summary"]["score"] = 0.0
        artifact["tasks"][0]["state"] = "failed"
        artifact["tasks"][0]["score"] = 0.0
        artifact["tasks"][0]["error_class"] = None

        errors = validate_capability_run_artifact(artifact)

        self.assertIn("summary.score must be null unless the run is scored or partial", errors)
        self.assertIn("tasks[0].score must be null unless the task is scored or partial", errors)
        self.assertIn("tasks[0].error_class is required when state is failed", errors)

    def test_scored_artifacts_require_scorer_metadata(self):
        artifact = _artifact()
        del artifact["protocol"]["scorer_type"]
        del artifact["tasks"][0]["scorer_type"]
        del artifact["tasks"][0]["scoring_policy"]

        errors = validate_capability_run_artifact(artifact)

        self.assertTrue(any("protocol.scorer_type" in error for error in errors), errors)
        self.assertIn("tasks[0].scorer_type is required", errors)
        self.assertIn("tasks[0].scoring_policy is required", errors)

    def test_invalid_lane_and_surface_are_rejected(self):
        artifact = _artifact()
        artifact["evidence"]["lane"] = "gold/curated"
        artifact["evidence"]["surface"] = "general_assistant"

        errors = validate_capability_run_artifact(artifact)

        self.assertTrue(any("evidence.lane" in error for error in errors), errors)
        self.assertTrue(any("evidence.surface" in error for error in errors), errors)

    def test_schema_json_round_trips(self):
        payload = json.loads(json.dumps(load_capability_run_schema()))
        self.assertEqual(payload["title"], "InferGrade Capability Run Artifact")
        summary_payload = json.loads(json.dumps(load_capability_summary_schema()))
        self.assertEqual(summary_payload["title"], "InferGrade Capability Summary Artifact")

    def test_valid_capability_summary_artifact_passes_semantic_validation(self):
        artifact = {
            "artifact_spec_version": "0.1.0",
            "artifact_kind": "capability_summary",
            "summary_id": "capsum_example",
            "created_at": "2026-05-08T12:00:00Z",
            "runner": {"name": "infergrade-runner", "version": "0.2.11-dev"},
            "subject": {"model": {"model": "example"}, "runtime": {"backend": "llama.cpp"}, "hardware": {"source": "run_bundle_environment"}},
            "surfaces": [
                {
                    "surface": "local_assistant_capability",
                    "state": "scored",
                    "score": 1.0,
                    "lane": "decision",
                    "confidence_label": "thin_local_sample",
                    "repetition_count": 1,
                    "task_count": 3,
                    "failure_count": 0,
                    "partial_count": 0,
                    "capability_artifacts": [],
                    "unsupported_claims": ["This is not a global assistant capability score."],
                }
            ],
            "capability_artifacts": [
                {
                    "artifact_kind": "capability_run",
                    "benchmark_id": "multiturn_chat_memory_v1",
                    "surface": "local_assistant_capability",
                    "state": "scored",
                    "lane": "decision",
                    "confidence_label": "thin_local_sample",
                    "path": "artifacts/capability/multiturn_chat_memory_v1/capability_run.json",
                }
            ],
            "unsupported_claim_summary": ["This summary is not a global intelligence score."],
            "next_recommended_benchmark_action": {
                "action": "run_coding_decision_lane",
                "surface": "local_coding_capability",
                "benchmark_check_id": "coding_static_repair_v1",
                "reason": "This surface is missing local decision-lane evidence.",
            },
        }

        self.assertEqual(validate_capability_summary_artifact(artifact), [])

    def test_summary_confidence_cannot_exceed_evidence_lane_controls(self):
        artifact = {
            "artifact_spec_version": "0.1.0",
            "artifact_kind": "capability_summary",
            "summary_id": "capsum_bad_confidence",
            "created_at": "2026-05-08T12:00:00Z",
            "runner": {"name": "infergrade-runner", "version": "0.2.11-dev"},
            "subject": {},
            "surfaces": [
                {
                    "surface": "local_coding_capability",
                    "state": "scored",
                    "score": 1.0,
                    "lane": "decision",
                    "confidence_label": "sampled_reference",
                    "repetition_count": 1,
                    "task_count": 3,
                    "failure_count": 0,
                    "partial_count": 0,
                    "capability_artifacts": [],
                    "unsupported_claims": ["Thin local sample only."],
                }
            ],
            "capability_artifacts": [
                {
                    "artifact_kind": "capability_run",
                    "benchmark_id": "coding_static_repair_v1",
                    "surface": "local_coding_capability",
                    "state": "scored",
                    "lane": "decision",
                    "confidence_label": "sampled_reference",
                    "path": "artifacts/capability/coding_static_repair_v1/capability_run.json",
                }
            ],
            "unsupported_claim_summary": ["This summary is not a global intelligence score."],
            "next_recommended_benchmark_action": {"action": "repeat_local_capability_run", "reason": "Repeat local capability checks."},
        }

        errors = validate_capability_summary_artifact(artifact)

        self.assertIn("surfaces[0].confidence_label cannot exceed evidence lane controls", errors)
        self.assertIn("capability_artifacts[0].confidence_label cannot exceed evidence lane controls", errors)

    def test_summary_artifact_pointers_require_explicit_kind(self):
        artifact = {
            "artifact_spec_version": "0.1.0",
            "artifact_kind": "capability_summary",
            "summary_id": "capsum_missing_kind",
            "created_at": "2026-05-08T12:00:00Z",
            "runner": {"name": "infergrade-runner", "version": "0.2.11-dev"},
            "subject": {},
            "surfaces": [],
            "capability_artifacts": [
                {
                    "benchmark_id": "coding_static_repair_v1",
                    "surface": "local_coding_capability",
                    "state": "scored",
                    "lane": "decision",
                    "confidence_label": "thin_local_sample",
                    "path": "artifacts/capability/coding_static_repair_v1/capability_run.json",
                }
            ],
            "unsupported_claim_summary": ["This summary is not a global intelligence score."],
            "next_recommended_benchmark_action": {"action": "repeat_local_capability_run", "reason": "Repeat local capability checks."},
        }

        errors = validate_capability_summary_artifact(artifact)

        self.assertTrue(any("capability_artifacts[0].artifact_kind" in error for error in errors), errors)

    def test_v2_summary_requires_inspectable_score_diagnostics(self):
        artifact = {
            "artifact_spec_version": "0.1.0",
            "artifact_kind": "capability_summary",
            "summary_id": "capsum_bad_v2",
            "created_at": "2026-05-08T12:00:00Z",
            "runner": {"name": "infergrade-runner", "version": "0.3.2"},
            "subject": {},
            "surfaces": [
                {
                    "surface": "local_coding_capability",
                    "state": "scored",
                    "score": 0.7,
                    "score_version": "local_coding_score_v2",
                    "score_method": "weighted_primary_metric_v2",
                    "score_ready": True,
                    "score_coverage": {},
                    "score_components": [],
                    "lane": "reference",
                    "confidence_label": "sampled_reference",
                    "repetition_count": 1,
                    "task_count": 2,
                    "failure_count": 0,
                    "partial_count": 0,
                    "capability_artifacts": [],
                    "unsupported_claims": ["Not a global score."],
                }
            ],
            "capability_artifacts": [],
            "unsupported_claim_summary": ["This summary is not a global intelligence score."],
            "next_recommended_benchmark_action": {"action": "repeat", "reason": "Repeat the run."},
        }

        errors = validate_capability_summary_artifact(artifact)

        self.assertIn("surfaces[0].versioned score requires score_failed_gates as a string array", errors)
        self.assertIn("surfaces[0].versioned score requires score_eligibility", errors)
        self.assertIn("surfaces[0].versioned score requires score_robustness", errors)
        self.assertIn("surfaces[0].versioned score requires score_confidence_basis", errors)


if __name__ == "__main__":
    unittest.main()
