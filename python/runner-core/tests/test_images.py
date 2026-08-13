import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade import __version__
from infergrade.images import container_image_identity, docker_image_exists, install_image, install_known_images, local_build_command


class ImageInstallTests(unittest.TestCase):
    def test_runner_core_image_includes_runner_owned_contract_resources(self):
        dockerfile = (
            Path(__file__).resolve().parents[3] / "containers" / "runner-core" / "Dockerfile"
        ).read_text(encoding="utf-8")

        self.assertIn("COPY python/runner-core/src /app/src", dockerfile)
        self.assertIn("COPY schemas /app/schemas", dockerfile)

    @mock.patch("infergrade.images.subprocess.run", side_effect=FileNotFoundError("docker"))
    def test_docker_image_exists_returns_false_when_docker_cli_is_missing(self, _run_mock):
        self.assertFalse(docker_image_exists("infergrade-llama-cpp:local"))

    @mock.patch("infergrade.images.subprocess.run")
    def test_install_image_reports_present_when_local_image_exists(self, run_mock):
        run_mock.return_value = mock.Mock(returncode=0, stdout="[]", stderr="")
        result = install_image("infergrade-llama-cpp:local", pull_if_missing=False)
        self.assertEqual(result["action"], "present")

    @mock.patch("infergrade.images._repo_root", return_value="/tmp/infergrade-runner")
    @mock.patch("infergrade.images.subprocess.run")
    def test_install_image_builds_local_image_when_missing(self, run_mock, _repo_root_mock):
        run_mock.side_effect = [
            mock.Mock(returncode=1, stdout="", stderr="missing"),
            mock.Mock(returncode=0, stdout="built", stderr=""),
        ]
        result = install_image("infergrade-llama-cpp:local")
        self.assertEqual(result["action"], "built")
        self.assertIn("containers/llama-cpp/Dockerfile", result["dockerfile"])

    @mock.patch("infergrade.images._repo_root", return_value="/tmp/infergrade-runner")
    @mock.patch("infergrade.images.subprocess.run")
    def test_install_image_builds_canonical_versioned_image_from_source(self, run_mock, _repo_root_mock):
        run_mock.side_effect = [
            mock.Mock(returncode=1, stdout="", stderr="missing"),
            mock.Mock(returncode=0, stdout="built", stderr=""),
        ]
        image = "ghcr.io/bfogels/infergrade-mmlu-pro:%s" % __version__
        result = install_image(image)
        self.assertEqual(result, {"image": image, "action": "built", "dockerfile": "/tmp/infergrade-runner/containers/capability-mmlu-pro/Dockerfile"})

    @mock.patch("infergrade.images._repo_root", return_value="/tmp/infergrade-runner")
    @mock.patch("infergrade.images.subprocess.run")
    def test_install_image_can_rebuild_existing_local_image(self, run_mock, _repo_root_mock):
        run_mock.return_value = mock.Mock(returncode=0, stdout="rebuilt", stderr="")
        result = install_image("infergrade-runner-core:local", rebuild=True)
        self.assertEqual(result["action"], "rebuilt")
        self.assertIn("containers/runner-core/Dockerfile", result["dockerfile"])

    @mock.patch("infergrade.images._repo_root", return_value=None)
    @mock.patch("infergrade.images.subprocess.run")
    def test_install_image_gives_helpful_error_for_missing_local_image_without_source(self, run_mock, _repo_root_mock):
        run_mock.side_effect = [
            mock.Mock(returncode=1, stdout="", stderr="missing"),
            mock.Mock(returncode=1, stdout="", stderr="pull denied"),
        ]
        with self.assertRaises(RuntimeError) as exc:
            install_image("infergrade-llama-cpp:local")
        self.assertIn("infergrade install-images --image infergrade-llama-cpp:local", str(exc.exception))

    @mock.patch("infergrade.images._repo_root", return_value=None)
    @mock.patch("infergrade.images.subprocess.run")
    def test_install_image_times_out_with_desktop_recovery_guidance(self, run_mock, _repo_root_mock):
        run_mock.side_effect = [
            mock.Mock(returncode=1, stdout="", stderr="missing"),
            subprocess.TimeoutExpired(["docker", "pull"], 1200),
        ]

        with self.assertRaises(RuntimeError) as exc:
            install_image("ghcr.io/bfogels/infergrade-gpqa:0.3.57", prefer_local_build=False)

        self.assertIn("did not finish downloading", str(exc.exception))
        self.assertIn("Restart Docker Desktop", str(exc.exception))
        self.assertIn("reuse the cached model artifact", str(exc.exception))
        self.assertEqual(run_mock.call_args_list[-1].kwargs["timeout"], 1200)

    @mock.patch("infergrade.images.platform.machine", return_value="arm64")
    @mock.patch("infergrade.images.platform.system", return_value="Darwin")
    @mock.patch("infergrade.images._repo_root", return_value=None)
    @mock.patch("infergrade.images.subprocess.run")
    def test_install_image_retries_amd64_release_on_apple_silicon(
        self,
        run_mock,
        _repo_root_mock,
        _system_mock,
        _machine_mock,
    ):
        run_mock.side_effect = [
            mock.Mock(returncode=1, stdout="", stderr="missing"),
            mock.Mock(
                returncode=1,
                stdout="",
                stderr="no matching manifest for linux/arm64/v8 in the manifest list entries",
            ),
            mock.Mock(
                returncode=0,
                stdout="pulled",
                stderr="",
                args=["docker", "pull", "--platform", "linux/amd64"],
            ),
        ]

        result = install_image(
            "ghcr.io/bfogels/infergrade-evalplus:0.3.45",
            prefer_local_build=False,
        )

        self.assertEqual(result["action"], "pulled")
        self.assertEqual(result["platform"], "linux/amd64")
        self.assertEqual(
            run_mock.call_args_list[-1].args[0],
            [
                "docker",
                "pull",
                "--platform",
                "linux/amd64",
                "ghcr.io/bfogels/infergrade-evalplus:0.3.45",
            ],
        )

    @mock.patch("infergrade.images.platform.machine", return_value="x86_64")
    @mock.patch("infergrade.images.platform.system", return_value="Linux")
    @mock.patch("infergrade.images._repo_root", return_value=None)
    @mock.patch("infergrade.images.subprocess.run")
    def test_install_image_does_not_hide_manifest_failure_on_other_platforms(
        self,
        run_mock,
        _repo_root_mock,
        _system_mock,
        _machine_mock,
    ):
        run_mock.side_effect = [
            mock.Mock(returncode=1, stdout="", stderr="missing"),
            mock.Mock(
                returncode=1,
                stdout="",
                stderr="no matching manifest for linux/arm64/v8 in the manifest list entries",
            ),
        ]

        with self.assertRaisesRegex(RuntimeError, "no matching manifest"):
            install_image(
                "ghcr.io/bfogels/infergrade-evalplus:0.3.45",
                prefer_local_build=False,
            )

        self.assertEqual(len(run_mock.call_args_list), 2)

    @mock.patch("infergrade.images.platform.machine", return_value="arm64")
    @mock.patch("infergrade.images.platform.system", return_value="Darwin")
    @mock.patch("infergrade.images._repo_root", return_value=None)
    @mock.patch("infergrade.images.subprocess.run")
    def test_install_image_does_not_emulate_inference_runtime(
        self,
        run_mock,
        _repo_root_mock,
        _system_mock,
        _machine_mock,
    ):
        run_mock.side_effect = [
            mock.Mock(returncode=1, stdout="", stderr="missing"),
            mock.Mock(
                returncode=1,
                stdout="",
                stderr="no matching manifest for linux/arm64/v8 in the manifest list entries",
            ),
        ]

        with self.assertRaisesRegex(RuntimeError, "no matching manifest"):
            install_image(
                "ghcr.io/bfogels/infergrade-llama-cpp:0.3.45",
                prefer_local_build=False,
            )

        self.assertEqual(len(run_mock.call_args_list), 2)

    @mock.patch("infergrade.images.platform.machine", return_value="x86_64")
    @mock.patch("infergrade.images.platform.system", return_value="Darwin")
    @mock.patch("infergrade.images._repo_root", return_value=None)
    @mock.patch("infergrade.images.subprocess.run")
    def test_install_image_retries_capability_image_under_rosetta(
        self,
        run_mock,
        _repo_root_mock,
        _system_mock,
        _machine_mock,
    ):
        run_mock.side_effect = [
            mock.Mock(returncode=1, stdout="", stderr="missing"),
            mock.Mock(
                returncode=1,
                stdout="",
                stderr="no matching manifest for linux/arm64/v8 in the manifest list entries",
            ),
            mock.Mock(returncode=0, stdout="1\n", stderr=""),
            mock.Mock(returncode=0, stdout="pulled", stderr=""),
        ]

        result = install_image(
            "ghcr.io/bfogels/infergrade-mmlu-pro:0.3.45",
            prefer_local_build=False,
        )

        self.assertEqual(result["platform"], "linux/amd64")
        self.assertEqual(
            run_mock.call_args_list[-1].args[0],
            [
                "docker",
                "pull",
                "--platform",
                "linux/amd64",
                "ghcr.io/bfogels/infergrade-mmlu-pro:0.3.45",
            ],
        )

    @mock.patch("infergrade.images._repo_root", return_value="/tmp/infergrade-runner")
    def test_local_build_command_is_available_for_known_images(self, _repo_root_mock):
        command = local_build_command("infergrade-llama-cpp:local")
        self.assertIn("docker build -t infergrade-llama-cpp:local", command)

    @mock.patch("infergrade.images._repo_root", return_value="/tmp/infergrade-runner")
    def test_local_build_command_is_available_for_mmlu_pro_image(self, _repo_root_mock):
        command = local_build_command("infergrade-mmlu-pro:local")
        self.assertIn("containers/capability-mmlu-pro/Dockerfile", command)

    @mock.patch("infergrade.images._repo_root", return_value="/tmp/infergrade-runner")
    def test_local_build_command_is_available_for_gpqa_image(self, _repo_root_mock):
        command = local_build_command("infergrade-gpqa:local")
        self.assertIn("containers/capability-gpqa/Dockerfile", command)

    @mock.patch("infergrade.images._repo_root", return_value="/tmp/infergrade-runner")
    def test_local_build_command_is_available_for_bfcl_image(self, _repo_root_mock):
        command = local_build_command("infergrade-bfcl:local")
        self.assertIn("containers/capability-bfcl/Dockerfile", command)

    @mock.patch("infergrade.images.install_image")
    def test_install_known_images_includes_runner_core_for_local_runtime_setup(self, install_mock):
        install_mock.side_effect = lambda image, **_kwargs: {"image": image, "action": "present"}
        installed = install_known_images("infergrade-llama-cpp:local")
        self.assertIn("infergrade-runner-core:local", installed)
        self.assertIn("infergrade-llama-cpp:local", installed)
        self.assertEqual(
            [call.args[0] for call in install_mock.call_args_list],
            ["infergrade-runner-core:local", "infergrade-llama-cpp:local"],
        )

    @mock.patch("infergrade.images.install_image")
    def test_install_known_images_passes_rebuild_through(self, install_mock):
        install_mock.side_effect = lambda image, **kwargs: {"image": image, "action": "rebuilt" if kwargs.get("rebuild") else "present"}
        installed = install_known_images("infergrade-runner-core:local", rebuild=True)
        self.assertEqual(installed["infergrade-runner-core:local"]["action"], "rebuilt")
        self.assertTrue(install_mock.call_args.kwargs["rebuild"])

    @mock.patch("infergrade.images.install_image")
    def test_install_known_images_defaults_to_canonical_runner_version(self, install_mock):
        install_mock.side_effect = lambda image, **_kwargs: {"image": image, "action": "present"}
        installed = install_known_images()
        self.assertEqual(len(installed), 8)
        self.assertIn("ghcr.io/bfogels/infergrade-bfcl:" + __version__, installed)
        self.assertTrue(all(image.startswith("ghcr.io/bfogels/") and image.endswith(":" + __version__) for image in installed))
        self.assertTrue(all(call.kwargs["pull_if_missing"] for call in install_mock.call_args_list))

    @mock.patch("infergrade.images.subprocess.run")
    def test_container_image_identity_records_id_and_repo_digest(self, run_mock):
        run_mock.return_value = mock.Mock(
            returncode=0,
            stdout='{"Id":"sha256:abc","RepoDigests":["ghcr.io/bfogels/infergrade-mmlu-pro@sha256:def"]}',
            stderr="",
        )
        identity = container_image_identity("ghcr.io/bfogels/infergrade-mmlu-pro:0.3.11")
        self.assertEqual(identity["container_image_id"], "sha256:abc")
        self.assertEqual(identity["container_repo_digests"], ["ghcr.io/bfogels/infergrade-mmlu-pro@sha256:def"])


if __name__ == "__main__":
    unittest.main()
