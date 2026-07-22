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

    def test_ci_rejects_feature_work_on_a_stale_develop_base(self):
        ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("Require develop to contain released main ancestry", ci)
        self.assertIn("github.base_ref == 'develop'", ci)
        self.assertIn('= "already_synced"', ci)


if __name__ == "__main__":
    unittest.main()
