import unittest
from copy import deepcopy

from infergrade.benchmark_catalog import load_capability_catalog
from infergrade.benchmark_readiness import audit_benchmark_readiness


class BenchmarkReadinessTests(unittest.TestCase):
    def test_missing_corpus_evidence_fails_closed_even_when_scoped_facets_exist(self):
        report = audit_benchmark_readiness([], load_capability_catalog())

        self.assertEqual(report["artifact_spec_version"], "0.3.0")
        self.assertFalse(report["scoped_claim_ready"])
        self.assertFalse(report["broad_surface_ready"])
        self.assertEqual(report["status"], "not_ready")
        for surface in report["surfaces"]:
            self.assertTrue(surface["structural_scoped_claim_coverage_ready"])
            self.assertFalse(surface["empirical_distribution_ready"])
            self.assertIn(
                "calibration:insufficient_observation_count",
                surface["scoped_claim_blockers"],
            )

    def test_empirical_headroom_cannot_override_catalog_breadth_gaps(self):
        catalog = load_capability_catalog()
        documents = _calibrated_documents(catalog)

        report = audit_benchmark_readiness(documents, catalog)

        self.assertTrue(report["scoped_claim_ready"])
        self.assertFalse(report["broad_surface_ready"])
        self.assertEqual(report["status"], "scoped_claim_ready")
        assistant = _surface(report, "local_assistant_capability")
        self.assertTrue(assistant["empirical_distribution_ready"])
        self.assertFalse(assistant["structural_broad_surface_coverage_ready"])
        self.assertEqual(assistant["scoped_claim_blockers"], [])
        self.assertIn(
            "catalog:missing_priority_facet:assistant_preference_quality",
            assistant["broad_surface_blockers"],
        )
        self.assertIn("corpus:priority_facet_unobserved:tool_use", assistant["broad_surface_blockers"])
        self.assertIn(
            "corpus:priority_facet_unobserved:stateful_tool_use",
            assistant["broad_surface_blockers"],
        )

    def test_structural_breadth_cannot_override_saturated_empirical_scores(self):
        catalog = _structurally_broad_catalog()
        documents = _calibrated_documents(catalog, saturated=True)

        report = audit_benchmark_readiness(documents, catalog)

        self.assertFalse(report["scoped_claim_ready"])
        self.assertFalse(report["broad_surface_ready"])
        for surface in report["surfaces"]:
            self.assertTrue(surface["structural_broad_surface_coverage_ready"])
            self.assertFalse(surface["empirical_distribution_ready"])
            self.assertTrue(
                any(
                    "ceiling" in item or "headroom" in item
                    for item in surface["scoped_claim_blockers"]
                )
            )

    def test_invalid_catalog_metadata_blocks_readiness_even_with_good_scores(self):
        catalog = _structurally_broad_catalog()
        assistant = next(
            item
            for item in catalog["surface_score_policies"]
            if item["surface_id"] == "local_assistant_capability"
        )
        assistant["representativeness_policy"]["supporting_check_ids"].remove("ifeval")

        report = audit_benchmark_readiness(_calibrated_documents(catalog), catalog)

        self.assertFalse(report["catalog_metadata_valid"])
        self.assertFalse(report["scoped_claim_ready"])
        self.assertTrue(any("omits weighted checks" in item for item in report["catalog_metadata_errors"]))
        self.assertTrue(
            any(
                item.startswith("catalog_metadata:")
                for item in _surface(report, "local_assistant_capability")["scoped_claim_blockers"]
            )
        )

    def test_broad_readiness_requires_both_structural_and_empirical_gates(self):
        catalog = _structurally_broad_catalog()

        report = audit_benchmark_readiness(_calibrated_documents(catalog), catalog)

        self.assertTrue(report["scoped_claim_ready"])
        self.assertTrue(report["broad_surface_ready"])
        self.assertEqual(report["status"], "broad_surface_ready")
        self.assertTrue(all(item["status"] == "broad_surface_ready" for item in report["surfaces"]))
        self.assertTrue(all(item["broad_surface_blockers"] == [] for item in report["surfaces"]))

    def test_composite_calibration_cannot_substitute_for_unobserved_priority_facet(self):
        catalog = _structurally_broad_catalog_with_assistant_diagnostic()

        report = audit_benchmark_readiness(_calibrated_documents(catalog), catalog)

        assistant = _surface(report, "local_assistant_capability")
        self.assertTrue(assistant["structural_broad_surface_coverage_ready"])
        self.assertTrue(assistant["empirical_distribution_ready"])
        self.assertFalse(assistant["empirical_priority_facet_coverage_ready"])
        self.assertFalse(assistant["broad_surface_ready"])
        self.assertIn(
            "corpus:priority_facet_unobserved:multi_turn_state_retention",
            assistant["broad_surface_blockers"],
        )
        facet = _facet(assistant, "multi_turn_state_retention")
        self.assertEqual(facet["status"], "unobserved")
        self.assertEqual(facet["checks"][0]["observation_count"], 0)

    def test_representative_diagnostic_observations_can_clear_priority_facet_gate(self):
        catalog = _structurally_broad_catalog_with_assistant_diagnostic()
        documents = _calibrated_documents(catalog)
        _add_component_observations(
            documents,
            "local_assistant_capability",
            "multiturn_chat_memory_v1",
        )

        report = audit_benchmark_readiness(documents, catalog)

        assistant = _surface(report, "local_assistant_capability")
        self.assertTrue(assistant["empirical_priority_facet_coverage_ready"])
        self.assertTrue(assistant["broad_surface_ready"])
        facet = _facet(assistant, "multi_turn_state_retention")
        self.assertEqual(facet["status"], "ready")
        self.assertEqual(facet["checks"][0]["observation_count"], 20)
        self.assertEqual(facet["checks"][0]["model_family_count"], 5)
        self.assertEqual(
            facet["checks"][0]["independently_replicated_setup_count"],
            10,
        )

    def test_priority_facet_gate_detects_empirical_suite_saturation(self):
        catalog = _structurally_broad_catalog_with_assistant_diagnostic()
        documents = _calibrated_documents(catalog)
        _add_component_observations(
            documents,
            "local_assistant_capability",
            "multiturn_chat_memory_v1",
            score=1.0,
        )

        report = audit_benchmark_readiness(documents, catalog)

        assistant = _surface(report, "local_assistant_capability")
        self.assertTrue(assistant["scoped_claim_ready"])
        self.assertFalse(assistant["broad_surface_ready"])
        self.assertIn(
            "corpus:priority_facet_saturation_risk:multi_turn_state_retention",
            assistant["broad_surface_blockers"],
        )
        check = _facet(assistant, "multi_turn_state_retention")["checks"][0]
        self.assertEqual(check["status"], "saturation_risk")
        self.assertEqual(check["suite_ceiling_fraction"], 1.0)
        self.assertEqual(check["headroom_to_suite_ceiling"], 0.0)

    def test_representative_outcome_slice_saturation_blocks_priority_facet(self):
        catalog = _structurally_broad_catalog_with_stateful_diagnostic()
        documents = _stateful_component_documents(saturated_slice="noop")

        report = audit_benchmark_readiness(documents, catalog)

        assistant = _surface(report, "local_assistant_capability")
        check = _facet(assistant, "stateful_tool_use")["checks"][0]
        self.assertEqual(check["status"], "saturation_risk")
        self.assertFalse(check["ready"])
        self.assertIn("required_slice_saturation_risk:noop", check["blockers"])
        self.assertEqual(check["suite_ceiling_fraction"], 0.0)
        self.assertEqual(
            check["required_slice_metrics"]["noop"]["suite_ceiling_fraction"],
            1.0,
        )
        self.assertEqual(
            check["required_slice_metrics"]["noop"]["headroom_to_suite_ceiling"],
            0.0,
        )

    def test_one_perfect_outcome_observation_is_insufficient_not_saturated(self):
        catalog = _structurally_broad_catalog_with_stateful_diagnostic()

        report = audit_benchmark_readiness(
            _stateful_component_documents(saturated_slice="noop")[:1],
            catalog,
        )

        assistant = _surface(report, "local_assistant_capability")
        check = _facet(assistant, "stateful_tool_use")["checks"][0]
        self.assertEqual(check["status"], "insufficient_evidence")
        self.assertNotIn(
            "corpus:priority_facet_saturation_risk:stateful_tool_use",
            assistant["broad_surface_blockers"],
        )
        self.assertEqual(
            check["required_slice_metrics"]["noop"]["status"],
            "insufficient_evidence",
        )

    def test_representative_non_saturated_outcome_slices_clear_gate(self):
        catalog = _structurally_broad_catalog_with_stateful_diagnostic()

        report = audit_benchmark_readiness(
            _stateful_component_documents(),
            catalog,
        )

        check = _facet(
            _surface(report, "local_assistant_capability"),
            "stateful_tool_use",
        )["checks"][0]
        self.assertEqual(check["status"], "ready")
        self.assertTrue(check["ready"])
        self.assertEqual(
            set(check["required_slice_metrics"]),
            {"success", "blocked", "noop"},
        )
        self.assertTrue(
            all(item["ready"] for item in check["required_slice_metrics"].values())
        )

    def test_underfilled_outcome_slice_cannot_clear_gate(self):
        catalog = _structurally_broad_catalog_with_stateful_diagnostic()
        documents = _stateful_component_documents()
        for document in documents:
            document["summary"]["variant_metrics"]["noop"]["total_count"] = 3

        report = audit_benchmark_readiness(documents, catalog)

        check = _facet(
            _surface(report, "local_assistant_capability"),
            "stateful_tool_use",
        )["checks"][0]
        self.assertEqual(check["status"], "insufficient_evidence")
        self.assertIn("required_slice_unobserved:noop", check["blockers"])
        self.assertEqual(
            check["required_slice_metrics"]["noop"]["observation_count"],
            0,
        )

    def test_self_asserted_evidence_groups_do_not_count_as_independent_repeats(self):
        catalog = _structurally_broad_catalog_with_assistant_diagnostic()
        documents = _calibrated_documents(catalog)
        _add_component_observations(
            documents,
            "local_assistant_capability",
            "multiturn_chat_memory_v1",
        )
        for document in documents:
            if document["capability"]["capability_score_details"]["surface_id"] == (
                "local_assistant_capability"
            ):
                document["evidence_group_provenance"] = "self_asserted"

        report = audit_benchmark_readiness(documents, catalog)

        assistant = _surface(report, "local_assistant_capability")
        check = _facet(assistant, "multi_turn_state_retention")["checks"][0]
        self.assertFalse(assistant["broad_surface_ready"])
        self.assertEqual(check["independently_replicated_setup_count"], 0)
        self.assertIn("insufficient_independently_replicated_setups", check["blockers"])

    def test_standalone_diagnostic_runs_establish_only_their_declared_facet(self):
        catalog = _structurally_broad_catalog_with_assistant_diagnostic()
        documents = _standalone_component_documents(
            "local_assistant_capability",
            "multiturn_chat_memory_v1",
        )

        report = audit_benchmark_readiness(documents, catalog)

        assistant = _surface(report, "local_assistant_capability")
        check = _facet(assistant, "multi_turn_state_retention")["checks"][0]
        self.assertFalse(assistant["empirical_distribution_ready"])
        self.assertFalse(assistant["scoped_claim_ready"])
        self.assertEqual(check["status"], "ready")
        self.assertEqual(check["observation_count"], 20)
        self.assertEqual(check["score_ready_composite_observation_count"], 0)
        self.assertEqual(check["standalone_capability_run_observation_count"], 20)
        self.assertEqual(check["independently_replicated_setup_count"], 10)

    def test_standalone_diagnostic_runs_can_complete_broad_facet_evidence(self):
        catalog = _structurally_broad_catalog_with_assistant_diagnostic()
        documents = _calibrated_documents(catalog)
        documents.extend(
            _standalone_component_documents(
                "local_assistant_capability",
                "multiturn_chat_memory_v1",
            )
        )

        report = audit_benchmark_readiness(documents, catalog)

        assistant = _surface(report, "local_assistant_capability")
        check = _facet(assistant, "multi_turn_state_retention")["checks"][0]
        self.assertTrue(assistant["empirical_distribution_ready"])
        self.assertTrue(assistant["empirical_priority_facet_coverage_ready"])
        self.assertTrue(assistant["broad_surface_ready"])
        self.assertEqual(check["standalone_capability_run_observation_count"], 20)

    def test_duplicate_standalone_and_composite_views_do_not_inflate_facets(self):
        catalog = _structurally_broad_catalog_with_assistant_diagnostic()
        documents = _calibrated_documents(catalog)
        _add_component_observations(
            documents,
            "local_assistant_capability",
            "multiturn_chat_memory_v1",
        )
        documents.extend(
            _standalone_component_documents(
                "local_assistant_capability",
                "multiturn_chat_memory_v1",
            )
        )

        report = audit_benchmark_readiness(documents, catalog)

        assistant = _surface(report, "local_assistant_capability")
        check = _facet(assistant, "multi_turn_state_retention")["checks"][0]
        self.assertTrue(assistant["broad_surface_ready"])
        self.assertEqual(check["observation_count"], 20)
        self.assertEqual(check["score_ready_composite_observation_count"], 20)
        self.assertEqual(check["standalone_capability_run_observation_count"], 0)
        self.assertEqual(check["duplicate_view_count"], 0)
        self.assertEqual(check["unpooled_alternate_observation_count"], 20)
        self.assertEqual(len(check["evidence_cohorts"]), 2)

    def test_standalone_fixture_revisions_never_pool_to_clear_a_gate(self):
        catalog = _structurally_broad_catalog_with_assistant_diagnostic()
        documents = _standalone_component_documents(
            "local_assistant_capability",
            "multiturn_chat_memory_v1",
            fixture_revision=lambda index: "fixture-v%d" % (index % 4),
        )

        report = audit_benchmark_readiness(documents, catalog)

        assistant = _surface(report, "local_assistant_capability")
        check = _facet(assistant, "multi_turn_state_retention")["checks"][0]
        self.assertFalse(check["ready"])
        self.assertEqual(check["observation_count"], 5)
        self.assertEqual(len(check["evidence_cohorts"]), 4)
        self.assertEqual(
            sum(item["observation_count"] for item in check["evidence_cohorts"]),
            20,
        )
        self.assertEqual(check["unpooled_alternate_observation_count"], 15)
        self.assertIn("insufficient_observations", check["blockers"])

    def test_standalone_evidence_cannot_cross_score_surfaces(self):
        catalog = _structurally_broad_catalog_with_assistant_diagnostic()
        documents = _standalone_component_documents(
            "local_coding_capability",
            "multiturn_chat_memory_v1",
        )

        report = audit_benchmark_readiness(documents, catalog)

        assistant = _surface(report, "local_assistant_capability")
        check = _facet(assistant, "multi_turn_state_retention")["checks"][0]
        self.assertFalse(check["ready"])
        self.assertEqual(check["status"], "unobserved")
        self.assertEqual(check["observation_count"], 0)
        self.assertEqual(check["evidence_cohorts"], [])

    def test_out_of_range_standalone_scores_cannot_establish_headroom(self):
        catalog = _structurally_broad_catalog_with_assistant_diagnostic()
        documents = _standalone_component_documents(
            "local_assistant_capability",
            "multiturn_chat_memory_v1",
        )
        for document in documents:
            document["summary"]["score"] = -0.1

        report = audit_benchmark_readiness(documents, catalog)

        assistant = _surface(report, "local_assistant_capability")
        check = _facet(assistant, "multi_turn_state_retention")["checks"][0]
        self.assertFalse(check["ready"])
        self.assertEqual(check["status"], "unobserved")
        self.assertEqual(check["observation_count"], 0)

    def test_surface_filter_keeps_readiness_scope_explicit(self):
        catalog = _structurally_broad_catalog()

        report = audit_benchmark_readiness(
            _calibrated_documents(catalog),
            catalog,
            surface_id="local_reasoning_capability",
        )

        self.assertEqual(len(report["surfaces"]), 1)
        self.assertEqual(report["surfaces"][0]["surface_id"], "local_reasoning_capability")
        self.assertTrue(report["broad_surface_ready"])


