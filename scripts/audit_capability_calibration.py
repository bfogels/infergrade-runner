#!/usr/bin/env python3
"""Audit capability-score headroom from result or summary JSON artifacts."""

import argparse
import json
import sys

from infergrade.capability_calibration import (
    audit_capability_observations,
    extract_calibration_observations,
    load_json_documents,
    policy_for_score_version,
    policy_for_benchmark_id,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", help="JSON files or directories to scan")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--score-version")
    target.add_argument("--benchmark-id")
    parser.add_argument("--output")
    parser.add_argument("--fail-unready", action="store_true")
    args = parser.parse_args()
    observations = extract_calibration_observations(
        load_json_documents(args.paths),
        score_version=args.score_version,
        benchmark_id=args.benchmark_id,
    )
    target_id = args.score_version or next(
        (item.get("score_version") for item in observations if item.get("benchmark_id") == args.benchmark_id),
        "benchmark:%s:unknown" % args.benchmark_id,
    )
    report = audit_capability_observations(
        observations,
        target_id,
        policy=(
            policy_for_score_version(args.score_version)
            if args.score_version
            else policy_for_benchmark_id(args.benchmark_id)
        ),
    )
    if args.benchmark_id:
        report["benchmark_id"] = args.benchmark_id
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(encoded)
    else:
        sys.stdout.write(encoded)
    return 2 if args.fail_unready and not report["headline_ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
