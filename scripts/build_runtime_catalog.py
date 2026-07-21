#!/usr/bin/env python3
"""Build role-separated signed runtime metadata with offline PEM keys.

Private keys are never accepted from or written inside the repository. The
script uses the system OpenSSL Ed25519 implementation so the build tool adds no
Python package dependency. Root metadata is 2-of-2 by default; online roles use
separate keys.
"""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

SPEC_VERSION = "infergrade_runtime_catalog_v1"
KEY_NAMES = ("root-1", "root-2", "timestamp", "snapshot", "targets")


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def key_path(key_dir, name):
    return key_dir / (name + ".pem")


def require_external_key_dir(repo_root, key_dir):
    repo_root = repo_root.resolve()
    key_dir = key_dir.expanduser().resolve()
    if key_dir == repo_root or repo_root in key_dir.parents:
        raise SystemExit("Refusing to store runtime catalog private keys inside the repository.")
    return key_dir


def init_keys(key_dir):
    key_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(key_dir, 0o700)
    for name in KEY_NAMES:
        path = key_path(key_dir, name)
        if path.exists():
            raise SystemExit("Refusing to overwrite existing key: %s" % path)
        subprocess.run(
            ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(path)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        os.chmod(path, 0o600)


def public_key_hex(path):
    result = subprocess.run(
        ["openssl", "pkey", "-in", str(path), "-pubout", "-outform", "DER"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if len(result.stdout) < 32:
        raise SystemExit("OpenSSL returned an invalid Ed25519 public key for %s" % path)
    return result.stdout[-32:].hex()


def sign_bytes(path, payload):
    with tempfile.NamedTemporaryFile() as source, tempfile.NamedTemporaryFile() as signature:
        source.write(payload)
        source.flush()
        subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-rawin",
                "-inkey",
                str(path),
                "-in",
                source.name,
                "-out",
                signature.name,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        signature.seek(0)
        return signature.read().hex()


def envelope(signed, signers, key_dir):
    payload = canonical_bytes(signed)
    return {
        "signed": signed,
        "signatures": [
            {"keyid": name, "sig_hex": sign_bytes(key_path(key_dir, name), payload)}
            for name in signers
        ],
    }


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def meta_reference(version, payload):
    return {
        "version": version,
        "length": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def build(source_path, key_dir, output_dir, trust_projection=None):
    source = json.loads(source_path.read_text(encoding="utf-8"))
    for name in KEY_NAMES:
        if not key_path(key_dir, name).is_file():
            raise SystemExit("Missing signing key: %s" % key_path(key_dir, name))
    versions = source["versions"]
    expiry = source["expires_unix"]
    targets = envelope(
        {
            "_type": "targets",
            "spec_version": SPEC_VERSION,
            "version": versions["targets"],
            "expires_unix": expiry["targets"],
            "signing_environment": source.get("signing_environment", "review_candidate"),
            "targets": source["targets"],
        },
        ["targets"],
        key_dir,
    )
    targets_bytes = encoded(targets)
    snapshot = envelope(
        {
            "_type": "snapshot",
            "spec_version": SPEC_VERSION,
            "version": versions["snapshot"],
            "expires_unix": expiry["snapshot"],
            "meta": {"targets.json": meta_reference(versions["targets"], targets_bytes)},
        },
        ["snapshot"],
        key_dir,
    )
    snapshot_bytes = encoded(snapshot)
    timestamp = envelope(
        {
            "_type": "timestamp",
            "spec_version": SPEC_VERSION,
            "version": versions["timestamp"],
            "expires_unix": expiry["timestamp"],
            "meta": {"snapshot.json": meta_reference(versions["snapshot"], snapshot_bytes)},
        },
        ["timestamp"],
        key_dir,
    )
    keys = {
        name: {"keytype": "ed25519", "public_key_hex": public_key_hex(key_path(key_dir, name))}
        for name in KEY_NAMES
    }
    root = envelope(
        {
            "_type": "root",
            "spec_version": SPEC_VERSION,
            "version": versions["root"],
            "expires_unix": expiry["root"],
            "keys": keys,
            "roles": {
                "root": {"keyids": ["root-1", "root-2"], "threshold": 2},
                "timestamp": {"keyids": ["timestamp"], "threshold": 1},
                "snapshot": {"keyids": ["snapshot"], "threshold": 1},
                "targets": {"keyids": ["targets"], "threshold": 1},
            },
            "publisher_policies": source["publisher_policies"],
        },
        ["root-1", "root-2"],
        key_dir,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in (
        ("root.json", root),
        ("timestamp.json", timestamp),
        ("snapshot.json", snapshot),
        ("targets.json", targets),
    ):
        (output_dir / name).write_bytes(encoded(value))
    if trust_projection:
        projected_targets = []
        for name, target in sorted(source["targets"].items()):
            custom = target["custom"]
            projected_targets.append(
                {
                    "target_name": name,
                    "runtime_build_id": custom["runtime_build_id"],
                    "content_manifest_sha256": custom["content_manifest_sha256"],
                    "archive_sha256": target["sha256"],
                    "runtime_family": custom["runtime_family"],
                    "runtime_interface": custom["runtime_interface"],
                    "origin": custom["origin"],
                    "maturity": custom["maturity"],
                    "support_tier": custom["support_tier"],
                    "compatibility_status": custom["compatibility_status"],
                    "provenance_strength": custom["provenance_strength"],
                    "publisher": custom["publisher"],
                    "validation_assertions": custom["validation_assertions"],
                    "revoked": bool(custom.get("revoked", False)),
                    "revocation_reason": custom.get("revocation_reason"),
                }
            )
        projection = {
            "catalog_version": "infergrade_runtime_trust_catalog_v1",
            "targets_metadata_version": versions["targets"],
            "targets_metadata_sha256": hashlib.sha256(targets_bytes).hexdigest(),
            "root_key_ids": ["root-1", "root-2"],
            "signing_environment": source.get("signing_environment", "review_candidate"),
            "targets": projected_targets,
        }
        trust_projection.parent.mkdir(parents=True, exist_ok=True)
        trust_projection.write_bytes(encoded(projection))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-dir", required=True, type=Path)
    parser.add_argument("--init-keys", action="store_true")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--trust-projection", type=Path)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    key_dir = require_external_key_dir(repo_root, args.key_dir)
    if args.init_keys:
        init_keys(key_dir)
        return
    if not args.source or not args.output_dir:
        parser.error("--source and --output-dir are required unless --init-keys is used")
    build(args.source, key_dir, args.output_dir, args.trust_projection)


if __name__ == "__main__":
    main()
