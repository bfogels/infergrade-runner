#!/usr/bin/env python3
"""Check local public-release readiness evidence for InferGrade Runner."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


REQUIRED_FILES = [
    "LICENSE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    ".github/CODEOWNERS",
    ".github/dependabot.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/benchmark_methodology.md",
    ".github/ISSUE_TEMPLATE/security.md",
    "docs/public_release_checklist.md",
    "docs/release_process.md",
    "docs/desktop_runner_distribution.md",
    "docs/third_party_license_audit.md",
    "scripts/verify_desktop_macos_release.sh",
    "scripts/notarize_desktop_dmg.sh",
    "scripts/write_desktop_release_checksums.py",
    "scripts/verify_desktop_release_artifacts.py",
]

SECRET_FILE_PATTERNS = [
    re.compile(r"(^|/)\.env($|\.)"),
    re.compile(r"\.(pem|p12|pfx|mobileprovision|provisionprofile)$", re.IGNORECASE),
    re.compile(r"(^|/)AuthKey_[^/]+\.p8$", re.IGNORECASE),
    re.compile(r"\.(key)$", re.IGNORECASE),
]

SKIPPED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "dist",
    "node_modules",
    "target",
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


def read_text(root: Path, relative_path: str) -> str:
    return (root / relative_path).read_text(encoding="utf-8")


def run_git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()


def repository_metadata(root: Path) -> dict[str, str | None]:
    metadata: dict[str, str | None] = {
        "version": None,
        "commit": None,
        "branch": None,
        "status": None,
    }
    version_path = root / "VERSION"
    if version_path.is_file():
        metadata["version"] = version_path.read_text(encoding="utf-8").strip()
    try:
        metadata["commit"] = run_git(root, "rev-parse", "--short", "HEAD")
        metadata["branch"] = run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
        metadata["status"] = run_git(root, "status", "--short") or "clean"
    except (subprocess.CalledProcessError, FileNotFoundError):
        metadata["status"] = "git unavailable"
    return metadata


def check_required_files(root: Path) -> CheckResult:
    missing = [path for path in REQUIRED_FILES if not (root / path).is_file()]
    if missing:
        return CheckResult("required_files", "fail", "missing: " + ", ".join(missing))
    return CheckResult("required_files", "pass", f"{len(REQUIRED_FILES)} release policy/docs/scripts present")


def check_git_repository_state(root: Path) -> CheckResult:
    try:
        inside = run_git(root, "rev-parse", "--is-inside-work-tree")
        commit = run_git(root, "rev-parse", "--short", "HEAD")
        status_output = run_git(root, "status", "--short")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return CheckResult("git_repository_state", "fail", "git metadata unavailable")
    if inside != "true":
        return CheckResult("git_repository_state", "fail", "not inside a Git work tree")
    if status_output:
        changed = ", ".join(status_output.splitlines()[:5])
        if len(status_output.splitlines()) > 5:
            changed += ", ..."
        return CheckResult("git_repository_state", "fail", "worktree is not clean: " + changed)
    return CheckResult("git_repository_state", "pass", f"clean Git worktree at {commit}")


def check_workflow_posture(root: Path) -> CheckResult:
    workflow_path = ".github/workflows/desktop-runner-release.yml"
    workflow_file = root / workflow_path
    if not workflow_file.is_file():
        return CheckResult("desktop_release_workflow", "fail", f"missing {workflow_path}")
    workflow = workflow_file.read_text(encoding="utf-8")
    required_snippets = [
        "environment: release",
        "Verify signing and notarization inputs",
        "TAURI_SIGNING_PRIVATE_KEY",
        "APPLE_CERTIFICATE",
        "APPLE_API_PRIVATE_KEY",
        "APPLE_NOTARIZATION_MODE",
        "scripts/notarize_desktop_dmg.sh",
        "scripts/verify_desktop_macos_release.sh",
        "scripts/write_desktop_release_checksums.py",
        "target/release/bundle/macos/SHA256SUMS",
        "must not fall back to ad-hoc signing or skip notarization",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in workflow]
    if missing:
        return CheckResult("desktop_release_workflow", "fail", "missing protected-release gates: " + ", ".join(missing))
    return CheckResult("desktop_release_workflow", "pass", "protected macOS release workflow gates are present")


def check_untrusted_workflow_triggers(root: Path) -> CheckResult:
    workflow_dir = root / ".github" / "workflows"
    offenders: list[str] = []
    if workflow_dir.is_dir():
        for workflow in sorted(workflow_dir.glob("*.y*ml")):
            if "pull_request_target" in workflow.read_text(encoding="utf-8"):
                offenders.append(str(workflow.relative_to(root)))
    if offenders:
        return CheckResult("untrusted_workflow_triggers", "fail", "pull_request_target found: " + ", ".join(offenders))
    return CheckResult("untrusted_workflow_triggers", "pass", "no pull_request_target workflows found locally")


def check_secret_filenames(root: Path) -> CheckResult:
    findings: list[str] = []
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIPPED_DIRS]
        current_path = Path(current_root)
        for filename in filenames:
            relative = str((current_path / filename).relative_to(root))
            normalized = relative.replace(os.sep, "/")
            if any(pattern.search(normalized) for pattern in SECRET_FILE_PATTERNS):
                findings.append(normalized)
    if findings:
        return CheckResult("secret_filename_scan", "fail", "suspicious local file(s): " + ", ".join(sorted(findings)))
    return CheckResult("secret_filename_scan", "pass", "no local secret-looking filenames found")


def check_docs_honesty(root: Path) -> CheckResult:
    doc_paths = (
        "docs/public_release_checklist.md",
        "docs/release_process.md",
        "docs/desktop_runner_distribution.md",
    )
    missing_docs = [path for path in doc_paths if not (root / path).is_file()]
    if missing_docs:
        return CheckResult("release_docs_honesty", "fail", "missing docs: " + ", ".join(missing_docs))
    docs = "\n".join(
        read_text(root, path)
        for path in doc_paths
    )
    required_snippets = [
        "Developer ID",
        "notarization",
        "Gatekeeper",
        "Do not ask users to bypass Gatekeeper",
        "does not replace Developer ID signing",
        "Windows and Linux",
        "not supported public installers",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in docs]
    if missing:
        return CheckResult("release_docs_honesty", "fail", "missing release-honesty wording: " + ", ".join(missing))
    return CheckResult("release_docs_honesty", "pass", "release docs separate local checks from public trust gates")


def local_checks(root: Path) -> list[CheckResult]:
    return [
        check_git_repository_state(root),
        check_required_files(root),
        check_workflow_posture(root),
        check_untrusted_workflow_triggers(root),
        check_secret_filenames(root),
        check_docs_honesty(root),
        CheckResult(
            "github_settings",
            "manual",
            "verify release environment restrictions, required reviewers, branch protection, and secret scanning in GitHub",
        ),
        CheckResult(
            "signing_credentials",
            "manual",
            "local readiness check cannot inspect Apple Developer ID, notarization, or updater signing secrets",
        ),
        CheckResult(
            "published_artifacts",
            "manual",
            "after workflow publish, download artifacts and run scripts/verify_desktop_release_artifacts.py",
        ),
    ]


def status(results: list[CheckResult]) -> str:
    if any(result.status == "fail" for result in results):
        return "fail"
    if any(result.status == "manual" for result in results):
        return "manual_required"
    return "pass"


def render_text(payload: dict[str, object]) -> None:
    print(f"public_release_readiness={payload['status']}")
    metadata = payload["repository"]
    assert isinstance(metadata, dict)
    print(f"release_version={metadata.get('version')}")
    print(f"release_branch={metadata.get('branch')}")
    print(f"release_commit={metadata.get('commit')}")
    print(f"release_worktree_status={metadata.get('status')}")
    print("release_evidence_scope=local_repository_checks_only")
    print("release_signing_notarization=manual_github_release_environment_gate")
    for item in payload["checks"]:
        assert isinstance(item, dict)
        print(f"{item['status']}\t{item['name']}\t{item['detail']}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="check_public_release_readiness")
    parser.add_argument(
        "--root",
        default=".",
        help="Runner repository root. Defaults to the current directory.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of stable text lines.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    results = local_checks(root)
    payload = {
        "status": status(results),
        "repository": repository_metadata(root),
        "scope": "local_repository_checks_only",
        "checks": [result.__dict__ for result in results],
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        render_text(payload)
    return 1 if payload["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
