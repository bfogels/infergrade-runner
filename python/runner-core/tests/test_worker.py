import sys
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.worker import _progress_percent, run_worker_loop, run_worker_once


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
                                    with mock.patch("infergrade.worker.upload_bundle", return_value={"stored": True}) as upload_mock:
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
        upload_mock.assert_called_once()
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
        scoped_upload_mock.assert_called_once()

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


if __name__ == "__main__":
    unittest.main()
