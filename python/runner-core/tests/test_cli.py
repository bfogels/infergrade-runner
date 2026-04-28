import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.cli import main


class CliTests(unittest.TestCase):
    def test_default_help_shows_canonical_runner_commands_only(self):
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as caught:
                main(["--help"])

        self.assertEqual(caught.exception.code, 0)
        help_text = output.getvalue()
        self.assertIn("{doctor,cache,install-runtime,pair,unpair,start}", help_text)
        self.assertIn("start               Start a long-lived local runner", help_text)
        self.assertNotIn("run-job", help_text)
        self.assertNotIn("upload-bundle", help_text)
        self.assertNotIn("show-capabilities", help_text)

    def test_all_help_shows_advanced_commands(self):
        output = io.StringIO()
        with redirect_stdout(output):
            with self.assertRaises(SystemExit) as caught:
                main(["--all", "--help"])

        self.assertEqual(caught.exception.code, 0)
        help_text = output.getvalue()
        self.assertIn("run-job", help_text)
        self.assertIn("upload-bundle", help_text)
        self.assertIn("show-capabilities", help_text)

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

    def test_cache_status_command_prints_artifact_cache_status(self):
        output = io.StringIO()
        with mock.patch(
            "infergrade.cli.artifact_cache_status",
            return_value={"cache_dir": "/tmp/cache", "total_bytes": 123},
        ) as status_mock:
            with redirect_stdout(output):
                exit_code = main(["cache", "--artifact-cache-dir", "/tmp/cache", "--status"])

        self.assertEqual(exit_code, 0)
        status_mock.assert_called_once_with(cache_dir="/tmp/cache")
        self.assertIn('"total_bytes": 123', output.getvalue())

    def test_cache_prune_partials_command_supports_dry_run(self):
        output = io.StringIO()
        with mock.patch(
            "infergrade.cli.prune_partial_artifacts",
            return_value={"cache_dir": "/tmp/cache", "dry_run": True, "removed_count": 1},
        ) as prune_mock:
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "cache",
                        "--artifact-cache-dir",
                        "/tmp/cache",
                        "--prune-partials",
                        "--dry-run",
                        "--partial-min-age-seconds",
                        "0",
                    ]
                )

        self.assertEqual(exit_code, 0)
        prune_mock.assert_called_once_with(cache_dir="/tmp/cache", dry_run=True, min_age_seconds=0)
        self.assertIn('"removed_count": 1', output.getvalue())

    def test_install_runtime_lists_manifest(self):
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(["install-runtime", "--runtime", "llama.cpp", "--list"])

        self.assertEqual(exit_code, 0)
        self.assertIn('"runtime_family": "llama.cpp"', output.getvalue())

    def test_install_runtime_preview_does_not_execute(self):
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(["install-runtime", "--runtime", "llama.cpp"])

        self.assertEqual(exit_code, 0)
        self.assertIn('"action": "plan"', output.getvalue())

    def test_start_command_invokes_local_worker_loop(self):
        output = io.StringIO()
        with mock.patch(
            "infergrade.cli.run_worker_loop",
            return_value={"worker_id": "worker-test", "processed_jobs": 0, "completed_jobs": 0, "failed_jobs": 0},
        ) as run_loop_mock, mock.patch(
            "infergrade.cli.resolve_runner_execution_mode",
            return_value="local_native",
        ), mock.patch(
            "infergrade.cli.resolve_runner_id",
            return_value="runner-paired",
        ), mock.patch(
            "infergrade.cli.resolve_runner_api_token",
            return_value=None,
        ):
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
            execution_mode="local_native",
            worker_id="runner-paired",
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
            "infergrade.cli.resolve_runner_execution_mode",
            return_value="local_native",
        ), mock.patch(
            "infergrade.cli.resolve_runner_id",
            return_value="runner-saved",
        ), mock.patch(
            "infergrade.cli.resolve_runner_api_token",
            return_value="qbhr_saved_token",
        ):
            with redirect_stdout(output):
                exit_code = main(["start", "--poll-interval-seconds", "2"])

        self.assertEqual(exit_code, 0)
        run_loop_mock.assert_called_once_with(
            api_url="http://localhost:8000",
            execution_mode="local_native",
            worker_id="runner-saved",
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
        ) as run_job_mock, mock.patch(
            "infergrade.cli.resolve_runner_execution_mode",
            return_value="local_container",
        ), mock.patch(
            "infergrade.cli.resolve_runner_id",
            return_value=None,
        ), mock.patch(
            "infergrade.cli.resolve_runner_api_token",
            return_value=None,
        ):
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

    def test_worker_command_does_not_reuse_paired_local_runner_id_for_cloud_mode(self):
        output = io.StringIO()
        with mock.patch(
            "infergrade.cli.run_worker_loop",
            return_value={"worker_id": "cloud-worker", "processed_jobs": 0, "completed_jobs": 0, "failed_jobs": 0},
        ) as run_loop_mock, mock.patch(
            "infergrade.cli.resolve_runner_execution_mode",
            return_value="local_native",
        ), mock.patch(
            "infergrade.cli.resolve_runner_id",
            return_value="runner-paired",
        ), mock.patch(
            "infergrade.cli.resolve_runner_api_url",
            return_value="http://localhost:8000",
        ), mock.patch(
            "infergrade.cli.resolve_runner_api_token",
            return_value="qbhr_saved_token",
        ):
            with redirect_stdout(output):
                exit_code = main(["worker", "--execution-mode", "cloud_container"])

        self.assertEqual(exit_code, 0)
        run_loop_mock.assert_called_once_with(
            api_url="http://localhost:8000",
            execution_mode="cloud_container",
            worker_id=None,
            run_id=None,
            run_config_id=None,
            provider_id=None,
            instance_type_id=None,
            hostname=None,
            api_token="qbhr_saved_token",
            run_token=None,
            simulate=False,
            poll_interval_seconds=10.0,
            max_jobs=None,
            emit_progress=mock.ANY,
        )

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
        ) as save_mock, mock.patch(
            "infergrade.cli.preferred_local_execution_mode",
            return_value="local_native",
        ), mock.patch(
            "infergrade.cli.capture_environment",
            return_value={"hardware_class": "apple_silicon"},
        ):
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
            execution_mode="local_native",
            environment={"hardware_class": "apple_silicon"},
        )
        save_mock.assert_called_once_with(response["runner_profile"])
        self.assertIn('"paired": true', output.getvalue().lower())
        self.assertIn('"next_action": "start_runner"', output.getvalue())
        self.assertIn('"start": "infergrade start"', output.getvalue())

    def test_pair_command_surfaces_hub_pairing_errors(self):
        with mock.patch(
            "infergrade.cli.redeem_runner_pairing",
            side_effect=RuntimeError("runner pairing failed (pair_code_expired): HTTP 410: runner pairing code has expired"),
        ), mock.patch(
            "infergrade.cli.preferred_local_execution_mode",
            return_value="local_native",
        ), mock.patch(
            "infergrade.cli.capture_environment",
            return_value={"hardware_class": "apple_silicon"},
        ):
            with self.assertRaises(SystemExit) as caught:
                main(
                    [
                        "pair",
                        "--api-url",
                        "http://localhost:8000",
                        "--pair-code",
                        "igrp_expired",
                    ]
                )

        self.assertIn("pair_code_expired", str(caught.exception))
        self.assertIn("runner pairing code has expired", str(caught.exception))

    def test_export_support_command_prints_json_when_output_is_omitted(self):
        output = io.StringIO()
        payload = {"export_kind": "infergrade_runner_support_v1", "runner_version": "0.1.0"}
        with mock.patch("infergrade.cli.build_support_export", return_value=payload) as export_mock:
            with redirect_stdout(output):
                exit_code = main(["export-support", "--execution-mode", "local_native"])

        self.assertEqual(exit_code, 0)
        export_mock.assert_called_once_with(run_dir=None, execution_mode="local_native")
        self.assertIn('"export_kind": "infergrade_runner_support_v1"', output.getvalue())

    def test_export_support_command_writes_file_when_output_is_provided(self):
        output = io.StringIO()
        with mock.patch(
            "infergrade.cli.write_support_export",
            return_value="/tmp/infergrade-support.json",
        ) as write_mock:
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "export-support",
                        "--run-dir",
                        "runs/example",
                        "--execution-mode",
                        "local_native",
                        "--output",
                        "/tmp/infergrade-support.json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        write_mock.assert_called_once_with(
            "/tmp/infergrade-support.json",
            run_dir="runs/example",
            execution_mode="local_native",
        )
        self.assertIn('"written": true', output.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
