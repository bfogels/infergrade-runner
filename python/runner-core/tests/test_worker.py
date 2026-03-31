import sys
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.worker import run_worker_once


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
            run_id="run_specific",
            run_config_id=None,
            provider_id=None,
            instance_type_id=None,
            hostname=mock.ANY,
            api_token=None,
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
        fake_request.cloud_provider = None
        fake_request.cloud_instance_type = None

        with mock.patch("infergrade.worker.claim_run_job", return_value={"run": claimed_run}) as claim_mock:
            with mock.patch("infergrade.worker.fetch_run_config", return_value=run_config):
                with mock.patch("infergrade.worker.request_from_run_config_document", return_value=fake_request):
                    with mock.patch(
                        "infergrade.worker.run_infergrade",
                        return_value={"bundle_id": "qb_bundle", "output_dir": "runs/run_example"},
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
        upload_mock.assert_called_once()
        complete_mock.assert_called_once()
        heartbeat_mock.assert_called()
        self.assertEqual(fake_request.output_dir, "runs/run_example")
        self.assertTrue(fake_request.resume)

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
            run_id=None,
            run_config_id=None,
            provider_id="modal",
            instance_type_id="a10g",
            hostname="cloud-host-1",
            api_token=None,
        )


if __name__ == "__main__":
    unittest.main()
