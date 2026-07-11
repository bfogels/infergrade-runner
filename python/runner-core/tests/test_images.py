import sys
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade import __version__
from infergrade.images import container_image_identity, docker_image_exists, install_image, install_known_images, local_build_command


class ImageInstallTests(unittest.TestCase):
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

    @mock.patch("infergrade.images._repo_root", return_value="/tmp/infergrade-runner")
    def test_local_build_command_is_available_for_known_images(self, _repo_root_mock):
        command = local_build_command("infergrade-llama-cpp:local")
        self.assertIn("docker build -t infergrade-llama-cpp:local", command)

    @mock.patch("infergrade.images._repo_root", return_value="/tmp/infergrade-runner")
    def test_local_build_command_is_available_for_mmlu_pro_image(self, _repo_root_mock):
        command = local_build_command("infergrade-mmlu-pro:local")
        self.assertIn("containers/capability-mmlu-pro/Dockerfile", command)

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
        self.assertEqual(len(installed), 5)
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
