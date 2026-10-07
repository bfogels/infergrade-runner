import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("container_input_digest", ROOT / "scripts" / "container_input_digest.py")
digest_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(digest_module)


class ContainerInputDigestTests(unittest.TestCase):
    def _repo(self, tmp: str) -> Path:
        root = Path(tmp)
        (root / "containers" / "demo").mkdir(parents=True)
        (root / "lib" / "pkg").mkdir(parents=True)
        (root / "containers" / "demo" / "Dockerfile").write_text(
            "FROM python:3.11-slim AS build\n"
            "ARG PIN=abc123\n"
            "# COPY ignored/comment.txt /nowhere\n"
            "COPY containers/demo/runner.py \\\n"
            "     /app/runner.py\n"
            "COPY --chown=1000 lib/pkg /app/pkg\n"
            "FROM build AS final\n"
            "COPY --from=build /app /app\n",
            encoding="utf-8",
        )
        (root / "containers" / "demo" / "runner.py").write_text("print('v1')\n", encoding="utf-8")
        (root / "lib" / "pkg" / "a.py").write_text("A = 1\n", encoding="utf-8")
        (root / "unrelated.txt").write_text("noise\n", encoding="utf-8")
        return root

    def _digest(self, root: Path, **kwargs) -> str:
        return digest_module.input_digest(
            root, "containers/demo/Dockerfile", kwargs.get("platforms", "linux/amd64"), kwargs.get("base", "")
        )

    def test_sources_follow_continuations_and_skip_stage_copies(self):
        with TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            text = (root / "containers/demo/Dockerfile").read_text(encoding="utf-8")
            self.assertEqual(digest_module.copy_sources(text), ["containers/demo/runner.py", "lib/pkg"])
            self.assertEqual(digest_module.base_images(text), ["python:3.11-slim"])

    def test_digest_is_stable_and_ignores_unrelated_files(self):
        with TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            first = self._digest(root)
            (root / "unrelated.txt").write_text("changed\n", encoding="utf-8")
            (root / "lib" / "pkg" / "__pycache__").mkdir()
            (root / "lib" / "pkg" / "__pycache__" / "a.cpython-311.pyc").write_bytes(b"\0")
            self.assertEqual(first, self._digest(root))
            self.assertEqual(self._digest(root, platforms="linux/arm64,linux/amd64"),
                             self._digest(root, platforms="linux/amd64, linux/arm64"))

    def test_every_real_input_changes_the_digest(self):
        with TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            baseline = self._digest(root)
            self.assertNotEqual(baseline, self._digest(root, base="python:3.11-slim=deadbeef;"))
            self.assertNotEqual(baseline, self._digest(root, platforms="linux/amd64,linux/arm64"))
            (root / "lib" / "pkg" / "b.py").write_text("B = 2\n", encoding="utf-8")
            with_new_file = self._digest(root)
            self.assertNotEqual(baseline, with_new_file)
            (root / "containers" / "demo" / "runner.py").write_text("print('v2')\n", encoding="utf-8")
            self.assertNotEqual(with_new_file, self._digest(root))
            dockerfile = root / "containers/demo/Dockerfile"
            before = self._digest(root)
            dockerfile.write_text(dockerfile.read_text(encoding="utf-8").replace("abc123", "def456"), encoding="utf-8")
            self.assertNotEqual(before, self._digest(root))

    def test_missing_copy_source_fails_closed(self):
        with TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            (root / "containers" / "demo" / "runner.py").unlink()
            with self.assertRaises(FileNotFoundError):
                self._digest(root)

    def test_every_repository_dockerfile_is_fingerprintable(self):
        for dockerfile in sorted((ROOT / "containers").glob("*/Dockerfile")):
            with self.subTest(dockerfile=dockerfile.parent.name):
                value = digest_module.input_digest(ROOT, dockerfile.relative_to(ROOT).as_posix(), "linux/amd64")
                self.assertRegex(value, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
