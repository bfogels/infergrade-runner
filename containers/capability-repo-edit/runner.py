import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Tuple


FIXTURE_PATH = Path(os.environ.get("INFERGRADE_REPOSITORY_EDIT_FIXTURES", "/opt/infergrade/repository-edit/fixtures.json"))
FIXTURE_REVISION = "2026-08-repository-edit-v1"
MAX_PATCH_BYTES = 32768
TEST_TIMEOUT_SECONDS = 10
PATCH_FENCE = re.compile(r"\A\s*```(?:diff|patch)?\s*\n(.*?)\n```\s*\Z", re.DOTALL | re.IGNORECASE)
TEST_RUN_RECEIPT = re.compile(r"Ran\s+(\d+)\s+tests?\s+in\s+[0-9.]+s.*\n\nOK\s*\Z", re.DOTALL)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _load_fixtures(path: Optional[Path] = None) -> List[dict]:
    path = path or FIXTURE_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("fixture_revision") != FIXTURE_REVISION:
        raise ValueError("Repository-edit fixture revision does not match the scorer revision.")
    fixtures = list(payload.get("fixtures") or [])
    if not fixtures:
        raise ValueError("Repository-edit fixture set is empty.")
    task_ids = [str(item.get("task_id") or "") for item in fixtures]
    if len(task_ids) != len(set(task_ids)) or any(not item for item in task_ids):
        raise ValueError("Repository-edit fixture task ids must be non-empty and unique.")
    for fixture in fixtures:
        source_files = set(dict(fixture.get("files") or {}))
        test_files = set(dict(fixture.get("tests") or {}))
        editable_files = set(fixture.get("editable_files") or [])
        all_paths = source_files | test_files
        if not source_files or not test_files or not editable_files:
            raise ValueError("Repository-edit fixtures require source, test, and editable files.")
        if not editable_files.issubset(source_files):
            raise ValueError("Repository-edit editable files must be present in the source tree.")
        if source_files & test_files:
            raise ValueError("Repository-edit source and hidden-test paths must not overlap.")
        if any(_fixture_path_error(value) for value in all_paths):
            raise ValueError("Repository-edit fixture paths must be safe relative POSIX paths.")
        if any(not value.startswith("tests/") for value in test_files):
            raise ValueError("Repository-edit hidden tests must remain under tests/.")
    return fixtures


def _fixture_path_error(value: str) -> bool:
    candidate = str(value or "")
    path = PurePosixPath(candidate)
    return bool(
        not candidate
        or path.is_absolute()
        or "." in path.parts
        or ".." in path.parts
        or "\\" in candidate
    )


def _render_prompt(fixture: dict) -> str:
    rendered_files = []
    for path, content in sorted(dict(fixture["files"]).items()):
        rendered_files.append("FILE: %s\n```python\n%s\n```" % (path, str(content).rstrip()))
    return (
        "You are editing a small Python repository. Fix the described behavior while preserving the public API. "
        "Return only one unified diff using a/ and b/ paths. Do not add prose or Markdown fences. Only edit the "
        "listed editable files; hidden deterministic tests will be run.\n\n"
        "ISSUE:\n%s\n\nEDITABLE FILES: %s\n\n%s"
        % (
            str(fixture["issue"]).strip(),
            ", ".join(str(item) for item in fixture["editable_files"]),
            "\n\n".join(rendered_files),
        )
    )


def prepare(output_dir: str, limit: Optional[int] = None) -> None:
    fixtures = _load_fixtures()
    selected = fixtures[:limit] if limit else fixtures
    cases = [
        {
            "case_id": "repository_edit/%s" % fixture["task_id"],
            "task_id": "repository_edit/%s" % fixture["task_id"],
            "category": fixture["category"],
            "prompt": _render_prompt(fixture),
            "editable_files": list(fixture["editable_files"]),
            "fixture_revision": FIXTURE_REVISION,
        }
        for fixture in selected
    ]
    root = Path(output_dir)
    selection_sha256 = hashlib.sha256(
        "\n".join(sorted(str(item["task_id"]) for item in selected)).encode("utf-8")
    ).hexdigest()
    _write_jsonl(root / "cases.jsonl", cases)
    _write_json(
        root / "benchmark_metadata.json",
        {
            "benchmark_id": "repository_edit_smoke_v1",
            "display_name": "Repository edit diagnostic",
            "case_count": len(cases),
            "fixture_revision": FIXTURE_REVISION,
            "sample_policy": "pinned_fixture_order_v1",
            "selection_digest_algorithm": "sorted_utf8_newline_sha256_v1",
            "selection_sha256": selection_sha256,
            "scoring_policy": "repo_edit_task_success_v1",
        },
    )


