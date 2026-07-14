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
        try:
            _parse_timestamp(str(pin.get("upstream_published_at") or ""))
        except (TypeError, ValueError):
            failures.append(f"{pin_id}: upstream_published_at is invalid")
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
        "candidate_available": bool(latest_tag) and not any(
            item["channel"] == "infergrade_stable" and item["matches_latest_release"] for item in pins
        ),
        "stable_promotion_automatic": bool(policy["intake"]["automatic_stable_promotion"]),
        "runner_release_required": bool(policy["intake"]["runner_release_required"]),
        "pins": pins,
        "compatibility_gates": list(policy["compatibility_gates"]),
        "model_canaries": list(policy["model_canaries"]),
        "claim_boundary": policy["intake"]["claim_boundary"],
    }


def render_markdown(report: Dict[str, Any]) -> str:
    upstream = report["upstream"]
    lines = [
        "# llama.cpp runtime intake",
        "",
        f"Latest upstream release: `{upstream['latest_release_tag'] or 'not queried'}`",
        f"Candidate available: `{'yes' if report['candidate_available'] else 'no'}`",
        f"Automatic stable promotion: `{'yes' if report['stable_promotion_automatic'] else 'no'}`",
        "",
        "| Lane | Channel | Pin | Age | Review due |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for pin in report["pins"]:
        lines.append(
            f"| {pin['id']} | {pin['channel']} | `{pin['value']}` | {pin['age_days']} days | "
            f"{'yes' if pin['review_due'] else 'no'} |"
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
    report = build_report(policy, latest_release=latest)
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
        print("No stable release-tag lane matches the latest upstream release.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
