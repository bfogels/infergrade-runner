import unittest
from copy import deepcopy

from infergrade.benchmark_catalog import load_capability_catalog
from infergrade.benchmark_readiness import audit_benchmark_readiness


class BenchmarkReadinessTests(unittest.TestCase):
    def test_missing_corpus_evidence_fails_closed_even_when_scoped_facets_exist(self):
        report = audit_benchmark_readiness([], load_capability_catalog())

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
            "catalog:missing_priority_facet:tool_use",
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
