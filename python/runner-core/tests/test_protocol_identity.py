import copy
import json
import tempfile
import unittest
from pathlib import Path

from infergrade.protocol_identity import (
    BENCHMARK_PROTOCOL_IDENTITY_VERSION,
    validate_capability_protocol_identity,
    verify_protocol_identity_path,
)
from infergrade.utils import stable_hash


def _identity(benchmark_id):
    payload = {
        "identity_version": BENCHMARK_PROTOCOL_IDENTITY_VERSION,
        "benchmark_id": benchmark_id,
        "registry_version": "2026-07-capability-protocol-3.1",
        "input_identity_sha256": "1" * 64,
        "scoring_identity_sha256": "2" * 64,
        "generation_identity_sha256": "3" * 64,
    }
    payload["fingerprint_sha256"] = stable_hash(payload, length=64)
    return payload


def _capability(*benchmark_ids):
    identities = {benchmark_id: _identity(benchmark_id) for benchmark_id in benchmark_ids}
    fingerprints = {
        benchmark_id: identities[benchmark_id]["fingerprint_sha256"] for benchmark_id in sorted(benchmark_ids)
    }
    aggregate = {
        "identity_version": BENCHMARK_PROTOCOL_IDENTITY_VERSION,
        "status": "complete",
        "check_fingerprints": fingerprints,
        "missing_benchmark_ids": [],
    }
    aggregate["fingerprint_sha256"] = stable_hash(aggregate, length=64)
    return {
        "benchmark_coverage": {
            "planned_benchmark_ids": list(benchmark_ids),
            "scored_benchmark_ids": list(benchmark_ids),
            "coverage_state": "complete",
        },
        "benchmark_results": {
            benchmark_id: {
                "status": "completed",
                "primary_metric": {"name": "score", "value": 0.5},
                "protocol_identity": identity,
            }
            for benchmark_id, identity in identities.items()
        },
        "benchmark_protocol_identity": aggregate,
    }


class ProtocolIdentityTests(unittest.TestCase):
    def test_validates_exact_component_and_aggregate_identity(self):
        report = validate_capability_protocol_identity(_capability("ifeval", "assistant_compositional_instruction_v2"))

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["verified_check_count"], 2)
        self.assertEqual(report["errors"], [])

    def test_rejects_missing_scored_check_identity(self):
        capability = _capability("ifeval")
        del capability["benchmark_results"]["ifeval"]["protocol_identity"]

        report = validate_capability_protocol_identity(capability)

        self.assertEqual(report["status"], "fail")
        self.assertIn("ifeval: scored benchmark protocol_identity is missing", report["errors"])

    def test_rejects_tampered_check_identity_even_when_aggregate_is_unchanged(self):
        capability = _capability("ifeval")
        capability["benchmark_results"]["ifeval"]["protocol_identity"]["registry_version"] = "tampered"

        report = validate_capability_protocol_identity(capability)

        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("does not match the protocol identity payload" in error for error in report["errors"]))

    def test_rejects_aggregate_that_omits_a_scored_check(self):
        capability = _capability("ifeval", "assistant_compositional_instruction_v2")
        del capability["benchmark_protocol_identity"]["check_fingerprints"]["ifeval"]

        report = validate_capability_protocol_identity(capability)

        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("check_fingerprints do not exactly match" in error for error in report["errors"]))

    def test_release_gate_rejects_partial_benchmark_coverage(self):
        capability = _capability("ifeval")
        capability["benchmark_coverage"]["planned_benchmark_ids"].append("assistant_compositional_instruction_v2")
        capability["benchmark_coverage"]["coverage_state"] = "partial"

        report = validate_capability_protocol_identity(capability)

        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("planned and scored benchmark ids differ" in error for error in report["errors"]))

    def test_verifies_every_capability_result_listed_by_bundle_manifest(self):
        with tempfile.TemporaryDirectory() as tempdir:
            bundle = Path(tempdir)
            (bundle / "results").mkdir()
            (bundle / "manifest.json").write_text(
                json.dumps({"files": {"results": ["results/chat.json", "results/context.json"]}}),
                encoding="utf-8",
            )
            for name in ("chat", "context"):
                (bundle / "results" / (name + ".json")).write_text(
                    json.dumps({"result_id": name, "capability": _capability("ifeval")}),
                    encoding="utf-8",
                )

            report = verify_protocol_identity_path(bundle)

        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["capability_result_count"], 2)
        self.assertEqual(report["verified_check_count"], 2)

    def test_fails_when_result_has_no_capability_evidence(self):
        with tempfile.TemporaryDirectory() as tempdir:
            result_path = Path(tempdir) / "result.json"
            result_path.write_text(json.dumps({"result_id": "speed-only"}), encoding="utf-8")

            report = verify_protocol_identity_path(result_path)

        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["capability_result_count"], 0)
        self.assertEqual(report["errors"], ["result document is missing capability evidence"])

    def test_rejects_different_protocols_across_bundle_results(self):
        with tempfile.TemporaryDirectory() as tempdir:
            bundle = Path(tempdir)
            (bundle / "results").mkdir()
            (bundle / "manifest.json").write_text(
                json.dumps({"files": {"results": ["results/chat.json", "results/context.json"]}}),
                encoding="utf-8",
            )
            first = _capability("ifeval")
            second = _capability("assistant_compositional_instruction_v2")
            (bundle / "results" / "chat.json").write_text(
                json.dumps({"result_id": "chat", "capability": first}), encoding="utf-8"
            )
            (bundle / "results" / "context.json").write_text(
                json.dumps({"result_id": "context", "capability": second}), encoding="utf-8"
            )

            report = verify_protocol_identity_path(bundle)

        self.assertEqual(report["status"], "fail")
        self.assertIn("capability protocol identity differs across bundle result documents", report["errors"])


if __name__ == "__main__":
    unittest.main()