def _surface(report, surface_id):
    return next(item for item in report["surfaces"] if item["surface_id"] == surface_id)


def _facet(surface, facet):
    return next(
        item
        for item in surface["empirical_priority_facet_evidence"]["facets"]
        if item["facet"] == facet
    )


def _structurally_broad_catalog():
    catalog = deepcopy(load_capability_catalog())
    checks = {item["check_id"]: item for item in catalog["checks"]}
    for score_policy in catalog["surface_score_policies"]:
        representativeness = score_policy["representativeness_policy"]
        representativeness["priority_facets"] = list(representativeness["scoped_claim_facets"])
        representativeness["planned_check_ids"] = []
        representativeness["minimum_refreshable_priority_facets"] = 0
        headline_ids = [
            check_id
            for check_id in representativeness["supporting_check_ids"]
            if float(checks[check_id].get("primary_score_weight") or 0.0) > 0.0
        ]
        representativeness["supporting_check_ids"] = headline_ids
        for check_id in headline_ids:
            checks[check_id]["discrimination_status"] = "calibrated_headroom"
            checks[check_id].pop("saturation_evidence", None)
    return catalog


def _structurally_broad_catalog_with_assistant_diagnostic():
    catalog = _structurally_broad_catalog()
    checks = {item["check_id"]: item for item in catalog["checks"]}
    assistant = next(
        item
        for item in catalog["surface_score_policies"]
        if item["surface_id"] == "local_assistant_capability"
    )
    representativeness = assistant["representativeness_policy"]
    representativeness["priority_facets"].append("multi_turn_state_retention")
    representativeness["supporting_check_ids"].append("multiturn_chat_memory_v1")
    checks["multiturn_chat_memory_v1"]["discrimination_status"] = "calibrated_headroom"
    checks["multiturn_chat_memory_v1"].pop("saturation_evidence", None)
    return catalog