def _normalized_patch(completion: str) -> Tuple[Optional[str], Optional[str]]:
    text = str(completion or "").strip()
    fenced = PATCH_FENCE.fullmatch(text)
    if fenced:
        text = fenced.group(1).strip()
    if not text:
        return None, "empty_patch"
    if len(text.encode("utf-8")) > MAX_PATCH_BYTES:
        return None, "patch_too_large"
    if "\x00" in text or "GIT binary patch" in text or "Binary files " in text:
        return None, "binary_patch_not_allowed"
    if not text.startswith("--- a/"):
        return None, "not_unified_diff"
    return text + "\n", None


def _safe_relative_path(value: str) -> Optional[str]:
    if not value.startswith(("a/", "b/")):
        return None
    candidate = value[2:].split("\t", 1)[0].strip()
    path = PurePosixPath(candidate)
    if not candidate or path.is_absolute() or ".." in path.parts or "\\" in candidate:
        return None
    return path.as_posix()


def _validate_patch_paths(patch_text: str, editable_files: List[str]) -> Optional[str]:
    old_paths = []
    new_paths = []
    for line in patch_text.splitlines():
        if line.startswith("--- "):
            old_paths.append(_safe_relative_path(line[4:]))
        elif line.startswith("+++ "):
            new_paths.append(_safe_relative_path(line[4:]))
        elif line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
            return "rename_or_copy_not_allowed"
    if not old_paths or len(old_paths) != len(new_paths):
        return "invalid_file_headers"
    if any(path is None for path in old_paths + new_paths):
        return "unsafe_patch_path"
    allowed = set(editable_files)
    for old_path, new_path in zip(old_paths, new_paths):
        if old_path != new_path or old_path not in allowed:
            return "non_editable_path"
    return None


def _write_tree(root: Path, files: Dict[str, str]) -> None:
    for relative, content in files.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(str(content), encoding="utf-8")


def _drop_to_unprivileged_user() -> None:
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)


def _expected_test_count(workspace: Path) -> int:
    count = 0
    for test_path in sorted((workspace / "tests").rglob("test*.py")):
        tree = ast.parse(test_path.read_text(encoding="utf-8"), filename=str(test_path))
        count += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test")
        )
    return count


def _valid_test_receipt(output: str, expected_count: int) -> bool:
    matched = TEST_RUN_RECEIPT.search(str(output or ""))
    return bool(matched and int(matched.group(1)) == expected_count)


