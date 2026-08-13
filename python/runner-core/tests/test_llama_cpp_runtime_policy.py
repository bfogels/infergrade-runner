import copy
import contextlib
import datetime as dt
import importlib.util
import io
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

    def test_short_commit_pin_is_rejected(self):
        policy = copy.deepcopy(self.policy)
        policy["pins"][0]["value"] = "14d3ba45f"
        failures = self.module.validate_policy(policy, root=ROOT)
        self.assertTrue(any("full 40-character" in item for item in failures))

    def test_reviewed_archive_pin_requires_its_receipt(self):
        policy = copy.deepcopy(self.policy)
        windows_pin = next(item for item in policy["pins"] if item["id"] == "windows_x64_cuda_preview")
        windows_pin["review_receipt"] = "runtime/reviews/missing.json"
        failures = self.module.validate_policy(policy, root=ROOT)
        self.assertTrue(any("review receipt is missing" in item for item in failures))

    def test_windows_candidate_receipt_matches_the_reviewed_pin(self):
        windows_pin = next(item for item in self.policy["pins"] if item["id"] == "windows_x64_cuda_preview")
        receipt = json.loads((ROOT / windows_pin["review_receipt"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt["upstream"]["release"], windows_pin["value"])
        self.assertEqual(receipt["hardware_validation"]["status"], "not_run")
        self.assertEqual(receipt["license_review"]["status"], "pending")

    def test_release_default_and_candidate_containers_are_separate_lanes(self):
        pins = {item["id"]: item for item in self.policy["pins"]}
        stable = pins["container_linux_cpu_stable"]
        candidate = pins["container_linux_cpu_candidate"]
        self.assertEqual(stable["channel"], "infergrade_stable")
        self.assertEqual(candidate["channel"], "reviewed_candidate")
        self.assertEqual(stable["locations"][0]["path"], "containers/llama-cpp/Dockerfile")
        self.assertEqual(candidate["locations"][0]["path"], "containers/llama-cpp-candidate/Dockerfile")

    def test_new_upstream_release_is_advisory_candidate(self):
        latest = {
            "tag_name": "b10100",
            "published_at": "2026-07-15T05:29:11Z",
            "html_url": "https://github.com/ggml-org/llama.cpp/releases/tag/b10100",
        }
        report = self.module.build_report(
            self.policy,
            latest_release=latest,
            now=dt.datetime(2026, 7, 14, 12, tzinfo=dt.timezone.utc),
        )
        self.assertTrue(report["candidate_available"])
        self.assertFalse(report["stable_promotion_automatic"])
        self.assertFalse(report["runner_release_required"])
        self.assertTrue(any(pin["review_due"] for pin in report["pins"] if pin["channel"] == "infergrade_stable"))

    def test_tracked_reviewed_candidate_is_not_reported_as_new(self):
        latest = {
            "tag_name": "b10069",
            "published_at": "2026-07-20T00:00:00Z",
            "html_url": "https://github.com/ggml-org/llama.cpp/releases/tag/b10069",
        }
        report = self.module.build_report(self.policy, latest_release=latest)
        self.assertFalse(report["candidate_available"])

    def test_stable_pin_age_triggers_review_without_forcing_latest(self):
        report = self.module.build_report(
            self.policy,
            now=dt.datetime(2026, 9, 1, 12, tzinfo=dt.timezone.utc),
        )
        self.assertTrue(any(pin["review_due"] for pin in report["pins"] if pin["channel"] == "infergrade_stable"))

    def test_default_cli_succeeds_when_upstream_is_newer(self):
        latest = {
            "tag_name": "b10100",
            "published_at": "2026-07-15T05:29:11Z",
            "html_url": "https://github.com/ggml-org/llama.cpp/releases/tag/b10100",
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

    def archive_receipt(self, platform="macos-arm64", status="not_run", tag="b10100"):
        suffix = {
            "macos-arm64": "macos-arm64.tar.gz",
            "ubuntu-x64": "ubuntu-x64.tar.gz",
            "windows-cpu-x64": "win-cpu-x64.zip",
        }[platform]
        return {
            "receipt_version": 1,
            "candidate_only": True,
            "upstream": {"repository": "ggml-org/llama.cpp", "release": tag},
            "platform": platform,
            "artifact": {
                "name": f"llama-{tag}-bin-{suffix}",
                "size_bytes": 123,
                "github_asset_sha256": "a" * 64,
                "downloaded_sha256": "a" * 64,
            },
            "version_smoke": {"status": status},
        }

    def model_canary_receipt(self, tag="b10100"):
        return {
            "receipt_version": 1,
            "candidate_only": True,
            "canary_id": "legacy_llama_tiny_generation_v1",
            "status": "passed",
            "proof_scope": "legacy_llama_model_load_and_generation",
            "model_compatibility": "legacy_control_only",
            "claim_boundary": "Does not prove recent architectures.",
            "runtime": {
                "release": tag,
                "platform": "ubuntu-x64",
                "archive_sha256": "a" * 64,
                "version_smoke": "passed",
            },
            "model": {
                "repository": "ggml-org/tiny-llamas",
                "revision": "b" * 40,
                "expected_sha256": "b" * 64,
                "downloaded_sha256": "b" * 64,
            },
            "execution": {
                "status": "passed",
                "generated_output_chars": 24,
                "generated_output_sha256": "c" * 64,
            },
        }

    def recent_model_canary_receipt(self, tag="b10100"):
        receipt = self.model_canary_receipt(tag=tag)
        receipt.update(
            {
                "canary_id": "minicpm5_tokenizer",
                "proof_scope": "recent_architecture_model_load_and_generation",
                "model_compatibility": "exact_model_artifact_only",
            }
        )
        receipt["model"].update(
            {
                "repository": "openbmb/MiniCPM5-1B-GGUF",
                "revision": "87007042419d30c1d8f38ef065424ee33870831e",
            }
        )
        return receipt

    def materialization_receipt(self, platform="macos-arm64", tag="b10100"):
        system, machine, build_character = {
            "macos-arm64": ("macos", "aarch64", "c"),
            "ubuntu-x64": ("linux", "x86_64", "d"),
        }[platform]
        return {
            "receipt_version": "infergrade_runtime_candidate_materialization_v1",
            "candidate_only": True,
            "claim_boundary": "Candidate package only.",
            "runtime": {
                "runtime_id": f"llama-cpp-{tag}-{platform}-qualification",
                "channel": "upstream_release",
                "source": "managed_download",
                "upstream": {
                    "project": "ggml-org/llama.cpp",
                    "tag": tag,
                    "release_url": f"https://github.com/ggml-org/llama.cpp/releases/tag/{tag}",
                },
                "selected_at_platform": {"system": system, "machine": machine},
                "runtime_build_id": build_character * 64,
                "source_assertion_id": "e" * 64,
                "content_scope": "managed_package",
                "file_count": 61,
            },
            "archive": {
                "url": f"https://github.com/ggml-org/llama.cpp/releases/download/{tag}/runtime.tar.gz",
                "sha256": "a" * 64,
                "checksum_verified": True,
                "independent_signature_verified": False,
            },
            "catalog_assertion": None,
            "version_smoke": {"command": "--version", "output": "version 10375"},
        }

    def benchmark_qualification(self, tag="b10100"):
        return {
            "qualification_version": "infergrade_runtime_qualification_v1",
            "status": "valid_comparable",
            "claim_scope": "exact_artifact_on_recorded_hardware_only",
            "runtime": {
                "upstream": {"tag": tag},
                "runtime_build_id": "c" * 64,
                "catalog_activation_status": "not_staged",
                "signed_catalog_assertion_state": "absent",
            },
            "hardware": {
                "hardware_class": "apple_silicon",
                "accelerator_model": "Apple M1 Pro",
            },
            "assertions": [
                {
                    "result_id": "qb_exact_interactive_chat_v1",
                    "model_id": "openbmb/MiniCPM5-1B-GGUF",
                    "model_revision": "f" * 40,
                    "model_artifact_sha256": "1" * 64,
                    "quantization_label": "Q4_K_M",
                    "bundle_valid": True,
                    "comparison_grade": "comparable",
                    "receipt_prelaunch": "passed",
                    "receipt_postrun": "passed",
                }
            ],
            "publication": {"status": "local_only", "published": False},
        }

    def test_candidate_archive_receipts_remain_distinct_from_model_compatibility(self):
        latest = {
            "tag_name": "b10100",
            "published_at": "2026-07-15T05:29:11Z",
            "html_url": "https://github.com/ggml-org/llama.cpp/releases/tag/b10100",
        }
        receipts = [
            self.archive_receipt("macos-arm64"),
            self.archive_receipt("ubuntu-x64", status="passed"),
            self.archive_receipt("windows-cpu-x64"),
        ]
        report = self.module.build_report(
            self.policy,
            latest_release=latest,
            archive_receipts=receipts,
        )
        coverage = report["candidate_archive_coverage"]
        self.assertTrue(coverage["all_expected_archives_verified"])
        self.assertEqual(coverage["native_version_smoke_platforms"], ["ubuntu-x64"])
        self.assertFalse(coverage["model_compatibility_verified"])
        self.assertEqual(
            {item["proof_scope"] for item in report["candidate_archive_receipts"]},
            {"archive_only", "native_version_smoke"},
        )
        markdown = self.module.render_markdown(report)
        self.assertIn("It does not prove GGUF or benchmark compatibility", markdown)

    def test_legacy_model_canary_is_visible_without_proving_recent_architectures(self):
        latest = {"tag_name": "b10100"}
        report = self.module.build_report(
            self.policy,
            latest_release=latest,
            archive_receipts=[self.archive_receipt("ubuntu-x64", status="passed")],
            model_canary_receipts=[self.model_canary_receipt()],
        )
        coverage = report["candidate_archive_coverage"]
        self.assertTrue(coverage["legacy_control_model_canary_passed"])
        self.assertFalse(coverage["recent_architecture_model_canary_passed"])
        self.assertFalse(coverage["model_compatibility_verified"])
        markdown = self.module.render_markdown(report)
        self.assertIn("legacy control catches broad load/generation regressions", markdown)
        self.assertIn("Recent architectures and benchmark protocols remain separate gates", markdown)

        wrong_release = self.model_canary_receipt(tag="b10099")
        with self.assertRaisesRegex(ValueError, "runtime release does not match"):
            self.module.build_report(
                self.policy,
                latest_release=latest,
                archive_receipts=[self.archive_receipt("ubuntu-x64", status="passed")],
                model_canary_receipts=[wrong_release],
            )

    def test_exact_recent_canary_is_visible_without_claiming_broad_compatibility(self):
        report = self.module.build_report(
            self.policy,
            latest_release={"tag_name": "b10100"},
            archive_receipts=[self.archive_receipt("ubuntu-x64", status="passed")],
            model_canary_receipts=[
                self.model_canary_receipt(),
                self.recent_model_canary_receipt(),
            ],
        )
        coverage = report["candidate_archive_coverage"]
        self.assertTrue(coverage["legacy_control_model_canary_passed"])
        self.assertTrue(coverage["recent_architecture_model_canary_passed"])
        self.assertFalse(coverage["model_compatibility_verified"])

    def test_evidence_ladder_keeps_package_model_benchmark_and_policy_distinct(self):
        archives = [
            self.archive_receipt("macos-arm64", status="passed"),
            self.archive_receipt("ubuntu-x64", status="passed"),
            self.archive_receipt("windows-cpu-x64", status="passed"),
        ]
        report = self.module.build_report(
            self.policy,
            latest_release={"tag_name": "b10100"},
            archive_receipts=archives,
            materialization_receipts=[
                self.materialization_receipt("macos-arm64"),
                self.materialization_receipt("ubuntu-x64"),
            ],
            model_canary_receipts=[self.recent_model_canary_receipt()],
            benchmark_qualifications=[self.benchmark_qualification()],
        )

        self.assertEqual(report["report_version"], 2)
        statuses = {
            item["id"]: item["status"]
            for item in report["candidate_evidence_ladder"]["rungs"]
        }
        for gate in (
            "official_release_metadata",
            "archive_identity",
            "native_version_smoke",
            "immutable_package_materialization",
            "exact_recent_model_canary",
            "exact_benchmark_qualification",
        ):
            self.assertEqual(statuses[gate], "passed")
        self.assertEqual(statuses["signed_catalog_assertion"], "not_run")
        self.assertEqual(statuses["support_promotion"], "not_run")
        self.assertEqual(
            report["candidate_evidence_ladder"]["next_required_gate"],
            "signed_catalog_assertion",
        )
        self.assertFalse(report["candidate_evidence_ladder"]["automatic_promotion"])
        self.assertEqual(
            report["candidate_archive_coverage"]["immutable_materialization_platforms"],
            ["macos-arm64", "ubuntu-x64"],
        )
        self.assertEqual(
            report["candidate_benchmark_qualifications"][0]["claim_scope"],
            "exact_artifact_on_recorded_hardware_only",
        )
        markdown = self.module.render_markdown(report)
        self.assertIn("Candidate evidence ladder", markdown)
        self.assertIn("Next gate: `signed_catalog_assertion`", markdown)
        self.assertIn("Catalog signing and support promotion remain separate", markdown)

    def test_materialization_receipt_rejects_mismatch_catalog_claim_or_private_path(self):
        latest = {"tag_name": "b10100"}
        archive = self.archive_receipt("macos-arm64", status="passed")

        mismatch = self.materialization_receipt()
        mismatch["archive"]["sha256"] = "2" * 64
        with self.assertRaisesRegex(ValueError, "does not match its archive"):
            self.module.build_report(
                self.policy,
                latest_release=latest,
                archive_receipts=[archive],
                materialization_receipts=[mismatch],
            )

        catalog_claim = self.materialization_receipt()
        catalog_claim["catalog_assertion"] = {"target": "runtime"}
        with self.assertRaisesRegex(ValueError, "cannot assert signed catalog"):
            self.module.build_report(
                self.policy,
                latest_release=latest,
                archive_receipts=[archive],
                materialization_receipts=[catalog_claim],
            )

        private_path = self.materialization_receipt()
        private_path["runtime"]["binaries"] = {"cli": "/tmp/llama-cli"}
        with self.assertRaisesRegex(ValueError, "private path fields"):
            self.module.build_report(
                self.policy,
                latest_release=latest,
                archive_receipts=[archive],
                materialization_receipts=[private_path],
            )

    def test_benchmark_qualification_must_match_materialized_build(self):
        qualification = self.benchmark_qualification()
        qualification["runtime"]["runtime_build_id"] = "9" * 64
        with self.assertRaisesRegex(ValueError, "was not materialized"):
            self.module.build_report(
                self.policy,
                latest_release={"tag_name": "b10100"},
                archive_receipts=[self.archive_receipt("macos-arm64", status="passed")],
                materialization_receipts=[self.materialization_receipt()],
                benchmark_qualifications=[qualification],
            )

    def test_cli_composes_archive_materialization_and_qualification_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            paths = {
                "latest": root / "latest.json",
                "archive": root / "archive.json",
                "materialization": root / "materialization.json",
                "qualification": root / "qualification.json",
                "report": root / "report.json",
                "markdown": root / "report.md",
            }
            paths["latest"].write_text(
                json.dumps({"tag_name": "b10100"}), encoding="utf-8"
            )
            paths["archive"].write_text(
                json.dumps(self.archive_receipt("macos-arm64", status="passed")),
                encoding="utf-8",
            )
            paths["materialization"].write_text(
                json.dumps(self.materialization_receipt()), encoding="utf-8"
            )
            paths["qualification"].write_text(
                json.dumps(self.benchmark_qualification()), encoding="utf-8"
            )
            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = self.module.main(
                    [
                        "--latest-release-json",
                        str(paths["latest"]),
                        "--archive-receipt",
                        str(paths["archive"]),
                        "--materialization-receipt",
                        str(paths["materialization"]),
                        "--benchmark-qualification",
                        str(paths["qualification"]),
                        "--report-json",
                        str(paths["report"]),
                        "--report-markdown",
                        str(paths["markdown"]),
                    ]
                )

            report = json.loads(paths["report"].read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(report["candidate_runtime_materializations"]), 1)
            self.assertEqual(len(report["candidate_benchmark_qualifications"]), 1)
            self.assertEqual(
                report["candidate_evidence_ladder"]["next_required_gate"],
                "archive_identity",
            )
            self.assertIn(
                "Exact benchmark qualifications",
                paths["markdown"].read_text(encoding="utf-8"),
            )

    def test_candidate_archive_receipts_reject_release_or_digest_mismatch(self):
        latest = {"tag_name": "b10100"}
        wrong_release = self.archive_receipt(tag="b10099")
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.module.build_report(
                self.policy,
                latest_release=latest,
                archive_receipts=[wrong_release],
            )
        wrong_digest = self.archive_receipt()
        wrong_digest["artifact"]["downloaded_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "downloaded digest"):
            self.module.build_report(
                self.policy,
                latest_release=latest,
                archive_receipts=[wrong_digest],
            )


if __name__ == "__main__":
    unittest.main()