def _structurally_broad_catalog_with_stateful_diagnostic():
    catalog = _structurally_broad_catalog()
    checks = {item["check_id"]: item for item in catalog["checks"]}
    assistant = next(
        item
        for item in catalog["surface_score_policies"]
        if item["surface_id"] == "local_assistant_capability"
    )
    representativeness = assistant["representativeness_policy"]
    representativeness["priority_facets"].append("stateful_tool_use")
    representativeness["supporting_check_ids"].append(
        "stateful_tool_loop_diagnostic_v1"
    )
    checks["stateful_tool_loop_diagnostic_v1"]["discrimination_status"] = (
        "calibrated_headroom"
    )
    checks["stateful_tool_loop_diagnostic_v1"].pop("saturation_evidence", None)
    return catalog


def _add_component_observations(documents, surface_id, check_id, score=None):
    for index, document in enumerate(documents):
        details = document["capability"]["capability_score_details"]
        if details["surface_id"] != surface_id:
            continue
        document["capability"]["capability_component_reports"].append(
            {
                "benchmark_id": check_id,
                "status": "completed",
                "component_score": score if score is not None else 0.2 + index / 100.0,
            }
        )


def _standalone_component_documents(surface_id, check_id, fixture_revision="fixture-v1"):
    bands = ("1B", "4B", "9B")
    return [
        {
            "artifact_kind": "capability_run",
            "capability_run_id": "%s-standalone-%d" % (surface_id, index),
            "protocol": {
                "task_version": check_id,
                "fixture_revision": (
                    fixture_revision(index)
                    if callable(fixture_revision)
                    else fixture_revision
                ),
            },
            "summary": {"score": 0.2 + index / 100.0, "state": "scored"},
            "tasks": [{} for _ in range(8)],
            "subject": {
                "model": {
                    "model": "models/%s-%d" % (surface_id, index % 10),
                }
            },
            "evidence": {"surface": surface_id},
            "model_family": "family-%d" % (index % 5),
            "parameter_scale": bands[index % len(bands)],
            "quantization_scheme": "q4_k_m",
            "evidence_group_id": "group-%d" % (index // 10),
            "evidence_group_provenance": "trusted_corpus_operator_v1",
        }
        for index in range(20)
    ]


def _stateful_component_documents(saturated_slice=None):
    documents = _standalone_component_documents(
        "local_assistant_capability",
        "stateful_tool_loop_diagnostic_v1",
    )
    base_scores = {
        "success": (0.5, 0.625, 0.75, 0.875),
        "blocked": (0.375, 0.5, 0.625, 0.75),
        "noop": (0.25, 0.375, 0.5, 0.625),
    }
    for index, document in enumerate(documents):
        document["tasks"] = [{} for _ in range(24)]
        document["summary"]["variant_metrics"] = {}
        for slice_id, scores in base_scores.items():
            score = 1.0 if slice_id == saturated_slice else scores[index % len(scores)]
            document["summary"]["variant_metrics"][slice_id] = {
                "correct_count": round(score * 8),
                "total_count": 8,
                "trajectory_success_rate": score,
            }
    return documents


def _calibrated_documents(catalog, saturated=False):
    documents = []
    checks = {item["check_id"]: item for item in catalog["checks"]}
    bands = ("1B", "4B", "9B")
    for score_policy in catalog["surface_score_policies"]:
        score_version = score_policy["score_version"]
        surface_id = score_policy["surface_id"]
        supporting = score_policy["representativeness_policy"]["supporting_check_ids"]
        headline_ids = [
            check_id
            for check_id in supporting
            if float(checks[check_id].get("primary_score_weight") or 0.0) > 0.0
        ]
        score_policy["calibration_policy"]["minimum_current_generation_fraction"] = 0.0
        score_policy["calibration_policy"]["minimum_headroom_challenge_observations"] = 0
        score_policy["calibration_policy"]["minimum_headroom_challenge_model_families"] = 0
        score_policy["calibration_policy"][
            "minimum_headroom_challenge_independently_replicated_setups"
        ] = 0
        for index in range(20):
            score = 1.0 if saturated else 0.2 + index / 100.0
            documents.append(
                {
                    "result_id": "%s-%d" % (surface_id, index),
                    "model_family": "family-%d" % (index % 5),
                    "parameter_scale": bands[index % len(bands)],
                    "model_id": "models/%s-%d" % (surface_id, index % 10),
                    "evidence_group_id": "group-%d" % (index // 10),
                    "evidence_group_provenance": "trusted_corpus_operator_v1",
                    "quantization_scheme": "q4_k_m",
                    "capability": {
                        "capability_score_details": {
                            "score_version": score_version,
                            "surface_id": surface_id,
                            "score_ready": True,
                            "raw_attainment": score,
                        },
                        "capability_component_reports": [
                            {
                                "benchmark_id": check_id,
                                "status": "completed",
                                "component_score": score,
                            }
                            for check_id in headline_ids
                        ],
                    },
                }
            )
    return documents


if __name__ == "__main__":
    unittest.main()
