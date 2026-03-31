"""Regression tests for the local listener helper script."""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


class StartLocalListenerScriptTests(unittest.TestCase):
    """Verify the shell helper works with and without extra listener args."""

    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self._tempdir.name)
        self.fake_bin = self.temp_path / "bin"
        self.fake_bin.mkdir()
        self.home = self.temp_path / "home"
        self.home.mkdir()
        self.python_log = self.temp_path / "python.log"
        self.docker_log = self.temp_path / "docker.log"
        self.script_path = Path(__file__).resolve().parents[3] / "scripts" / "start_local_listener.sh"
        self._write_executable(
            self.fake_bin / "python3",
            "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"" + str(self.python_log) + "\"\n",
        )
        self._write_executable(
            self.fake_bin / "docker",
            "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"" + str(self.docker_log) + "\"\n",
        )

    def tearDown(self):
        self._tempdir.cleanup()

    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _run_script(self, *args: str):
        env = os.environ.copy()
        env["PATH"] = str(self.fake_bin) + os.pathsep + env["PATH"]
        env["HOME"] = str(self.home)
        env["INFERGRADE_REBUILD_LISTENER_IMAGE"] = "0"
        return subprocess.run(
            ["bash", str(self.script_path), *args],
            text=True,
            capture_output=True,
            env=env,
            cwd=str(self.script_path.parent.parent),
        )

    def test_runs_without_extra_args(self):
        result = self._run_script("--api-url", "http://example.invalid:8000")
        self.assertEqual(result.returncode, 0, result.stderr)
        docker_args = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("infergrade-runner-core:local start --api-url http://example.invalid:8000", docker_args)

    def test_passes_through_extra_listener_args(self):
        result = self._run_script("--api-url", "http://example.invalid:8000", "--", "--once", "--simulate")
        self.assertEqual(result.returncode, 0, result.stderr)
        docker_args = self.docker_log.read_text(encoding="utf-8")
        self.assertIn("--once --simulate", docker_args)


if __name__ == "__main__":
    unittest.main()
