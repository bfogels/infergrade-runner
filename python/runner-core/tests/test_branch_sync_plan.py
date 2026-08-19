import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.branch_sync_plan import branch_sync_mode


class BranchSyncPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)
        self._git("init", "--initial-branch=main")
        self._git("config", "user.email", "tests@infergrade.local")
        self._git("config", "user.name", "InferGrade Tests")
        (self.repo / "state.txt").write_text("base\n", encoding="utf-8")
        self._git("add", "state.txt")
        self._git("commit", "-m", "base")
        self._git("branch", "develop")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        )

    def _commit(self, branch, filename, contents):
        self._git("checkout", branch)
        (self.repo / filename).write_text(contents, encoding="utf-8")
        self._git("add", filename)
        self._git("commit", "-m", "%s change" % branch)

    def test_reports_already_synced_when_develop_contains_main(self):
        self._commit("develop", "develop.txt", "develop\n")
        self.assertEqual(branch_sync_mode(self.repo, "main", "develop"), "already_synced")

    def test_reports_ancestry_pr_when_develop_is_behind_main(self):
        self._commit("main", "main.txt", "release\n")
        self.assertEqual(branch_sync_mode(self.repo, "main", "develop"), "ancestry_pr")

    def test_reports_integration_pr_without_merging_develop_into_main(self):
        self._commit("main", "main.txt", "release\n")
        self._commit("develop", "develop.txt", "new work\n")
        self.assertEqual(branch_sync_mode(self.repo, "main", "develop"), "integration_pr")

    def test_invalid_refs_fail_instead_of_guessing(self):
        with self.assertRaises(RuntimeError):
            branch_sync_mode(self.repo, "missing-main", "develop")


class BranchSyncWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)
        self._git("init", "--initial-branch=main")
        self._git("config", "user.email", "tests@infergrade.local")
        self._git("config", "user.name", "InferGrade Tests")
        (self.repo / "state.txt").write_text("base\n", encoding="utf-8")
        self._git("add", "state.txt")
        self._git("commit", "-m", "base")
        self.base_commit = self._git("rev-parse", "HEAD").stdout.strip()
        self._git("branch", "develop")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _git(self, *args, check=True):
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            check=check,
            capture_output=True,
            text=True,
        )

    def _main_ancestry_status(self):
        return self._git(
            "merge-base",
            "--is-ancestor",
            "origin/main",
            "HEAD",
            check=False,
        ).returncode

    def test_workflow_preserves_long_lived_branches_and_dispatches_protected_checks(self):
        workflow = Path(".github/workflows/sync-main-to-develop.yml").read_text(encoding="utf-8")
        self.assertIn("branches: [main]", workflow)
        self.assertIn("if: github.ref == 'refs/heads/main'", workflow)
        self.assertIn("ref: main", workflow)
        self.assertIn("python3 scripts/branch_sync_plan.py", workflow)
        self.assertIn("git merge --no-ff --no-edit origin/main", workflow)
        self.assertIn("gh workflow run ci.yml", workflow)
        self.assertIn("gh workflow run secret-scan.yml", workflow)
        self.assertIn("gh issue create", workflow)
        self.assertIn("gh pr merge", workflow)
        self.assertNotIn("push origin HEAD:develop", workflow)
        self.assertNotIn("--force", workflow)

    def test_dispatched_sync_checks_are_supported(self):
        ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        secret_scan = Path(".github/workflows/secret-scan.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", ci)
        self.assertIn("workflow_dispatch:", secret_scan)

    def test_ci_requires_prospective_merge_head_to_contain_main(self):
        ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("Require prospective develop merge to contain released main ancestry", ci)
        self.assertIn("github.base_ref == 'develop'", ci)
        self.assertIn(
            "git fetch --no-tags origin +refs/heads/main:refs/remotes/origin/main",
            ci,
        )
        self.assertIn("git merge-base --is-ancestor origin/main HEAD", ci)
        self.assertNotIn("refs/heads/develop:refs/remotes/origin/develop", ci)
        self.assertNotIn("scripts/branch_sync_plan.py", ci)
        self.assertNotIn('= "already_synced"', ci)

    def test_ci_ancestry_check_accepts_sync_merge_and_rejects_stale_feature(self):
        self._git("checkout", "main")
        (self.repo / "release.txt").write_text("released main\n", encoding="utf-8")
        self._git("add", "release.txt")
        self._git("commit", "-m", "release main")
        self._git("update-ref", "refs/remotes/origin/main", "main")

        self._git("checkout", "develop")
        (self.repo / "feature.txt").write_text("develop feature\n", encoding="utf-8")
        self._git("add", "feature.txt")
        self._git("commit", "-m", "develop feature")
        self._git("merge", "--no-ff", "--no-edit", "main")
        self.assertEqual(self._main_ancestry_status(), 0)

        self._git("branch", "stale-feature", self.base_commit)
        self._git("checkout", "stale-feature")
        (self.repo / "stale.txt").write_text("stale feature\n", encoding="utf-8")
        self._git("add", "stale.txt")
        self._git("commit", "-m", "stale feature")
        self.assertEqual(self._main_ancestry_status(), 1)


if __name__ == "__main__":
    unittest.main()
