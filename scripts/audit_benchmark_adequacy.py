#!/usr/bin/env python3
"""Audit catalog-level benchmark coverage and representativeness."""

import argparse
import json
import sys

from infergrade.benchmark_adequacy import audit_benchmark_adequacy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--surface-id")
    parser.add_argument(
        "--as-of-date",
        help="Evaluate refreshable benchmark content age on YYYY-MM-DD (defaults to today).",
    )
    parser.add_argument("--fail-scoped-coverage", action="store_true")
    parser.add_argument("--fail-broad-coverage", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    report = audit_benchmark_adequacy(
        surface_id=args.surface_id,
        as_of_date=args.as_of_date,
    )
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(encoded)
    else:
        sys.stdout.write(encoded)
    if args.fail_scoped_coverage and not report["scoped_claim_coverage_ready"]:
        return 2
    if args.fail_broad_coverage and not report["broad_surface_coverage_ready"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
