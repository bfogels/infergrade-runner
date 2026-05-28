import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.cuda import (
    WINDOWS_CUDA_PROOF_STEPS,
    WINDOWS_CUDA_RUNTIME_DELIVERY_GATE,
    minimum_driver_for_cuda,
    normalize_platform_snapshot,
    parse_nvidia_smi_cuda_version,
    parse_nvidia_smi_csv,
    version_at_least,
    windows_cuda_preflight,
)
from infergrade.runtimes import windows_cuda_candidate_manifest


class WindowsCudaPreflightTests(unittest.TestCase):
    def test_parse_nvidia_smi_csv_captures_gpu_driver_vram_and_compute_capability(self):
        rows = parse_nvidia_smi_csv("NVIDIA RTX 4090, 555.85, 24564, 8.9\n")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "NVIDIA RTX 4090")
        self.assertEqual(rows[0]["driver_version"], "555.85")
        self.assertEqual(rows[0]["vram_bytes"], 24564 * 1024 * 1024)
        self.assertEqual(rows[0]["compute_capability"], "8.9")

    def test_parse_nvidia_smi_csv_preserves_cuda_version_when_reported(self):
        rows = parse_nvidia_smi_csv("NVIDIA RTX 4090, 555.85, 24564, 8.9, 12.5\n")

        self.assertEqual(rows[0]["cuda_version"], "12.5")

    def test_parse_nvidia_smi_cuda_version_reads_plain_output(self):
        version = parse_nvidia_smi_cuda_version("| NVIDIA-SMI 555.85       Driver Version: 555.85       CUDA Version: 12.5 |")

        self.assertEqual(version, "12.5")

    def test_version_comparison_pads_segments(self):
        self.assertTrue(version_at_least("525.0", "525.0.0"))
        self.assertTrue(version_at_least("555.85", "525.0"))
        self.assertFalse(version_at_least("449.90", "450.0"))

    def test_minimum_driver_defaults_to_cuda_12_floor(self):
        self.assertEqual(minimum_driver_for_cuda(None), "525.0")
        self.assertEqual(minimum_driver_for_cuda("13.0"), "580.0")

    def test_normalize_platform_snapshot_accepts_windows_aliases(self):
        self.assertEqual(normalize_platform_snapshot({"system": "Windows", "arch": "AMD64"})["system"], "windows")
        self.assertEqual(normalize_platform_snapshot({"system": "Windows_NT", "arch": "x86_64"})["system"], "windows")
        self.assertEqual(normalize_platform_snapshot({"system": "win32", "arch": "AMD64"})["arch"], "amd64")

    def test_windows_cuda_preflight_blocks_until_full_loop_is_proven(self):
        result = windows_cuda_preflight(
            nvidia_smi_output="NVIDIA RTX 4090, 555.85, 24564, 8.9, 12.5\n",
            platform_snapshot={"system": "Windows", "arch": "AMD64", "version": "11"},
            which=lambda _name: None,
        )

        selector = result["selector"]
        self.assertTrue(result["hardware_blocked"])
        self.assertEqual(selector["platform"]["system"], "windows")
        self.assertEqual(selector["platform"]["arch"], "amd64")
        self.assertEqual(selector["accelerator"]["vendor"], "nvidia")
        self.assertEqual(selector["accelerator"]["compute_capability"], "8.9")
        self.assertEqual(selector["driver"]["minimum_required"], "525.0")
        self.assertEqual(selector["delivery"]["mode"], "user_selected")
        self.assertEqual(selector["delivery"]["source"], "run_config")
        self.assertEqual(selector["delivery"]["selected_by"], "run_config")
        self.assertEqual(
            selector["delivery"]["runtime_delivery_gate"]["status"],
            WINDOWS_CUDA_RUNTIME_DELIVERY_GATE["status"],
        )
        self.assertEqual(
            selector["delivery"]["runtime_delivery_gate"]["mode"],
            WINDOWS_CUDA_RUNTIME_DELIVERY_GATE["mode"],
        )
        self.assertTrue(selector["delivery"]["runtime_delivery_gate"]["pinned_manifest_available"])
        self.assertTrue(selector["delivery"]["runtime_delivery_gate"]["checksum_verification_available"])
        self.assertFalse(selector["delivery"]["runtime_delivery_gate"]["managed_download_available"])
        self.assertEqual(selector["delivery"]["runtime_delivery_gate"]["candidate_release"]["tag"], "b9371")
        artifact_names = [
            item["name"]
            for item in selector["delivery"]["runtime_delivery_gate"]["candidate_artifacts"]
        ]
        self.assertIn("llama-b9371-bin-win-cuda-12.4-x64.zip", artifact_names)
        self.assertIn("cudart-llama-bin-win-cuda-12.4-x64.zip", artifact_names)
        candidate_review = selector["delivery"]["runtime_delivery_gate"]["candidate_review"]
        self.assertEqual(candidate_review["status"], "blocked")
        self.assertEqual(candidate_review["status_reason"], "artifact_metadata_recorded_but_candidate_not_reviewed")
        review_checks = {item["id"]: item for item in candidate_review["checks"]}
        self.assertEqual(review_checks["asset_sha256_digests_pinned"]["status"], "recorded")
        self.assertEqual(review_checks["archive_contents_inspected"]["status"], "pending")
        self.assertEqual(review_checks["license_and_runtime_dll_distribution_reviewed"]["status"], "pending")
        self.assertEqual(review_checks["windows_nvidia_version_smoke_completed"]["status"], "pending")
        self.assertEqual(selector["support"]["tier"], "preview")
        self.assertFalse(selector["fallback"]["allowed"])
        self.assertIn(
            {"id": "cuda_version", "status": "passed", "observed": "12.5"},
            selector["compatibility"]["probes"],
        )
        self.assertIn("fallback_not_allowed", selector["compatibility"]["reason_codes"])
        self.assertIn("full_loop_not_proven", selector["compatibility"]["reason_codes"])
        self.assertIn("runtime_binary_missing", selector["compatibility"]["reason_codes"])
        self.assertNotIn("windows_host_required", selector["compatibility"]["reason_codes"])
        self.assertEqual(result["proof_gate"]["status"], "blocked")
        self.assertEqual(result["proof_gate"]["reason_code"], "full_loop_not_proven")
        self.assertEqual(result["proof_gate"]["required_steps"], WINDOWS_CUDA_PROOF_STEPS)
        self.assertEqual(
            [item["id"] for item in result["proof_gate"]["required_steps"]],
            [
                "select_runtime",
                "pair_hub_runner",
                "known_good_gguf_run",
                "upload_result",
                "review_result",
                "capture_support_export",
            ],
        )

    def test_windows_cuda_preflight_reports_old_driver(self):
        result = windows_cuda_preflight(
            nvidia_smi_output="NVIDIA GTX 1080, 449.90, 8192, 6.1\n",
            platform_snapshot={"system": "windows", "arch": "x86_64", "version": "10"},
            which=lambda _name: None,
        )

        reason_codes = result["selector"]["compatibility"]["reason_codes"]
        self.assertIn("driver_too_old", reason_codes)
        self.assertIn("full_loop_not_proven", reason_codes)

    def test_windows_cuda_preflight_reports_missing_nvidia_smi(self):
        result = windows_cuda_preflight(
            platform_snapshot={"system": "windows", "arch": "x86_64", "version": "11"},
            which=lambda _name: None,
        )

        reason_codes = result["selector"]["compatibility"]["reason_codes"]
        self.assertIn("nvidia_smi_missing", reason_codes)
        self.assertEqual(result["selector"]["accelerator"]["vendor"], "unknown")

    def test_windows_cuda_preflight_reports_no_nvidia_gpu_rows(self):
        result = windows_cuda_preflight(
            nvidia_smi_output="",
            platform_snapshot={"system": "windows", "arch": "x86_64", "version": "11"},
            which=lambda _name: None,
        )

        self.assertIn("no_nvidia_gpu", result["selector"]["compatibility"]["reason_codes"])

    @mock.patch("infergrade.cuda.subprocess.run")
    def test_windows_cuda_preflight_reports_nvidia_smi_failure_separately_from_empty_gpu_rows(self, run_mock):
        run_mock.side_effect = [
            mock.Mock(returncode=1, stdout="", stderr="Field \"cuda_version\" is not a valid field"),
            mock.Mock(returncode=1, stdout="", stderr="NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver."),
            mock.Mock(returncode=1, stdout="", stderr="NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver."),
        ]

        result = windows_cuda_preflight(
            nvidia_smi_path="nvidia-smi",
            platform_snapshot={"system": "windows", "arch": "x86_64", "version": "11"},
            which=lambda _name: None,
        )

        compatibility = result["selector"]["compatibility"]
        reason_codes = compatibility["reason_codes"]
        self.assertIn("nvidia_smi_failed", reason_codes)
        self.assertNotIn("no_nvidia_gpu", reason_codes)
        self.assertIn(
            {
                "id": "nvidia_smi",
                "status": "failed",
                "detail": "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.",
            },
            compatibility["probes"],
        )

    @mock.patch("infergrade.cuda.subprocess.run")
    def test_windows_cuda_preflight_reports_nvidia_smi_timeout(self, run_mock):
        run_mock.side_effect = subprocess.TimeoutExpired(cmd=["nvidia-smi"], timeout=8)

        result = windows_cuda_preflight(
            nvidia_smi_path="nvidia-smi",
            platform_snapshot={"system": "windows", "arch": "x86_64", "version": "11"},
            which=lambda _name: None,
        )

        compatibility = result["selector"]["compatibility"]
        self.assertIn("nvidia_smi_timeout", compatibility["reason_codes"])
        self.assertNotIn("nvidia_smi_failed", compatibility["reason_codes"])
        self.assertNotIn("no_nvidia_gpu", compatibility["reason_codes"])
        self.assertIn(
            {"id": "nvidia_smi", "status": "failed", "detail": "nvidia-smi did not return within 8 seconds."},
            compatibility["probes"],
        )
        self.assertNotIn(
            {"id": "nvidia_smi", "status": "failed", "detail": "No NVIDIA GPU rows were reported."},
            compatibility["probes"],
        )

    def test_windows_cuda_preflight_reports_vram_and_artifact_failures(self):
        result = windows_cuda_preflight(
            nvidia_smi_output="NVIDIA RTX 3060, 555.85, 8192, 8.6\n",
            platform_snapshot={"system": "windows", "arch": "x86_64", "version": "11"},
            required_vram_bytes=16 * 1024 * 1024 * 1024,
            artifact_download_error="download timed out",
            which=lambda _name: None,
        )

        reason_codes = result["selector"]["compatibility"]["reason_codes"]
        self.assertIn("insufficient_vram", reason_codes)
        self.assertIn("model_too_large", reason_codes)
        self.assertIn("artifact_download_failed", reason_codes)

    def test_windows_cuda_preflight_selects_gpu_that_satisfies_vram_requirement(self):
        result = windows_cuda_preflight(
            nvidia_smi_output=(
                "NVIDIA RTX 3060, 555.85, 8192, 8.6\n"
                "NVIDIA RTX 4090, 555.85, 24564, 8.9\n"
            ),
            platform_snapshot={"system": "windows", "arch": "x86_64", "version": "11"},
            required_vram_bytes=16 * 1024 * 1024 * 1024,
            which=lambda _name: None,
        )

        selector = result["selector"]
        self.assertEqual(selector["accelerator"]["model"], "NVIDIA RTX 4090")
        self.assertEqual(selector["accelerator"]["vram_bytes"], 24564 * 1024 * 1024)
        self.assertEqual(result["selected_gpu"]["index"], 1)
        self.assertEqual(result["selected_gpu"]["position"], 2)
        self.assertEqual(result["selected_gpu"]["count"], 2)
        self.assertEqual(result["selected_gpu"]["model"], "NVIDIA RTX 4090")
        self.assertEqual(result["selected_gpu"]["vram_bytes"], 24564 * 1024 * 1024)
        self.assertNotIn("insufficient_vram", selector["compatibility"]["reason_codes"])
        self.assertIn(
            {"id": "selected_gpu", "status": "passed", "observed": "NVIDIA RTX 4090 (2 of 2)"},
            selector["compatibility"]["probes"],
        )
        self.assertIn(
            {"id": "vram_capacity", "status": "passed", "observed": 24564 * 1024 * 1024},
            selector["compatibility"]["probes"],
        )

    def test_windows_cuda_preflight_reports_runtime_binary_mismatch(self):
        result = windows_cuda_preflight(
            nvidia_smi_output="NVIDIA RTX 4090, 555.85, 24564, 8.9\n",
            platform_snapshot={"system": "windows", "arch": "x86_64", "version": "11"},
            selected_binary_set="llama_cpp_windows_cpu_x86_64",
            which=lambda _name: None,
        )

        selector = result["selector"]
        self.assertEqual(selector["delivery"]["binary_set"], "llama_cpp_windows_cpu_x86_64")
        self.assertIn("runtime_binary_mismatch", selector["compatibility"]["reason_codes"])

    @mock.patch("infergrade.cuda.subprocess.run")
    def test_windows_cuda_preflight_smokes_selected_runtime_binary(self, run_mock):
        run_mock.return_value = mock.Mock(returncode=0, stdout="llama.cpp build 1234\n", stderr="")

        result = windows_cuda_preflight(
            runtime_binary_path="C:\\llama.cpp\\llama-cli.exe",
            nvidia_smi_output="NVIDIA RTX 4090, 555.85, 24564, 8.9\n",
            platform_snapshot={"system": "windows", "arch": "x86_64", "version": "11"},
            which=lambda _name: None,
        )

        selector = result["selector"]
        self.assertEqual(selector["delivery"]["mode"], "user_selected")
        self.assertEqual(selector["delivery"]["source"], "explicit_path")
        self.assertEqual(selector["delivery"]["runtime_delivery_gate"]["status"], "blocked")
        self.assertEqual(
            selector["delivery"]["runtime_delivery_gate"]["candidate_artifacts"][0]["sha256"],
            "762585777eb39884848ce410f62140f79d21305203fe948ca57f54ec89dc2255",
        )
        self.assertIn("candidate_runtime_not_validated", selector["delivery"]["runtime_delivery_gate"]["reason_codes"])
        self.assertIn("candidate_review_not_complete", selector["delivery"]["runtime_delivery_gate"]["reason_codes"])
        self.assertIn("managed_download_not_enabled", selector["delivery"]["runtime_delivery_gate"]["reason_codes"])
        self.assertEqual(selector["binary"]["version_output"], "llama.cpp build 1234")
        self.assertIn("full_loop_not_proven", selector["compatibility"]["reason_codes"])
        self.assertIn("fallback_not_allowed", selector["compatibility"]["reason_codes"])
        self.assertNotIn("runtime_smoke_failed", selector["compatibility"]["reason_codes"])

    @mock.patch("infergrade.cuda.windows_cuda_candidate_manifest")
    def test_runtime_delivery_gate_reflects_managed_download_candidate_flag(self, manifest_mock):
        manifest = windows_cuda_candidate_manifest()
        manifest["managed_download_enabled"] = True
        manifest_mock.return_value = manifest

        result = windows_cuda_preflight(
            nvidia_smi_output="NVIDIA RTX 4090, 555.85, 24564, 8.9\n",
            platform_snapshot={"system": "windows", "arch": "x86_64", "version": "11"},
            which=lambda _name: None,
        )

        gate = result["selector"]["delivery"]["runtime_delivery_gate"]
        self.assertEqual(gate["status"], "blocked")
        self.assertEqual(gate["mode"], "managed_download")
        self.assertTrue(gate["managed_download_available"])
        self.assertIn("candidate_runtime_not_validated", gate["reason_codes"])
        self.assertIn("candidate_review_not_complete", gate["reason_codes"])
        self.assertNotIn("managed_download_not_enabled", gate["reason_codes"])

    @mock.patch("infergrade.cuda.windows_cuda_candidate_manifest")
    def test_runtime_delivery_gate_stays_blocked_when_validated_candidate_review_is_pending(self, manifest_mock):
        manifest = windows_cuda_candidate_manifest()
        manifest["status"] = "validated"
        manifest["managed_download_enabled"] = True
        manifest_mock.return_value = manifest

        result = windows_cuda_preflight(
            nvidia_smi_output="NVIDIA RTX 4090, 555.85, 24564, 8.9\n",
            platform_snapshot={"system": "windows", "arch": "x86_64", "version": "11"},
            which=lambda _name: None,
        )

        gate = result["selector"]["delivery"]["runtime_delivery_gate"]
        self.assertEqual(gate["status"], "blocked")
        self.assertEqual(gate["mode"], "managed_download")
        self.assertTrue(gate["managed_download_available"])
        self.assertEqual(gate["reason_codes"], ["candidate_review_not_complete"])
        self.assertEqual(result["proof_gate"]["status"], "blocked")
        self.assertEqual(result["proof_gate"]["reason_code"], "full_loop_not_proven")

    @mock.patch("infergrade.cuda.windows_cuda_candidate_manifest")
    def test_runtime_delivery_gate_can_be_ready_for_validated_reviewed_managed_candidate(self, manifest_mock):
        manifest = windows_cuda_candidate_manifest()
        manifest["status"] = "validated"
        manifest["managed_download_enabled"] = True
        manifest["review"]["status"] = "ready"
        manifest["review"]["status_reason"] = "candidate_review_complete"
        manifest["review"]["checks"] = [
            dict(item, status="passed", evidence="Reviewed and passed.")
            for item in manifest["review"]["checks"]
        ]
        manifest_mock.return_value = manifest

        result = windows_cuda_preflight(
            nvidia_smi_output="NVIDIA RTX 4090, 555.85, 24564, 8.9\n",
            platform_snapshot={"system": "windows", "arch": "x86_64", "version": "11"},
            which=lambda _name: None,
        )

        gate = result["selector"]["delivery"]["runtime_delivery_gate"]
        self.assertEqual(gate["status"], "ready")
        self.assertEqual(gate["mode"], "managed_download")
        self.assertTrue(gate["managed_download_available"])
        self.assertEqual(gate["reason_codes"], [])
        self.assertEqual(gate["candidate_review"]["status"], "ready")
        self.assertEqual(result["proof_gate"]["status"], "blocked")
        self.assertEqual(result["proof_gate"]["reason_code"], "full_loop_not_proven")

    @mock.patch("infergrade.cuda.subprocess.run")
    def test_windows_cuda_preflight_records_runtime_binary_fingerprint(self, run_mock):
        run_mock.return_value = mock.Mock(returncode=0, stdout="llama.cpp build 1234\n", stderr="")
        with tempfile.TemporaryDirectory(prefix="infergrade-cuda-runtime-") as tempdir:
            runtime_path = os.path.join(tempdir, "llama-cli.exe")
            with open(runtime_path, "wb") as handle:
                handle.write(b"cuda runtime")

            result = windows_cuda_preflight(
                runtime_binary_path=runtime_path,
                nvidia_smi_output="NVIDIA RTX 4090, 555.85, 24564, 8.9\n",
                platform_snapshot={"system": "windows", "arch": "x86_64", "version": "11"},
                which=lambda _name: None,
            )

        fingerprint = result["selector"]["binary"]["fingerprint"]
        self.assertEqual(fingerprint["status"], "recorded")
        self.assertEqual(fingerprint["size_bytes"], len(b"cuda runtime"))
        self.assertEqual(fingerprint["sha256"], hashlib.sha256(b"cuda runtime").hexdigest())

    @mock.patch("infergrade.cuda.subprocess.run")
    def test_windows_cuda_preflight_reports_runtime_binary_timeout(self, run_mock):
        run_mock.side_effect = subprocess.TimeoutExpired(cmd=["C:\\llama.cpp\\llama-cli.exe", "--version"], timeout=5)

        result = windows_cuda_preflight(
            runtime_binary_path="C:\\llama.cpp\\llama-cli.exe",
            nvidia_smi_output="NVIDIA RTX 4090, 555.85, 24564, 8.9\n",
            platform_snapshot={"system": "windows", "arch": "x86_64", "version": "11"},
            which=lambda _name: None,
        )

        selector = result["selector"]
        self.assertIn("runtime_smoke_timeout", selector["compatibility"]["reason_codes"])
        self.assertNotIn("runtime_smoke_failed", selector["compatibility"]["reason_codes"])
        self.assertIn(
            {
                "id": "cuda_runtime_binary",
                "status": "failed",
                "detail": "Selected CUDA llama.cpp binary did not return --version within 5 seconds.",
            },
            selector["compatibility"]["probes"],
        )

    @mock.patch("infergrade.cuda.subprocess.run")
    def test_windows_cuda_preflight_reports_runtime_binary_not_found(self, run_mock):
        run_mock.side_effect = FileNotFoundError()

        result = windows_cuda_preflight(
            runtime_binary_path="C:\\llama.cpp\\missing.exe",
            nvidia_smi_output="NVIDIA RTX 4090, 555.85, 24564, 8.9\n",
            platform_snapshot={"system": "windows", "arch": "x86_64", "version": "11"},
            which=lambda _name: None,
        )

        selector = result["selector"]
        self.assertIn("runtime_binary_not_found", selector["compatibility"]["reason_codes"])
        self.assertIn(
            {
                "id": "cuda_runtime_binary",
                "status": "failed",
                "detail": "Selected CUDA llama.cpp binary was not found.",
            },
            selector["compatibility"]["probes"],
        )

    @mock.patch("infergrade.cuda.subprocess.run")
    def test_windows_cuda_preflight_queries_cuda_version_when_available(self, run_mock):
        run_mock.return_value = mock.Mock(returncode=0, stdout="NVIDIA RTX 4090, 555.85, 24564, 8.9, 12.5\n", stderr="")

        result = windows_cuda_preflight(
            nvidia_smi_path="nvidia-smi",
            platform_snapshot={"system": "windows", "arch": "x86_64", "version": "11"},
            which=lambda _name: None,
        )

        selector = result["selector"]
        self.assertIn(
            {"id": "cuda_version", "status": "passed", "observed": "12.5"},
            selector["compatibility"]["probes"],
        )
        self.assertIn(
            mock.call(
                [
                    "nvidia-smi",
                    "--query-gpu=name,driver_version,memory.total,compute_cap,cuda_version",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=8,
            ),
            run_mock.mock_calls,
        )

    @mock.patch("infergrade.cuda.subprocess.run")
    def test_windows_cuda_preflight_falls_back_when_cuda_version_query_is_unsupported(self, run_mock):
        run_mock.side_effect = [
            mock.Mock(returncode=1, stdout="", stderr="Field \"cuda_version\" is not a valid field"),
            mock.Mock(returncode=0, stdout="| NVIDIA-SMI 555.85       Driver Version: 555.85       CUDA Version: 12.5 |\n", stderr=""),
            mock.Mock(returncode=0, stdout="NVIDIA RTX 4090, 555.85, 24564, 8.9\n", stderr=""),
        ]

        result = windows_cuda_preflight(
            nvidia_smi_path="nvidia-smi",
            platform_snapshot={"system": "windows", "arch": "x86_64", "version": "11"},
            which=lambda _name: None,
        )

        selector = result["selector"]
        self.assertIn(
            {"id": "cuda_version", "status": "passed", "observed": "12.5"},
            selector["compatibility"]["probes"],
        )
        self.assertEqual(run_mock.call_count, 3)

    def test_windows_cuda_runtime_delivery_gate_derives_candidate_from_runtime_manifest(self):
        result = windows_cuda_preflight(
            nvidia_smi_output="NVIDIA RTX 4090, 555.85, 24564, 8.9, 12.5\n",
            platform_snapshot={"system": "windows", "arch": "x86_64", "version": "11"},
            which=lambda _name: None,
        )
        candidate = windows_cuda_candidate_manifest()
        gate = result["selector"]["delivery"]["runtime_delivery_gate"]

        self.assertEqual(gate["candidate_release"]["project"], candidate["upstream"]["project"])
        self.assertEqual(gate["candidate_release"]["tag"], candidate["upstream"]["tag"])
        self.assertEqual(gate["candidate_release"]["selected_at"], candidate["selected_for_review_at"])
        self.assertEqual(gate["managed_download_available"], candidate["managed_download_enabled"])
        self.assertEqual(gate["candidate_review"]["status"], candidate["review"]["status"])
        review_checks = {item["id"]: item for item in gate["candidate_review"]["checks"]}
        self.assertEqual(review_checks["asset_sha256_digests_pinned"]["status"], "recorded")
        self.assertEqual(review_checks["hub_upload_and_result_reviewed"]["status"], "pending")
        artifacts_by_name = {item["name"]: item for item in gate["candidate_artifacts"]}
        for artifact in candidate["artifacts"]:
            expected_name = artifact["url"].rsplit("/", 1)[-1]
            self.assertIn(expected_name, artifacts_by_name)
            self.assertEqual(artifacts_by_name[expected_name]["sha256"], artifact["sha256"])
        self.assertTrue(artifacts_by_name["llama-b9371-bin-win-cuda-12.4-x64.zip"]["required"])
        self.assertFalse(artifacts_by_name["cudart-llama-bin-win-cuda-12.4-x64.zip"]["required"])


if __name__ == "__main__":
    unittest.main()
