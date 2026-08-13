#!/usr/bin/env python3
"""Join catalog adequacy and corpus headroom into one readiness audit."""

import argparse
import json
import sys

from infergrade.benchmark_readiness import audit_benchmark_readiness
from infergrade.capability_calibration import load_json_documents


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", help="JSON files or directories to scan")
    parser.add_argument("--surface-id")
    parser.add_argument("--output")
    parser.add_argument("--fail-scoped-ready", action="store_true")
    parser.add_argument("--fail-broad-ready", action="store_true")
    args = parser.parse_args()
    documents = load_json_documents(args.paths)
    report = audit_benchmark_readiness(
        documents,
        surface_id=args.surface_id,
    )
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(encoded)
    else:
        sys.stdout.write(encoded)
    if args.fail_broad_ready and not report["broad_surface_ready"]:
        return 2
    if args.fail_scoped_ready and not report["scoped_claim_ready"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