def _score_patch(fixture: dict, completion: str) -> dict:
    patch_text, error = _normalized_patch(completion)
    if error:
        return {"passed": False, "failure_class": "malformed_patch", "failure_detail": error}
    error = _validate_patch_paths(patch_text or "", list(fixture["editable_files"]))
    if error:
        return {"passed": False, "failure_class": "malformed_patch", "failure_detail": error}
    workspace = Path(tempfile.mkdtemp(prefix="infergrade-repo-edit-", dir="/tmp"))
    try:
        _write_tree(workspace, dict(fixture["files"]))
        try:
            applied = subprocess.run(
                ["patch", "-p1", "--batch", "--forward", "--reject-file=-"],
                cwd=workspace,
                input=patch_text,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            return {"passed": False, "failure_class": "patch_timeout"}
        if applied.returncode != 0:
            return {
                "passed": False,
                "failure_class": "patch_apply_failed",
                "failure_detail": (applied.stderr or applied.stdout or "")[-1000:],
            }
        expected_paths = set(dict(fixture["files"]))
        actual_paths = {
            path.relative_to(workspace).as_posix()
            for path in workspace.rglob("*")
            if path.is_file()
        }
        if actual_paths != expected_paths:
            return {"passed": False, "failure_class": "unexpected_file_change"}
        _write_tree(workspace, dict(fixture["tests"]))
        expected_test_count = _expected_test_count(workspace)
        if expected_test_count <= 0:
            return {"passed": False, "failure_class": "test_protocol_failed"}
        for path in workspace.rglob("*"):
            path.chmod(0o555 if path.is_dir() else 0o444)
        workspace.chmod(0o555)
        try:
            tested = subprocess.run(
                [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=TEST_TIMEOUT_SECONDS,
                env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "PYTHONDONTWRITEBYTECODE": "1"},
                preexec_fn=_drop_to_unprivileged_user,
            )
        except subprocess.TimeoutExpired:
            return {"passed": False, "failure_class": "test_timeout"}
        if tested.returncode != 0:
            return {
                "passed": False,
                "failure_class": "test_failed",
                "failure_detail": (tested.stderr or tested.stdout or "")[-2000:],
            }
        test_output = "\n".join(item for item in (tested.stdout, tested.stderr) if item)
        if not _valid_test_receipt(test_output, expected_test_count):
            return {"passed": False, "failure_class": "test_protocol_failed"}
        return {"passed": True, "failure_class": None}
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def evaluate(output_dir: str) -> None:
    root = Path(output_dir)
    fixtures = {"repository_edit/%s" % item["task_id"]: item for item in _load_fixtures()}
    cases = {str(item["task_id"]): item for item in _read_jsonl(root / "cases.jsonl")}
    predictions = _read_jsonl(root / "predictions.jsonl")
    results = []
    counts = {
        "passed_count": 0,
        "malformed_patch_count": 0,
        "patch_apply_failure_count": 0,
        "test_failure_count": 0,
        "timeout_count": 0,
    }
    seen = set()
    for prediction in predictions:
        if str(prediction.get("generation_status") or "completed") != "completed":
            continue
        task_id = str(prediction.get("task_id") or prediction.get("case_id") or "")
        if task_id in seen or task_id not in cases or task_id not in fixtures:
            raise ValueError("Prediction contains an unknown or duplicate repository-edit task: %s" % task_id)
        seen.add(task_id)
        scored = _score_patch(fixtures[task_id], str(prediction.get("completion") or ""))
        failure_class = scored.get("failure_class")
        counts["passed_count"] += int(bool(scored["passed"]))
        if failure_class == "malformed_patch":
            counts["malformed_patch_count"] += 1
        elif failure_class in {"patch_apply_failed", "unexpected_file_change"}:
            counts["patch_apply_failure_count"] += 1
        elif failure_class in {"test_failed", "test_protocol_failed"}:
            counts["test_failure_count"] += 1
        elif failure_class in {"patch_timeout", "test_timeout"}:
            counts["timeout_count"] += 1
        results.append(
            {
                "case_id": task_id,
                "task_id": task_id,
                "category": fixtures[task_id]["category"],
                "score": 1.0 if scored["passed"] else 0.0,
                "passed": bool(scored["passed"]),
                "state": "scored",
                "error_class": failure_class,
            }
        )
    total = len(results)
    success_rate = round(counts["passed_count"] / float(total), 6) if total else None
    _write_json(
        root / "summary.json",
        {
            "benchmark_id": "repository_edit_smoke_v1",
            "display_name": "Repository edit diagnostic",
            "status": "completed" if total else "failed",
            "primary_metric": {"name": "task_success_rate", "value": success_rate},
            "metrics": {"task_success_rate": success_rate, "total_count": total, **counts},
            "case_results": results,
            "scoring_policy": "repo_edit_task_success_v1",
            "fixture_revision": FIXTURE_REVISION,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--output-dir", required=True)
    prepare_parser.add_argument("--limit", type=int)
    evaluate_parser = commands.add_parser("evaluate")
    evaluate_parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    if args.command == "prepare":
        prepare(args.output_dir, limit=args.limit)
    else:
        evaluate(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
