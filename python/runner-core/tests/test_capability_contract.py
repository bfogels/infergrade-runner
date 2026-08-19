import json
import sys
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.capability_contract import (
    CAPABILITY_STATES,
    CONFIDENCE_LABELS,
    EVIDENCE_LANES,
    capability_run_schema_path,
    capability_run_admission_error_summary,
    capability_summary_schema_path,
    load_capability_run_schema,
    load_capability_summary_schema,
    validate_capability_run_artifact,
    validate_capability_run_schema_artifact,
    validate_capability_summary_artifact,
    validate_current_capability_run_artifact,
)
from infergrade.contracts import load_contract_manifest
from infergrade.selection_identity import (
    SORTED_JSON_STRING_ARRAY_SHA256_V1,
    selection_digest,
)


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
        self.assertEqual(
            schema["properties"]["artifact_spec_version"]["enum"],
            ["0.1.0", "0.1.1"],
        )
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

    def test_longbench_schema_requires_allowlisted_tier_and_receipt_pointer(self):
        artifact = _artifact()
        artifact["artifact_spec_version"] = "0.1.1"
        artifact["protocol"].update(
            {
                "task_version": "longbench_v2_local_reference_v1",
                "selection_digest_algorithm": SORTED_JSON_STRING_ARRAY_SHA256_V1,
                "selection_sha256": selection_digest(
                    ["assistant_fixture_001"], SORTED_JSON_STRING_ARRAY_SHA256_V1
                ),
                "case_count": 1,
                "benchmark_tier": "canary",
            }
        )
        artifact["artifacts"]["supporting_files"] = ["selection_receipt.json"]
        self.assertEqual(validate_capability_run_schema_artifact(artifact), [])

        missing_tier = json.loads(json.dumps(artifact))
        del missing_tier["protocol"]["benchmark_tier"]
        self.assertTrue(
            any("benchmark_tier" in error for error in validate_capability_run_schema_artifact(missing_tier))
        )

        invalid_tier = json.loads(json.dumps(artifact))
        invalid_tier["protocol"]["benchmark_tier"] = "unsupported"
        self.assertTrue(
            any("benchmark_tier" in error for error in validate_capability_run_schema_artifact(invalid_tier))
        )

        missing_receipt = json.loads(json.dumps(artifact))
        missing_receipt["artifacts"]["supporting_files"] = []
        self.assertTrue(validate_capability_run_schema_artifact(missing_receipt))

    def test_longbench_malformed_truthy_artifacts_are_rejected_without_semantic_crashes(self):
        artifact = _artifact()
        artifact["artifact_spec_version"] = "0.1.1"
        artifact["protocol"].update(
            {
                "task_version": "longbench_v2_local_reference_v1",
                "selection_digest_algorithm": SORTED_JSON_STRING_ARRAY_SHA256_V1,
                "selection_sha256": selection_digest(
                    ["assistant_fixture_001"], SORTED_JSON_STRING_ARRAY_SHA256_V1
                ),
                "case_count": 1,
                "benchmark_tier": "canary",
            }
        )

        for malformed_artifacts in (["not-an-object"], "not-an-object", 1, True):
            with self.subTest(artifacts=repr(malformed_artifacts)):
                candidate = json.loads(json.dumps(artifact))
                candidate["artifacts"] = malformed_artifacts
                schema_errors = validate_capability_run_schema_artifact(candidate)
                semantic_errors = validate_capability_run_artifact(candidate)
                current_errors = validate_current_capability_run_artifact(candidate)
                self.assertTrue(schema_errors)
                self.assertTrue(semantic_errors)
                self.assertTrue(current_errors)

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

    def test_capability_schemas_declare_completion_metadata_shapes(self):
        run_schema = load_capability_run_schema()
        run_summary = run_schema["properties"]["summary"]["properties"]
        run_task = run_schema["properties"]["tasks"]["items"]["properties"]
        run_performance = run_schema["$defs"]["task_performance_summary"]["properties"]
        summary_schema = load_capability_summary_schema()
        summary_performance = summary_schema["$defs"]["task_performance_summary"]["properties"]

        self.assertEqual(run_summary["token_budget_exhaustion_count"]["type"], ["integer", "null"])
        self.assertEqual(run_task["natural_stop"]["type"], ["boolean", "null"])
        self.assertEqual(run_task["output_token_budget"]["type"], ["integer", "null"])
        self.assertEqual(run_performance["natural_stop_rate"]["type"], ["number", "null"])
        self.assertEqual(run_performance["natural_stop_reported_count"]["type"], ["integer", "null"])
        self.assertEqual(
            run_performance["token_budget_exhaustion_reported_count"]["type"],
            ["integer", "null"],
        )
        self.assertEqual(run_performance["stop_type_counts"]["type"], "object")
        self.assertEqual(summary_performance["token_budget_exhaustion_rate"]["type"], ["number", "null"])

    def test_valid_capability_run_artifact_passes_semantic_validation(self):
        self.assertEqual(validate_capability_run_artifact(_artifact()), [])

    def test_legacy_capability_run_artifact_remains_readable_without_selection_provenance(self):
        artifact = _artifact()

        self.assertEqual(artifact["artifact_spec_version"], "0.1.0")
        self.assertEqual(validate_capability_run_artifact(artifact), [])
        self.assertIn(
            "artifact_spec_version must be current-admissible: 0.1.1",
            validate_current_capability_run_artifact(artifact),
        )

    def test_v011_capability_run_requires_valid_selection_provenance(self):
        artifact = _artifact()
        artifact["artifact_spec_version"] = "0.1.1"
        artifact["protocol"].update(
            {
                "selection_digest_algorithm": SORTED_JSON_STRING_ARRAY_SHA256_V1,
                "selection_sha256": selection_digest(
                    ["assistant_fixture_001"], SORTED_JSON_STRING_ARRAY_SHA256_V1
                ),
                "case_count": 1,
            }
        )

        self.assertEqual(validate_capability_run_artifact(artifact), [])
        self.assertEqual(validate_capability_run_schema_artifact(artifact), [])
        self.assertEqual(validate_current_capability_run_artifact(artifact), [])

        missing = dict(artifact)
        missing["protocol"] = dict(artifact["protocol"])
        del missing["protocol"]["selection_sha256"]
        errors = validate_capability_run_artifact(missing)
        self.assertIn("protocol.selection_sha256 is required", errors)

    def test_v011_selection_provenance_rejects_algorithm_digest_and_count_drift(self):
        artifact = _artifact()
        artifact["artifact_spec_version"] = "0.1.1"
        artifact["protocol"].update(
            {
                "selection_digest_algorithm": "unsupported_v1",
                "selection_sha256": "A" * 64,
                "case_count": 2,
            }
        )

        errors = validate_capability_run_artifact(artifact)

        self.assertIn(
            "protocol.selection_digest_algorithm must be a supported selection digest algorithm",
            errors,
        )
        self.assertIn(
            "protocol.selection_sha256 must be a lowercase SHA-256 hex digest",
            errors,
        )
        self.assertIn("protocol.case_count must equal len(tasks)", errors)

    def test_capability_run_rejects_unknown_artifact_spec_version(self):
        artifact = _artifact()
        artifact["artifact_spec_version"] = "0.2.0"

        errors = validate_capability_run_artifact(artifact)

        self.assertIn(
            "artifact_spec_version must be one of: 0.1.0, 0.1.1",
            errors,
        )

    def test_v011_rejects_forged_digest_and_duplicate_or_empty_task_ids(self):
        artifact = _artifact()
        artifact["artifact_spec_version"] = "0.1.1"
        artifact["protocol"].update(
            {
                "selection_digest_algorithm": SORTED_JSON_STRING_ARRAY_SHA256_V1,
                "selection_sha256": "0" * 64,
                "case_count": 1,
            }
        )
        self.assertIn(
            "protocol.selection_sha256 must match task IDs",
            validate_capability_run_artifact(artifact),
        )

        duplicate = dict(artifact)
        duplicate["protocol"] = dict(artifact["protocol"])
        duplicate["tasks"] = [dict(artifact["tasks"][0]), dict(artifact["tasks"][0])]
        duplicate["protocol"]["case_count"] = 2
        errors = validate_capability_run_artifact(duplicate)
        self.assertIn("tasks[1].task_id must be unique", errors)

        empty = dict(artifact)
        empty["protocol"] = dict(artifact["protocol"])
        empty["tasks"] = [dict(artifact["tasks"][0])]
        empty["tasks"][0]["task_id"] = "  "
        errors = validate_capability_run_artifact(empty)
        self.assertIn("tasks[0].task_id must be a non-empty string", errors)

    def test_legacy_optional_selection_fields_use_schema_shapes(self):
        artifact = _artifact()
        artifact["protocol"].update(
            {
                "selection_digest_algorithm": "unsupported_v1",
                "selection_sha256": "A" * 64,
                "case_count": -1,
            }
        )

        errors = validate_capability_run_artifact(artifact)

        self.assertIn(
            "protocol.selection_digest_algorithm must be a supported selection digest algorithm",
            errors,
        )
        self.assertIn(
            "protocol.selection_sha256 must be a lowercase SHA-256 hex digest",
            errors,
        )
        self.assertIn("protocol.case_count must be an integer >= 0", errors)

    def test_selection_digest_algorithm_rejects_unhashable_json_values_without_crashing(self):
        for artifact_spec_version in ("0.1.0", "0.1.1"):
            for malformed in ([], {}):
                with self.subTest(
                    artifact_spec_version=artifact_spec_version,
                    malformed=malformed,
                ):
                    artifact = _artifact()
                    artifact["artifact_spec_version"] = artifact_spec_version
                    artifact["protocol"]["selection_digest_algorithm"] = malformed
                    if artifact_spec_version == "0.1.1":
                        artifact["protocol"].update(
                            {
                                "selection_sha256": "0" * 64,
                                "case_count": 1,
                            }
                        )

                    errors = validate_capability_run_artifact(artifact)

                    self.assertIn(
                        "protocol.selection_digest_algorithm must be a supported selection digest algorithm",
                        errors,
                    )

    def test_admission_error_summary_bounds_count_and_message_length(self):
        summary = capability_run_admission_error_summary(
            ["x" * 1000 for _ in range(25)]
        )

        self.assertEqual(len(summary["admission_errors"]), 20)
        self.assertTrue(
            all(len(error) == 256 for error in summary["admission_errors"])
        )
        self.assertEqual(summary["admission_error_count"], 25)
        self.assertTrue(summary["admission_errors_truncated"])

    def test_current_admission_rejects_schema_only_structural_mutations(self):
        artifact = _artifact()
        artifact["artifact_spec_version"] = "0.1.1"
        artifact["protocol"].update(
            {
                "selection_digest_algorithm": SORTED_JSON_STRING_ARRAY_SHA256_V1,
                "selection_sha256": selection_digest(
                    ["assistant_fixture_001"],
                    SORTED_JSON_STRING_ARRAY_SHA256_V1,
                ),
                "case_count": 1,
            }
        )
        mutations = {
            "missing_runner": lambda item: item.pop("runner"),
            "missing_artifacts": lambda item: item.pop("artifacts"),
            "missing_output_artifact": lambda item: item["tasks"][0].pop(
                "output_artifact"
            ),
            "malformed_subject_runtime": lambda item: item["subject"].update(
                {"runtime": []}
            ),
            "malformed_task_performance": lambda item: item["summary"].update(
                {"task_performance": {"attempted_task_count": []}}
            ),
        }

        for name, mutate in mutations.items():
            with self.subTest(name=name):
                candidate = json.loads(json.dumps(artifact))
                mutate(candidate)

                schema_errors = validate_capability_run_schema_artifact(candidate)

                self.assertTrue(schema_errors)
                self.assertTrue(validate_current_capability_run_artifact(candidate))

    def test_v011_schema_conditionally_requires_selection_provenance(self):
        schema = load_capability_run_schema()
        conditional = next(
            item
            for item in schema["allOf"]
            if item.get("if", {}).get("properties", {})
            .get("artifact_spec_version", {})
            .get("const")
            == "0.1.1"
        )
        self.assertEqual(
            conditional["then"]["properties"]["protocol"]["required"],
            ["selection_digest_algorithm", "selection_sha256", "case_count"],
        )

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
