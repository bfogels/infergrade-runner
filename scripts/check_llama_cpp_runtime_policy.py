#!/usr/bin/env python3
"""Validate llama.cpp pins and report upstream release drift.

The default check is offline and fails only when the Runner-owned pin inventory
does not match source. Supplying a GitHub latest-release response adds advisory
freshness information. A newer upstream release is never treated as a supported
runtime by this script.
"""

import argparse
import datetime as dt
import json
import pathlib
import sys
from typing import Any, Dict, List, Optional


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "runtime" / "llama_cpp_release_policy.json"
EXPECTED_ARCHIVE_PLATFORMS = {"macos-arm64", "ubuntu-x64", "windows-cpu-x64"}


def _parse_timestamp(value: str) -> dt.datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def load_json(path: pathlib.Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def validate_policy(policy: Dict[str, Any], root: pathlib.Path = ROOT) -> List[str]:
    failures: List[str] = []
    if policy.get("schema_version") != 1:
        failures.append("policy schema_version must be 1")
    pins = policy.get("pins")
    if not isinstance(pins, list) or not pins:
        failures.append("policy pins must be a non-empty list")
        return failures

    seen_ids = set()
    for pin in pins:
        pin_id = str(pin.get("id") or "")
        value = str(pin.get("value") or "")
        if not pin_id or pin_id in seen_ids:
            failures.append(f"pin id is missing or duplicated: {pin_id!r}")
        seen_ids.add(pin_id)
        if not value:
            failures.append(f"{pin_id}: pin value is missing")
        if pin.get("kind") == "commit" and (
            len(value) != 40 or not all(character in "0123456789abcdefABCDEF" for character in value)
        ):
            failures.append(f"{pin_id}: commit pins must use the full 40-character hexadecimal SHA")
        try:
            _parse_timestamp(str(pin.get("upstream_published_at") or ""))
        except (TypeError, ValueError):
            failures.append(f"{pin_id}: upstream_published_at is invalid")
        review_receipt = pin.get("review_receipt")
        if review_receipt:
            receipt_relative = pathlib.Path(str(review_receipt))
            receipt_path = root / receipt_relative
            if receipt_relative.is_absolute() or ".." in receipt_relative.parts:
                failures.append(f"{pin_id}: unsafe review receipt path {receipt_relative}")
            elif not receipt_path.is_file():
                failures.append(f"{pin_id}: review receipt is missing: {receipt_relative}")
            else:
                try:
                    receipt = load_json(receipt_path)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    failures.append(f"{pin_id}: review receipt is invalid: {exc}")
                else:
                    upstream = receipt.get("upstream")
                    if not isinstance(upstream, dict) or upstream.get("release") != value:
                        failures.append(f"{pin_id}: review receipt release does not match pin {value}")
                    artifacts = receipt.get("artifacts")
                    if not isinstance(artifacts, list) or not artifacts:
                        failures.append(f"{pin_id}: review receipt artifacts must be a non-empty list")
                    else:
                        for artifact in artifacts:
                            if not isinstance(artifact, dict):
                                failures.append(f"{pin_id}: review receipt artifact must be an object")
                                continue
                            expected = str(artifact.get("github_asset_sha256") or "")
                            observed = str(artifact.get("downloaded_sha256") or "")
                            if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
                                failures.append(f"{pin_id}: review receipt has an invalid GitHub asset digest")
                            if observed != expected:
                                failures.append(f"{pin_id}: downloaded artifact digest does not match GitHub metadata")
                            members = artifact.get("members")
                            required = artifact.get("required_members")
                            if not isinstance(members, list) or len(members) != artifact.get("member_count"):
                                failures.append(f"{pin_id}: review receipt member inventory is incomplete")
                            if (
                                not isinstance(required, list)
                                or not all(isinstance(item, str) for item in required)
                                or not isinstance(members, list)
                                or not all(isinstance(item, str) for item in members)
                                or not set(required).issubset(set(members))
                            ):
                                failures.append(f"{pin_id}: review receipt is missing required archive members")
        locations = pin.get("locations")
        if not isinstance(locations, list) or not locations:
            failures.append(f"{pin_id}: locations must be a non-empty list")
            continue
        for location in locations:
            relative = pathlib.Path(str(location.get("path") or ""))
            needle = str(location.get("needle") or "")
            if relative.is_absolute() or ".." in relative.parts:
                failures.append(f"{pin_id}: unsafe source path {relative}")
                continue
            source_path = root / relative
            if not source_path.is_file():
                failures.append(f"{pin_id}: source path is missing: {relative}")
                continue
            if not needle:
                failures.append(f"{pin_id}: empty source needle for {relative}")
                continue
            if needle not in source_path.read_text(encoding="utf-8"):
                failures.append(f"{pin_id}: source pin does not match {relative}: {needle!r}")
    return failures


def build_report(
    policy: Dict[str, Any],
    latest_release: Optional[Dict[str, Any]] = None,
    now: Optional[dt.datetime] = None,
    archive_receipts: Optional[List[Dict[str, Any]]] = None,
    model_canary_receipts: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    now_utc = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    review_after_days = int(policy["intake"]["stable_pin_review_after_days"])
    latest_tag = str((latest_release or {}).get("tag_name") or "") or None
    latest_published_at = str((latest_release or {}).get("published_at") or "") or None
    latest_url = str((latest_release or {}).get("html_url") or "") or None
    pins = []
    for pin in policy["pins"]:
        published = _parse_timestamp(pin["upstream_published_at"])
        age_days = max(0, (now_utc - published).days)
        pins.append(
            {
                "id": pin["id"],
                "channel": pin["channel"],
                "kind": pin["kind"],
                "value": pin["value"],
                "upstream_published_at": pin["upstream_published_at"],
                "age_days": age_days,
                "review_due": pin["channel"] == "infergrade_stable" and age_days >= review_after_days,
                "matches_latest_release": pin["kind"] == "release_tag" and pin["value"] == latest_tag,
            }
        )
    receipt_rows = validate_candidate_archive_receipts(latest_release, archive_receipts or [])
    canary_rows = validate_model_canary_receipts(latest_release, model_canary_receipts or [])
    return {
        "report_version": 1,
        "generated_at": now_utc.isoformat().replace("+00:00", "Z"),
        "policy_version": policy["policy_version"],
        "upstream": {
            "repository": policy["upstream"]["repository"],
            "latest_release_tag": latest_tag,
            "latest_release_published_at": latest_published_at,
            "latest_release_url": latest_url,
        },
        "candidate_available": bool(latest_tag) and not any(item["matches_latest_release"] for item in pins),
        "stable_promotion_automatic": bool(policy["intake"]["automatic_stable_promotion"]),
        "runner_release_required": bool(policy["intake"]["runner_release_required"]),
        "pins": pins,
        "compatibility_gates": list(policy["compatibility_gates"]),
        "model_canaries": list(policy["model_canaries"]),
        "claim_boundary": policy["intake"]["claim_boundary"],
        "candidate_archive_receipts": receipt_rows,
        "candidate_model_canaries": canary_rows,
        "candidate_archive_coverage": {
            "expected_platforms": sorted(EXPECTED_ARCHIVE_PLATFORMS),
            "verified_platforms": sorted(item["platform"] for item in receipt_rows),
            "all_expected_archives_verified": {
                item["platform"] for item in receipt_rows
            }
            == EXPECTED_ARCHIVE_PLATFORMS,
            "native_version_smoke_platforms": sorted(
                item["platform"] for item in receipt_rows if item["version_smoke"] == "passed"
            ),
            "model_compatibility_verified": False,
            "legacy_control_model_canary_passed": any(
                item["canary_id"] == "legacy_llama_tiny_generation_v1" for item in canary_rows
            ),
            "recent_architecture_model_canary_passed": False,
        },
    }


def validate_candidate_archive_receipts(
    latest_release: Optional[Dict[str, Any]], receipts: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Validate candidate receipts without inflating them into compatibility proof."""
    if not receipts:
        return []
    latest_tag = str((latest_release or {}).get("tag_name") or "")
    if not latest_tag:
        raise ValueError("archive receipts require latest-release metadata")
    rows: List[Dict[str, Any]] = []
    seen_platforms = set()
    for receipt in receipts:
        if receipt.get("receipt_version") != 1 or receipt.get("candidate_only") is not True:
            raise ValueError("archive receipt must be a version-1 candidate-only receipt")
        upstream = receipt.get("upstream")
        if not isinstance(upstream, dict) or upstream.get("release") != latest_tag:
            raise ValueError("archive receipt release does not match the inspected upstream release")
        platform = str(receipt.get("platform") or "")
        if platform not in EXPECTED_ARCHIVE_PLATFORMS:
            raise ValueError(f"archive receipt has unsupported platform: {platform!r}")
        if platform in seen_platforms:
            raise ValueError(f"archive receipt platform is duplicated: {platform}")
        seen_platforms.add(platform)
        artifact = receipt.get("artifact")
        if not isinstance(artifact, dict):
            raise ValueError(f"{platform}: archive receipt artifact is missing")
        expected = str(artifact.get("github_asset_sha256") or "")
        observed = str(artifact.get("downloaded_sha256") or "")
        if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
            raise ValueError(f"{platform}: archive receipt digest is invalid")
        if observed != expected:
            raise ValueError(f"{platform}: downloaded digest does not match GitHub metadata")
        version_smoke = receipt.get("version_smoke")
        status = str(version_smoke.get("status") if isinstance(version_smoke, dict) else "")
        if status not in {"not_run", "passed"}:
            raise ValueError(f"{platform}: version smoke must be not_run or passed")
        rows.append(
            {
                "platform": platform,
                "asset": str(artifact.get("name") or ""),
                "size_bytes": int(artifact.get("size_bytes") or 0),
                "sha256": expected,
                "version_smoke": status,
                "proof_scope": "native_version_smoke" if status == "passed" else "archive_only",
                "model_compatibility": "not_run",
            }
        )
    return sorted(rows, key=lambda item: item["platform"])


def validate_model_canary_receipts(
    latest_release: Optional[Dict[str, Any]], receipts: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    if not receipts:
        return []
    latest_tag = str((latest_release or {}).get("tag_name") or "")
    if not latest_tag:
        raise ValueError("model canary receipts require latest-release metadata")
    rows: List[Dict[str, Any]] = []
    seen_ids = set()
    for receipt in receipts:
        canary_id = str(receipt.get("canary_id") or "")
        if receipt.get("receipt_version") != 1 or receipt.get("candidate_only") is not True:
            raise ValueError("model canary receipt must be a version-1 candidate-only receipt")
        if not canary_id or canary_id in seen_ids:
            raise ValueError(f"model canary id is missing or duplicated: {canary_id!r}")
        seen_ids.add(canary_id)
        runtime = receipt.get("runtime")
        if not isinstance(runtime, dict) or runtime.get("release") != latest_tag:
            raise ValueError("model canary runtime release does not match the inspected upstream release")
        if receipt.get("status") != "passed":
            raise ValueError(f"{canary_id}: model canary status must be passed")
        model = receipt.get("model")
        if not isinstance(model, dict) or model.get("expected_sha256") != model.get(
            "downloaded_sha256"
        ):
            raise ValueError(f"{canary_id}: model digest does not match")
        execution = receipt.get("execution")
        if not isinstance(execution, dict) or execution.get("status") != "passed":
            raise ValueError(f"{canary_id}: model execution did not pass")
        rows.append(
            {
                "canary_id": canary_id,
                "status": "passed",
                "proof_scope": str(receipt.get("proof_scope") or ""),
                "model_compatibility": str(receipt.get("model_compatibility") or ""),
                "model_repository": str(model.get("repository") or ""),
                "model_revision": str(model.get("revision") or ""),
                "claim_boundary": str(receipt.get("claim_boundary") or ""),
            }
        )
    return sorted(rows, key=lambda item: item["canary_id"])


def render_markdown(report: Dict[str, Any]) -> str:
    upstream = report["upstream"]
    lines = [
        "# llama.cpp runtime intake",
        "",
        f"Latest upstream release: `{upstream['latest_release_tag'] or 'not queried'}`",
        f"Candidate available: `{'yes' if report['candidate_available'] else 'no'}`",
        f"Automatic stable promotion: `{'yes' if report['stable_promotion_automatic'] else 'no'}`",
        f"Runner release required for delivery: `{'yes' if report['runner_release_required'] else 'no'}`",
        "",
        "| Lane | Channel | Pin | Age | Review due |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for pin in report["pins"]:
        lines.append(
            f"| {pin['id']} | {pin['channel']} | `{pin['value']}` | {pin['age_days']} days | "
            f"{'yes' if pin['review_due'] else 'no'} |"
        )
    receipts = report.get("candidate_archive_receipts") or []
    if receipts:
        lines.extend(
            [
                "",
                "## Candidate archive proof",
                "",
                "| Platform | Asset | Proof | Model load |",
                "| --- | --- | --- | --- |",
            ]
        )
        for receipt in receipts:
            lines.append(
                f"| {receipt['platform']} | `{receipt['asset']}` | "
                f"{receipt['proof_scope'].replace('_', ' ')} | not run |"
            )
        lines.extend(
            [
                "",
                "> Archive proof verifies identity, bounded extraction, and expected tools. It does not prove GGUF or benchmark compatibility.",
            ]
        )
    canaries = report.get("candidate_model_canaries") or []
    if canaries:
        lines.extend(
            [
                "",
                "## Model canaries",
                "",
                "| Canary | Result | Scope |",
                "| --- | --- | --- |",
            ]
        )
        for canary in canaries:
            lines.append(
                f"| {canary['canary_id']} | {canary['status']} | "
                f"{canary['model_compatibility'].replace('_', ' ')} |"
            )
        lines.extend(
            [
                "",
                "> The automated legacy control catches broad load/generation regressions. Recent architectures and benchmark protocols remain separate gates.",
            ]
        )
    lines.extend(["", f"> {report['claim_boundary']}", ""])
    return "\n".join(lines)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=pathlib.Path, default=DEFAULT_POLICY)
    parser.add_argument(
        "--latest-release-json",
        type=pathlib.Path,
        help="Saved response from the official GitHub latest-release API.",
    )
    parser.add_argument("--report-json", type=pathlib.Path)
    parser.add_argument("--report-markdown", type=pathlib.Path)
    parser.add_argument(
        "--archive-receipt",
        action="append",
        type=pathlib.Path,
        default=[],
        help="Candidate archive receipt to attach to the advisory report. Repeat per platform.",
    )
    parser.add_argument(
        "--model-canary-receipt",
        action="append",
        type=pathlib.Path,
        default=[],
        help="Model canary receipt to attach to the advisory report. Repeat per canary.",
    )
    parser.add_argument(
        "--require-current",
        action="store_true",
        help="Fail when no stable release-tag pin equals the latest release. Intended for experiments, not normal CI.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    policy = load_json(args.policy)
    failures = validate_policy(policy)
    if failures:
        print("llama.cpp runtime policy validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    latest = load_json(args.latest_release_json) if args.latest_release_json else None
    receipts = [load_json(path) for path in args.archive_receipt]
    canary_receipts = [load_json(path) for path in args.model_canary_receipt]
    report = build_report(
        policy,
        latest_release=latest,
        archive_receipts=receipts,
        model_canary_receipts=canary_receipts,
    )
    json_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    markdown = render_markdown(report)
    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(json_text, encoding="utf-8")
    if args.report_markdown:
        args.report_markdown.parent.mkdir(parents=True, exist_ok=True)
        args.report_markdown.write_text(markdown, encoding="utf-8")
    print(markdown)

    if args.require_current and latest and report["candidate_available"]:
        print("No tracked runtime lane matches the latest upstream release.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
