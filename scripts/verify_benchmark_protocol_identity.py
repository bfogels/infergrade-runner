#!/usr/bin/env python3
"""Fail closed unless a Runner bundle has exact capability protocol identity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from infergrade.protocol_identity import verify_protocol_identity_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Completed bundle directory or individual result JSON")
    parser.add_argument("--output", type=Path, help="Optional path for the JSON verification report")
    args = parser.parse_args()
    try:
        report = verify_protocol_identity_path(args.path, require_complete_coverage=True)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        report = {
            "status": "fail",
            "source": str(args.path),
            "result_document_count": 0,
            "capability_result_count": 0,
            "verified_check_count": 0,
            "results": [],
            "errors": [str(exc)],
        }
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
