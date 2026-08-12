#!/usr/bin/env python3
"""Capture repeatable Runner product-acceptance evidence without overstating hardware proof."""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_INVARIANTS = [
    {
        "name": "automatic_runtime_readiness",
        "path": "apps/desktop-runner/index.html",
        "needles": [
            "Automatic (recommended)",
            "Make ready",
            'class="runtime-power-options"',
            "Use selected build",
        ],
    },
    {
        "name": "runtime_repair_and_specialized_recovery",
        "path": "apps/desktop-runner/src/main.js",
        "needles": [
            "inspectRuntimePlan({ reconcileStale: true })",
            "installRequiredCatalogRuntime",
            'invoke("install_required_runtime_catalog_target"',
            'invoke("resume_hub_run"',
            "Runtime installed · Hub run requeued",
            'phase: "Ready to retry"',
        ],
    },
    {
        "name": "truthful_assignment_progress",
        "path": "apps/desktop-runner/src/main.js",
        "needles": [
            "function renderAssignmentStages",
            'artifact: "Preparing model"',
            'capability: "Running capability tasks"',
            'upload: "Publishing result"',
            "in this phase",
        ],
        "forbidden": [
            '`${payload.remaining}${/remaining/i.test(payload.remaining)',
        ],
    },
    {
        "name": "scheduled_runtime_candidate_intake",
        "path": ".github/workflows/llama-cpp-runtime-intake.yml",
        "needles": [
            'cron: "17 9 * * *"',
            'cron: "47 9 * * 0"',
            "Verify all official candidate archives once",
            "Restore archive receipts for this exact release and verifier",
            "Run tiny legacy model-load canary",
            "verify_llama_cpp_model_canary.py",
            "runtime-intake/archive-receipts/macos-arm64.json",
            "receipt_args+=(--archive-receipt",
            "--run-version-smoke",
        ],
        "forbidden": [
            "contents: write",
            "pull-requests: write",
            "issues: write",
        ],
    },
    {
        "name": "cross_platform_package_smoke",
        "path": ".github/workflows/desktop-platform-smoke.yml",
        "needles": [
            "Windows install and launch smoke",
            "Linux install and launch smoke",
            "CI candidate only; not an InferGrade release.",
            "GPU execution was not tested",
        ],
    },
]

COMMANDS = [
    {
        "name": "desktop_dependencies",
        "cwd": "apps/desktop-runner",
        "command": ["npm", "ci"],
    },
    {
        "name": "desktop_ui_contract",
        "cwd": "apps/desktop-runner",
        "command": ["npm", "run", "check"],
    },
    {
        "name": "runtime_policy_and_archive_tests",
        "cwd": ".",
        "command": [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "python/runner-core/tests",
            "-p",
            "test_llama_cpp_*.py",
        ],
    },
]

MANUAL_LANES = [
    {
        "id": "signed_macos_clean_machine_loop",
        "status": "manual_required",
        "evidence": "Install the signed current release on a clean macOS account, pair, run a current GGUF, upload, and open the public Result.",
    },
    {
        "id": "specialized_runtime_model_canaries",
        "status": "manual_required",
        "evidence": "Load and run the exact recent-architecture canaries with the selected immutable runtime; archive, version, and synthetic legacy-control receipts do not satisfy this lane.",
    },
    {
        "id": "windows_nvidia_execution",
        "status": "manual_required",
        "evidence": "Install on physical Windows/NVIDIA hardware, prove CUDA execution with a current model, upload the Result, and inspect the support export.",
    },
    {
        "id": "linux_nvidia_execution",
        "status": "manual_required",
        "evidence": "Install on physical Linux/NVIDIA hardware, prove CUDA execution with a current model, upload the Result, and inspect the support export.",
    },
    {
        "id": "custom_llama_cpp_binary",
        "status": "manual_required",
        "evidence": "Select a user-provided llama-cli, verify that InferGrade preserves its provenance, and recover cleanly if the executable is removed.",
    },
]


def source_checks():
    checks = []
    for invariant in SOURCE_INVARIANTS:
        path = ROOT / invariant["path"]
        source = path.read_text(encoding="utf-8") if path.is_file() else ""
        missing = [needle for needle in invariant["needles"] if needle not in source]
        present_forbidden = [needle for needle in invariant.get("forbidden", []) if needle in source]
        checks.append(
            {
                "name": invariant["name"],
                "path": invariant["path"],
                "status": "pass" if not missing and not present_forbidden else "fail",
                "missing": missing,
                "forbidden_present": present_forbidden,
            }
        )
    return checks


def run_command(entry):
    started = time.time()
    completed = subprocess.run(
        entry["command"],
        cwd=str(ROOT / entry.get("cwd", ".")),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return {
        "name": entry["name"],
        "command": entry["command"],
        "status": "pass" if completed.returncode == 0 else "fail",
        "returncode": completed.returncode,
        "duration_seconds": round(time.time() - started, 2),
        "output_tail": completed.stdout[-4000:],
    }


def git_metadata():
    def git(*args):
        completed = subprocess.run(
            ["git", *args], cwd=str(ROOT), capture_output=True, text=True, check=False
        )
        return completed.stdout.strip() if completed.returncode == 0 else ""

    return {
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "head": git("rev-parse", "HEAD"),
        "status_short": git("status", "--short"),
    }


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="artifacts/product-acceptance/latest.json",
        help="Path for the JSON evidence artifact.",
    )
    parser.add_argument("--skip-commands", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    evidence = {
        "artifact_kind": "infergrade.runner_product_acceptance.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git": git_metadata(),
        "source_invariants": source_checks(),
        "commands": [],
        "manual_lanes": MANUAL_LANES,
        "claim_boundary": (
            "Automated checks cover source contracts, unit tests, archive identity, and package smoke. "
            "They do not prove real model compatibility, GPU acceleration, or a clean-person workflow."
        ),
    }
    if not args.skip_commands:
        evidence["commands"] = [run_command(item) for item in COMMANDS]
    failures = [item for item in evidence["source_invariants"] if item["status"] == "fail"]
    failures.extend(item for item in evidence["commands"] if item["status"] == "fail")
    evidence["autonomous_status"] = "fail" if failures else "pass"
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"runner_product_acceptance_evidence={output}")
    print(f"runner_product_acceptance_status={evidence['autonomous_status']}")
    print(f"manual_lanes={len(evidence['manual_lanes'])}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
