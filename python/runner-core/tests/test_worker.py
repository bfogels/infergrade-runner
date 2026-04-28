import sys
import unittest
from unittest import mock
from urllib import error as urllib_error

sys.path.insert(0, "python/runner-core/src")

from infergrade.worker import _claim_error_message, _classify_worker_failure, _progress_percent, run_worker_loop, run_worker_once


class WorkerTests(unittest.TestCase):
    def test_worker_once_returns_unclaimed_when_no_job_available(self):
        with mock.patch("infergrade.worker.claim_run_job", return_value={"run": None}):
            result = run_worker_once(
                api_url="http://localhost:8000",
                execution_mode="local_container",
                worker_id="worker-1",
                emit_progress=lambda _message: None,
            )
        self.assertFalse(result["claimed"])
        self.assertEqual(result["worker_id"], "worker-1")

    def test_worker_once_passes_run_id_filter_when_provided(self):
        with mock.patch("infergrade.worker.claim_run_job", return_value={"run": None}) as claim_mock:
            result = run_worker_once(
                api_url="http://localhost:8000",
                execution_mode="local_container",
                worker_id="worker-1",
                run_id="run_specific",
            )

        self.assertFalse(result["claimed"])
        claim_mock.assert_called_once_with(
            "http://localhost:8000",
            worker_id="worker-1",
            execution_mode="local_container",
            api_token=None,
            run_token=None,
            run_id="run_specific",
            run_config_id=None,
            provider_id=None,
            instance_type_id=None,
            hostname=mock.ANY,
        )

    def test_worker_once_reports_string_claim_errors(self):
        with mock.patch("infergrade.worker.claim_run_job", return_value={"error": "runner session expired"}):
            with self.assertRaisesRegex(RuntimeError, "runner session expired"):
                run_worker_once(
                    api_url="http://localhost:8000",
                    execution_mode="local_container",
                    worker_id="worker-1",
                )

    def test_worker_once_reports_detail_only_claim_errors(self):
        with mock.patch("infergrade.worker.claim_run_job", return_value={"detail": [{"msg": "field required"}]}):
            with self.assertRaisesRegex(RuntimeError, "field required"):
                run_worker_once(
                    api_url="http://localhost:8000",
                    execution_mode="local_container",
                    worker_id="worker-1",
                )

    def test_claim_error_message_handles_common_api_envelopes(self):
        self.assertEqual(_claim_error_message({"error": "plain failure"}), "plain failure")
        self.assertEqual(_claim_error_message({"error": {"message": "structured failure"}}), "structured failure")
        self.assertEqual(_claim_error_message({"detail": "detail failure"}), "detail failure")
        self.assertEqual(_claim_error_message({"detail": [{"msg": "field required"}]}), "field required")

    def test_worker_once_executes_claimed_job_and_uploads_bundle(self):
        claimed_run = {
            "run_id": "run_example",
            "run_config_id": "rcfg_example",
            "execution_mode": "local_container",
            "output_dir": "runs/run_example",
            "cloud": None,
        }
        run_config = {
            "run_config_id": "rcfg_example",
            "name": "Example",
            "request": {
                "run": {
                    "model": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
                    "backend": "llama.cpp",
                    "tier": "canary",
                }
            },
        }
        fake_request = mock.Mock()
        fake_request.execution_mode = "local_container"
        fake_request.resume = False
        fake_request.output_dir = None
        fake_request.quant_artifact_cache_dir = "~/.cache/infergrade/artifacts"
        fake_request.cloud_provider = None
        fake_request.cloud_instance_type = None

        with mock.patch.dict("os.environ", {"INFERGRADE_HOST_ARTIFACT_CACHE_DIR": "/host/cache"}, clear=False):
            with mock.patch("infergrade.worker.claim_run_job", return_value={"run": claimed_run}) as claim_mock:
                with mock.patch("infergrade.worker.fetch_run_config", return_value=run_config):
                    with mock.patch("infergrade.worker.request_from_run_config_document", return_value=fake_request):
                        with mock.patch("infergrade.worker.run_doctor", return_value={"ok": True, "checks": []}) as doctor_mock:
                            with mock.patch(
                                "infergrade.worker.load_progress",
                                return_value={
                                    "current_stage": "deployment",
                                    "current_detail": "interactive_chat_v1",
                                    "request_context": {"deployment_profiles": ["interactive_chat_v1"]},
                                    "deployment_profiles": {"interactive_chat_v1": {"status": "running"}},
                                },
                            ):
                                with mock.patch(
                                    "infergrade.worker.run_infergrade",
                                    side_effect=lambda request, emit_progress=None: (
                                        emit_progress("Running deployment profile interactive_chat_v1...") if emit_progress else None,
                                        {"bundle_id": "qb_bundle", "output_dir": "runs/run_example"},
                                    )[1],
                                ):
                                    with mock.patch("infergrade.worker.upload_run_bundle", return_value={"stored": True}) as upload_mock:
                                        with mock.patch("infergrade.worker.complete_run_job", return_value={"run": {"run_id": "run_example", "status": "completed"}}) as complete_mock:
                                            with mock.patch("infergrade.worker.heartbeat_run_job") as heartbeat_mock:
                                                result = run_worker_once(
                                                    api_url="http://localhost:8000",
                                                    execution_mode="local_container",
                                                    worker_id="worker-1",
                                                )

        self.assertTrue(result["claimed"])
        self.assertTrue(result["completed"])
        claim_mock.assert_called_once()
        doctor_mock.assert_called_once()
        upload_mock.assert_called_once_with(
            "runs/run_example",
            "http://localhost:8000",
            run_id="run_example",
            run_token=None,
            api_token=None,
        )
        complete_mock.assert_called_once()
        heartbeat_mock.assert_called()
        self.assertTrue(
            any(
                call.kwargs.get("stage") == "deployment"
                and call.kwargs.get("detail") == "interactive_chat_v1"
                and call.kwargs.get("progress_percent") is not None
                and call.kwargs.get("progress_percent") >= 60.0
                for call in heartbeat_mock.call_args_list
            )
        )
        self.assertEqual(fake_request.output_dir, "runs/run_example")
        self.assertEqual(fake_request.quant_artifact_cache_dir, "/host/cache")
        self.assertTrue(fake_request.resume)

    def test_worker_once_fails_when_preflight_fails(self):
        claimed_run = {
            "run_id": "run_example",
            "run_config_id": "rcfg_example",
            "execution_mode": "local_container",
            "output_dir": "runs/run_example",
            "cloud": None,
        }
        run_config = {
            "run_config_id": "rcfg_example",
            "request": {
                "run": {
                    "model": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
                    "backend": "llama.cpp",
                    "tier": "canary",
                }
            },
        }
        fake_request = mock.Mock()
        fake_request.execution_mode = "local_container"
        fake_request.resume = False
        fake_request.output_dir = None
        fake_request.cloud_provider = None
        fake_request.cloud_instance_type = None

        with mock.patch("infergrade.worker.claim_run_job", return_value={"run": claimed_run}):
            with mock.patch("infergrade.worker.fetch_run_config", return_value=run_config):
                with mock.patch("infergrade.worker.request_from_run_config_document", return_value=fake_request):
                    with mock.patch(
                        "infergrade.worker.run_doctor",
                        return_value={
                            "ok": False,
                            "checks": [
                                {"id": "docker_daemon", "status": "error", "message": "Docker daemon is not reachable."}
                            ],
                        },
                    ):
                        with mock.patch("infergrade.worker.fail_run_job", return_value={"run": {"run_id": "run_example", "status": "failed"}}) as fail_mock:
                            with mock.patch("infergrade.worker.heartbeat_run_job"):
                                result = run_worker_once(
                                    api_url="http://localhost:8000",
                                    execution_mode="local_container",
                                    worker_id="worker-1",
                                )

        self.assertTrue(result["claimed"])
        self.assertFalse(result["completed"])
        self.assertIn("Preflight failed", result["error"])
        fail_mock.assert_called_once()
        self.assertEqual(fail_mock.call_args.kwargs["error_code"], "missing_runtime_image")
        self.assertTrue(fail_mock.call_args.kwargs["recovery"])

    def test_cloud_worker_passes_provider_filters_when_claiming(self):
        with mock.patch("infergrade.worker.claim_run_job", return_value={"run": None}) as claim_mock:
            result = run_worker_once(
                api_url="http://localhost:8000",
                execution_mode="cloud_container",
                worker_id="worker-cloud-1",
                provider_id="modal",
                instance_type_id="a10g",
                hostname="cloud-host-1",
            )

        self.assertFalse(result["claimed"])
        claim_mock.assert_called_once_with(
            "http://localhost:8000",
            worker_id="worker-cloud-1",
            execution_mode="cloud_container",
            api_token=None,
            run_token=None,
            run_id=None,
            run_config_id=None,
            provider_id="modal",
            instance_type_id="a10g",
            hostname="cloud-host-1",
        )

    def test_run_token_uses_run_scoped_upload(self):
        claimed_run = {
            "run_id": "run_example",
            "run_config_id": "rcfg_example",
            "execution_mode": "local_container",
            "output_dir": "runs/run_example",
            "cloud": None,
        }
        run_config = {
            "run_config_id": "rcfg_example",
            "request": {"run": {"model": "TinyLlama/TinyLlama-1.1B-Chat-v1.0", "backend": "llama.cpp", "tier": "canary"}},
        }
        fake_request = mock.Mock()
        fake_request.execution_mode = "local_container"
        fake_request.resume = False
        fake_request.output_dir = None
        fake_request.cloud_provider = None
        fake_request.cloud_instance_type = None

        with mock.patch("infergrade.worker.claim_run_job", return_value={"run": claimed_run}):
            with mock.patch("infergrade.worker.fetch_run_config", return_value=run_config):
                with mock.patch("infergrade.worker.request_from_run_config_document", return_value=fake_request):
                    with mock.patch("infergrade.worker.run_doctor", return_value={"ok": True, "checks": []}):
                        with mock.patch("infergrade.worker.run_infergrade", return_value={"bundle_id": "qb_bundle", "output_dir": "runs/run_example"}):
                            with mock.patch("infergrade.worker.upload_run_bundle", return_value={"stored": True}) as scoped_upload_mock:
                                with mock.patch("infergrade.worker.complete_run_job", return_value={"run": {"run_id": "run_example", "status": "completed"}}):
                                    with mock.patch("infergrade.worker.heartbeat_run_job"):
                                        result = run_worker_once(
                                            api_url="http://localhost:8000",
                                            execution_mode="local_container",
                                            worker_id="worker-1",
                                            run_id="run_example",
                                            run_token="igrt_example",
                                        )

        self.assertTrue(result["completed"])
        scoped_upload_mock.assert_called_once_with(
            "runs/run_example",
            "http://localhost:8000",
            run_id="run_example",
            run_token="igrt_example",
            api_token=None,
        )

    def test_runner_session_token_uses_run_scoped_upload(self):
        claimed_run = {
            "run_id": "run_example",
            "run_config_id": "rcfg_example",
            "execution_mode": "local_container",
            "output_dir": "runs/run_example",
            "cloud": None,
        }
        run_config = {
            "run_config_id": "rcfg_example",
            "request": {"run": {"model": "TinyLlama/TinyLlama-1.1B-Chat-v1.0", "backend": "llama.cpp", "tier": "canary"}},
        }
        fake_request = mock.Mock()
        fake_request.execution_mode = "local_container"
        fake_request.resume = False
        fake_request.output_dir = None
        fake_request.cloud_provider = None
        fake_request.cloud_instance_type = None

        with mock.patch("infergrade.worker.claim_run_job", return_value={"run": claimed_run}):
            with mock.patch("infergrade.worker.fetch_run_config", return_value=run_config):
                with mock.patch("infergrade.worker.request_from_run_config_document", return_value=fake_request):
                    with mock.patch("infergrade.worker.run_doctor", return_value={"ok": True, "checks": []}):
                        with mock.patch("infergrade.worker.run_infergrade", return_value={"bundle_id": "qb_bundle", "output_dir": "runs/run_example"}):
                            with mock.patch("infergrade.worker.upload_run_bundle", return_value={"stored": True}) as scoped_upload_mock:
                                with mock.patch("infergrade.worker.complete_run_job", return_value={"run": {"run_id": "run_example", "status": "completed"}}):
                                    with mock.patch("infergrade.worker.heartbeat_run_job"):
                                        with mock.patch("infergrade.worker.heartbeat_runner"):
                                            result = run_worker_once(
                                                api_url="http://localhost:8000",
                                                execution_mode="local_container",
                                                worker_id="worker-1",
                                                api_token="qbhr_runner_session",
                                            )

        self.assertTrue(result["completed"])
        scoped_upload_mock.assert_called_once_with(
            "runs/run_example",
            "http://localhost:8000",
            run_id="run_example",
            run_token=None,
            api_token="qbhr_runner_session",
        )

    def test_progress_percent_uses_capability_case_progress(self):
        payload = {
            "current_stage": "capability",
            "capability_benchmarks": {
                "evalplus_humaneval": {
                    "status": "running",
                    "completed_cases": 82,
                    "total_cases": 164,
                }
            },
        }
        self.assertGreater(_progress_percent(payload), 52.0)
        self.assertLess(_progress_percent(payload), 60.1)

    def test_progress_percent_uses_deployment_iteration_progress(self):
        payload = {
            "current_stage": "deployment",
            "request_context": {"deployment_profiles": ["interactive_chat_v1"]},
            "deployment_profiles": {
                "interactive_chat_v1": {
                    "status": "running",
                    "completed_iterations": 3,
                    "total_iterations": 7,
                }
            },
        }
        self.assertGreater(_progress_percent(payload), 60.0)
        self.assertLess(_progress_percent(payload), 94.1)

    def test_worker_loop_registers_runner_diagnostics(self):
        snapshot = {
            "environment": {"hardware_class": "apple_silicon"},
            "contract": {"publisher": "infergrade-runner", "contract_version": "0.1.0"},
            "diagnostics": {"status": "ready", "checks": []},
        }
        with mock.patch("infergrade.worker.collect_runner_diagnostics", return_value=snapshot):
            with mock.patch("infergrade.worker.register_runner") as register_mock:
                with mock.patch("infergrade.worker.heartbeat_runner"):
                    with mock.patch("infergrade.worker.run_worker_once", return_value={"claimed": True, "completed": True, "worker_id": "runner-1"}):
                        result = run_worker_loop(
                            api_url="http://localhost:8000",
                            execution_mode="local_native",
                            worker_id="runner-1",
                            max_jobs=1,
                        )

        self.assertEqual(result["processed_jobs"], 1)
        register_mock.assert_called_once()
        self.assertEqual(register_mock.call_args.kwargs["environment"], snapshot["environment"])
        self.assertEqual(register_mock.call_args.kwargs["contract"], snapshot["contract"])
        self.assertEqual(register_mock.call_args.kwargs["diagnostics"], snapshot["diagnostics"])

    def test_worker_loop_retries_after_claim_error(self):
        snapshot = {
            "environment": {"hardware_class": "apple_silicon"},
            "contract": {"publisher": "infergrade-runner", "contract_version": "0.1.0"},
            "diagnostics": {"status": "ready", "checks": []},
        }
        messages = []
        attempts = [
            RuntimeError("temporary claim failure"),
            {"claimed": True, "completed": True, "worker_id": "runner-1"},
        ]

        def worker_once_side_effect(**_kwargs):
            next_attempt = attempts.pop(0)
            if isinstance(next_attempt, Exception):
                raise next_attempt
            return next_attempt

        with mock.patch("infergrade.worker.collect_runner_diagnostics", return_value=snapshot):
            with mock.patch("infergrade.worker.register_runner"):
                with mock.patch("infergrade.worker.heartbeat_runner") as heartbeat_mock:
                    with mock.patch("infergrade.worker.time.sleep") as sleep_mock:
                        with mock.patch("infergrade.worker.run_worker_once", side_effect=worker_once_side_effect):
                            result = run_worker_loop(
                                api_url="http://localhost:8000",
                                execution_mode="local_native",
                                worker_id="runner-1",
                                max_jobs=1,
                                emit_progress=messages.append,
                            )

        self.assertEqual(result["processed_jobs"], 1)
        self.assertEqual(result["completed_jobs"], 1)
        self.assertTrue(any("temporary claim failure" in message for message in messages))
        sleep_mock.assert_called_once()
        self.assertTrue(
            any(
                "Last claim failed: temporary claim failure" == call.kwargs.get("metadata", {}).get("message")
                for call in heartbeat_mock.call_args_list
            )
        )

    def test_worker_loop_retries_after_transient_api_disconnect(self):
        snapshot = {
            "environment": {"hardware_class": "apple_silicon"},
            "contract": {"publisher": "infergrade-runner", "contract_version": "0.1.0"},
            "diagnostics": {"status": "ready", "checks": []},
        }
        messages = []
        attempts = [
            urllib_error.URLError("connection refused"),
            {"claimed": True, "completed": True, "worker_id": "runner-1"},
        ]

        def worker_once_side_effect(**_kwargs):
            next_attempt = attempts.pop(0)
            if isinstance(next_attempt, Exception):
                raise next_attempt
            return next_attempt

        with mock.patch("infergrade.worker.collect_runner_diagnostics", return_value=snapshot):
            with mock.patch("infergrade.worker.register_runner"):
                with mock.patch("infergrade.worker.heartbeat_runner", side_effect=[None, urllib_error.URLError("still down")]):
                    with mock.patch("infergrade.worker.time.sleep") as sleep_mock:
                        with mock.patch("infergrade.worker.run_worker_once", side_effect=worker_once_side_effect):
                            result = run_worker_loop(
                                api_url="http://localhost:8000",
                                execution_mode="local_native",
                                worker_id="runner-1",
                                max_jobs=1,
                                emit_progress=messages.append,
                            )

        self.assertEqual(result["processed_jobs"], 1)
        self.assertEqual(result["completed_jobs"], 1)
        self.assertTrue(any("Claim failed:" in message and "connection refused" in message for message in messages))
        self.assertTrue(any("Runner heartbeat failed:" in message and "still down" in message for message in messages))
        sleep_mock.assert_called_once()

    def test_classify_worker_failure_maps_download_errors_to_actionable_code(self):
        failure = _classify_worker_failure(
            RuntimeError("curl failed while downloading https://example.invalid/model.gguf: 404")
        )

        self.assertEqual(failure["error_code"], "artifact_download_failed")
        self.assertIn("Artifact download failed", failure["message"])
        self.assertTrue(failure["recovery"])
        self.assertIn("raw_error", failure["details"])

    def test_classify_worker_failure_maps_low_disk_errors_to_actionable_code(self):
        failure = _classify_worker_failure(
            RuntimeError("insufficient free disk space for artifact cache: 1.00 GB free, 5.00 GB required")
        )

        self.assertEqual(failure["error_code"], "insufficient_disk")
        self.assertIn("could not write", failure["message"])
        self.assertIn("raw_error", failure["details"])

    def test_classify_doctor_cache_low_disk_failure_uses_disk_error_code(self):
        failure = _classify_worker_failure(
            RuntimeError("Preflight failed."),
            doctor_report={
                "ok": False,
                "checks": [
                    {
                        "id": "artifact_cache_dir",
                        "status": "error",
                        "message": "Insufficient free disk space.",
                        "details": {"path": "/tmp/cache"},
                    }
                ],
            },
        )

        self.assertEqual(failure["error_code"], "insufficient_disk")
        self.assertIn("artifact cache", failure["message"])
        self.assertIn("failed_check", failure["details"])


if __name__ == "__main__":
    unittest.main()
