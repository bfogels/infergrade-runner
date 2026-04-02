import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.cli import main


class CliTests(unittest.TestCase):
    def test_install_images_command_invokes_image_installer(self):
        output = io.StringIO()
        with mock.patch(
            "infergrade.cli.install_known_images",
            return_value={"infergrade-llama-cpp:local": {"action": "built"}},
        ) as install_mock:
            with redirect_stdout(output):
                exit_code = main(["install-images", "--image", "infergrade-llama-cpp:local"])

        self.assertEqual(exit_code, 0)
        install_mock.assert_called_once_with(image="infergrade-llama-cpp:local", rebuild=False)
        self.assertIn('"infergrade-llama-cpp:local"', output.getvalue())

    def test_install_images_command_supports_rebuild(self):
        output = io.StringIO()
        with mock.patch(
            "infergrade.cli.install_known_images",
            return_value={"infergrade-runner-core:local": {"action": "rebuilt"}},
        ) as install_mock:
            with redirect_stdout(output):
                exit_code = main(["install-images", "--image", "infergrade-runner-core:local", "--rebuild"])

        self.assertEqual(exit_code, 0)
        install_mock.assert_called_once_with(image="infergrade-runner-core:local", rebuild=True)
        self.assertIn('"rebuilt"', output.getvalue())

    def test_start_command_invokes_local_worker_loop(self):
        output = io.StringIO()
        with mock.patch(
            "infergrade.cli.run_worker_loop",
            return_value={"worker_id": "worker-test", "processed_jobs": 0, "completed_jobs": 0, "failed_jobs": 0},
        ) as run_loop_mock:
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "start",
                        "--api-url",
                        "http://localhost:8000",
                        "--poll-interval-seconds",
                        "2",
                    ]
                )

        self.assertEqual(exit_code, 0)
        run_loop_mock.assert_called_once_with(
            api_url="http://localhost:8000",
            execution_mode="local_container",
            worker_id=None,
            hostname=None,
            api_token=None,
            run_token=None,
            simulate=False,
            poll_interval_seconds=2.0,
            max_jobs=None,
            emit_progress=mock.ANY,
        )
        self.assertIn('"worker_id": "worker-test"', output.getvalue())

    def test_start_command_uses_paired_profile_when_api_url_is_omitted(self):
        output = io.StringIO()
        with mock.patch(
            "infergrade.cli.run_worker_loop",
            return_value={"worker_id": "worker-test", "processed_jobs": 0, "completed_jobs": 0, "failed_jobs": 0},
        ) as run_loop_mock, mock.patch(
            "infergrade.cli.resolve_runner_api_url",
            return_value="http://localhost:8000",
        ), mock.patch(
            "infergrade.cli.resolve_runner_api_token",
            return_value="qbhr_saved_token",
        ):
            with redirect_stdout(output):
                exit_code = main(["start", "--poll-interval-seconds", "2"])

        self.assertEqual(exit_code, 0)
        run_loop_mock.assert_called_once_with(
            api_url="http://localhost:8000",
            execution_mode="local_container",
            worker_id=None,
            hostname=None,
            api_token="qbhr_saved_token",
            run_token=None,
            simulate=False,
            poll_interval_seconds=2.0,
            max_jobs=None,
            emit_progress=mock.ANY,
        )

    def test_run_job_command_invokes_single_job_execution(self):
        output = io.StringIO()
        with mock.patch(
            "infergrade.cli.run_worker_once",
            return_value={"claimed": True, "completed": True, "run": {"run_id": "run_example"}},
        ) as run_job_mock:
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "run-job",
                        "--api-url",
                        "http://localhost:8000",
                        "--run-id",
                        "run_example",
                    ]
                )

        self.assertEqual(exit_code, 0)
        run_job_mock.assert_called_once_with(
            api_url="http://localhost:8000",
            execution_mode="local_container",
            worker_id=None,
            run_id="run_example",
            run_config_id=None,
            provider_id=None,
            instance_type_id=None,
            hostname=None,
            api_token=None,
            run_token=None,
            simulate=False,
            emit_progress=mock.ANY,
        )
        self.assertIn('"run_id": "run_example"', output.getvalue())

    def test_pair_command_redeems_code_and_saves_profile(self):
        output = io.StringIO()
        response = {
            "runner_profile": {
                "api_url": "http://localhost:8000",
                "access_token": "qbhr_pair_token",
                "label": "Brian MacBook Pro",
            }
        }
        with mock.patch(
            "infergrade.cli.redeem_runner_pairing",
            return_value=response,
        ) as redeem_mock, mock.patch(
            "infergrade.cli.save_runner_profile",
            return_value="/tmp/runner_profile.json",
        ) as save_mock:
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "pair",
                        "--api-url",
                        "http://localhost:8000",
                        "--pair-code",
                        "igrp_example",
                        "--label",
                        "Brian MacBook Pro",
                    ]
                )

        self.assertEqual(exit_code, 0)
        redeem_mock.assert_called_once_with(
            api_url="http://localhost:8000",
            pair_code="igrp_example",
            label="Brian MacBook Pro",
            hostname=mock.ANY,
        )
        save_mock.assert_called_once_with(response["runner_profile"])
        self.assertIn('"paired": true', output.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
