#!/usr/bin/env python3
"""Print the Runner benchmark tier adequacy audit."""

import argparse
import json

from infergrade.benchmark_tier_adequacy import audit_benchmark_tier_adequacy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fail-invalid", action="store_true")
    args = parser.parse_args()
    report = audit_benchmark_tier_adequacy()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if args.fail_invalid and not report["ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
