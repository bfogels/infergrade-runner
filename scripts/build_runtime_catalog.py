#!/usr/bin/env python3
"""Create and sign InferGrade runtime catalog metadata.

The root ceremony is deliberately detached from routine catalog publication:
each root custodian signs an identical public-only payload independently, while
targets, snapshot, and timestamp metadata use separate online-role keys.
"""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


SPEC_VERSION = "infergrade_runtime_catalog_v1"
ROOT_KEY_NAMES = ("root-1", "root-2", "root-3")
KEY_NAMES = ROOT_KEY_NAMES + ("timestamp", "snapshot", "targets")
ONLINE_KEY_NAMES = ("timestamp", "snapshot", "targets")
ED25519_DER_PREFIX = bytes.fromhex("302a300506032b6570032100")
LOWER_HEX = frozenset("0123456789abcdef")


def canonical_bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def require_external_path(repo_root, path):
    repo_root = repo_root.resolve()
    path = path.expanduser().resolve()
    if path == repo_root or repo_root in path.parents:
        raise SystemExit("Refusing to store runtime catalog private keys inside the repository.")
    return path


def create_key(key_name, private_key, public_key):
    if key_name not in KEY_NAMES:
        raise SystemExit("Unknown runtime catalog key: %s" % key_name)
    for path in (private_key, public_key):
        if path.exists():
            raise SystemExit("Refusing to overwrite existing key material: %s" % path)
        path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(private_key.parent, 0o700)
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private_key)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    os.chmod(private_key, 0o600)
    public_key.write_bytes(
        encoded(
            {
                "keyid": key_name,
                "keytype": "ed25519",
                "public_key_hex": public_key_hex(private_key),
            }
        )
    )
    os.chmod(public_key, 0o644)


def public_key_hex(path):
    result = subprocess.run(
        ["openssl", "pkey", "-in", str(path), "-pubout", "-outform", "DER"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if not result.stdout.startswith(ED25519_DER_PREFIX) or len(result.stdout) != 44:
        raise SystemExit("OpenSSL returned an invalid Ed25519 public key for %s" % path)
    return result.stdout[-32:].hex()


def sign_bytes(path, payload):
    with tempfile.NamedTemporaryFile() as source, tempfile.NamedTemporaryFile() as signature:
        source.write(payload)
        source.flush()
        subprocess.run(
            [
                "openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(path),
                "-in", source.name, "-out", signature.name,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        signature.seek(0)
        return signature.read().hex()


def verify_signature(public_key, payload, signature_hex):
    try:
        raw_public = bytes.fromhex(public_key)
        signature = bytes.fromhex(signature_hex)
    except ValueError:
        return False
    if len(raw_public) != 32 or len(signature) != 64:
        return False
    with tempfile.NamedTemporaryFile() as key_file:
        with tempfile.NamedTemporaryFile() as source:
            with tempfile.NamedTemporaryFile() as signature_file:
                key_file.write(ED25519_DER_PREFIX + raw_public)
                key_file.flush()
                source.write(payload)
                source.flush()
                signature_file.write(signature)
                signature_file.flush()
                result = subprocess.run(
                    [
                        "openssl", "pkeyutl", "-verify", "-rawin", "-pubin",
                        "-keyform", "DER", "-inkey", key_file.name, "-in",
                        source.name, "-sigfile", signature_file.name,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
    return result.returncode == 0


def load_public_key(path, expected_name=None):
    value = json.loads(path.read_text(encoding="utf-8"))
    name = value.get("keyid")
    if expected_name and name != expected_name:
        raise SystemExit(
            "Public key %s identifies %r, expected %r" % (path, name, expected_name)
        )
    if name not in KEY_NAMES or value.get("keytype") != "ed25519":
        raise SystemExit("Invalid runtime catalog public-key descriptor: %s" % path)
    key_hex = value.get("public_key_hex", "")
    if len(key_hex) != 64 or any(character not in LOWER_HEX for character in key_hex):
        raise SystemExit("Invalid Ed25519 public key in %s" % path)
    return name, {"keytype": "ed25519", "public_key_hex": key_hex}


def prepare_root(source_path, public_key_paths, output):
    source = json.loads(source_path.read_text(encoding="utf-8"))
    keys = {}
    for path in public_key_paths:
        name, value = load_public_key(path)
        if name in keys:
            raise SystemExit("Duplicate public key descriptor: %s" % name)
        keys[name] = value
    missing = sorted(set(KEY_NAMES) - set(keys))
    if missing:
        raise SystemExit("Missing public key descriptors: %s" % ", ".join(missing))
    public_values = [value["public_key_hex"] for value in keys.values()]
    if len(set(public_values)) != len(public_values):
        raise SystemExit("Runtime catalog roles must use distinct public keys.")
    signed = {
        "_type": "root",
        "spec_version": SPEC_VERSION,
        "version": source["versions"]["root"],
        "expires_unix": source["expires_unix"]["root"],
        "keys": keys,
        "roles": {
            "root": {"keyids": list(ROOT_KEY_NAMES), "threshold": 2},
            "timestamp": {"keyids": ["timestamp"], "threshold": 1},
            "snapshot": {"keyids": ["snapshot"], "threshold": 1},
            "targets": {"keyids": ["targets"], "threshold": 1},
        },
        "publisher_policies": source["publisher_policies"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encoded(signed))


def sign_root(payload_path, key_name, private_key, output):
    if key_name not in ROOT_KEY_NAMES:
        raise SystemExit("Only a configured root key may sign a root payload.")
    signed = json.loads(payload_path.read_text(encoding="utf-8"))
    expected = signed["keys"][key_name]["public_key_hex"]
    if public_key_hex(private_key) != expected:
        raise SystemExit("Private key does not match %s in the root payload." % key_name)
    payload = canonical_bytes(signed)
    value = {
        "keyid": key_name,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "sig_hex": sign_bytes(private_key, payload),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encoded(value))


def verify_root(root):
    signed = root.get("signed", {})
    if signed.get("_type") != "root" or signed.get("spec_version") != SPEC_VERSION:
        raise SystemExit("Invalid runtime catalog root payload.")
    keys = signed.get("keys", {})
    if set(keys) != set(KEY_NAMES):
        raise SystemExit("Runtime catalog root must contain the exact configured key set.")
    public_values = []
    for keyid in KEY_NAMES:
        key = keys.get(keyid, {})
        key_hex = key.get("public_key_hex", "")
        if (
            key.get("keytype") != "ed25519"
            or len(key_hex) != 64
            or any(character not in LOWER_HEX for character in key_hex)
        ):
            raise SystemExit("Runtime catalog root contains an invalid key: %s" % keyid)
        public_values.append(key_hex)
    if len(set(public_values)) != len(public_values):
        raise SystemExit("Runtime catalog root roles must use distinct public keys.")
    roles = signed.get("roles", {})
    expected_roles = {
        "root": {"keyids": list(ROOT_KEY_NAMES), "threshold": 2},
        "timestamp": {"keyids": ["timestamp"], "threshold": 1},
        "snapshot": {"keyids": ["snapshot"], "threshold": 1},
        "targets": {"keyids": ["targets"], "threshold": 1},
    }
    if roles != expected_roles:
        raise SystemExit("Runtime catalog root must use the exact configured role policy.")
    keyids = roles["root"]["keyids"]
    threshold = roles["root"]["threshold"]
    payload = canonical_bytes(signed)
    valid = set()
    for signature in root.get("signatures", []):
        keyid = signature.get("keyid")
        key = keys.get(keyid, {})
        if keyid in keyids and verify_signature(
            key.get("public_key_hex", ""), payload, signature.get("sig_hex", "")
        ):
            valid.add(keyid)
    if len(valid) < threshold:
        raise SystemExit("Runtime catalog root signature threshold was not met.")


def assemble_root(payload_path, signature_paths, output):
    signed = json.loads(payload_path.read_text(encoding="utf-8"))
    payload = canonical_bytes(signed)
    payload_digest = hashlib.sha256(payload).hexdigest()
    signatures = []
    seen = set()
    for path in signature_paths:
        signature = json.loads(path.read_text(encoding="utf-8"))
        keyid = signature.get("keyid")
        if keyid in seen:
            raise SystemExit("Duplicate detached root signature: %s" % keyid)
        if signature.get("payload_sha256") != payload_digest:
            raise SystemExit("Detached signature does not match the root payload: %s" % path)
        seen.add(keyid)
        signatures.append({"keyid": keyid, "sig_hex": signature.get("sig_hex")})
    root = {
        "signed": signed,
        "signatures": sorted(signatures, key=lambda item: item["keyid"]),
    }
    verify_root(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encoded(root))


def envelope(signed, signer, private_key):
    return {
        "signed": signed,
        "signatures": [
            {
                "keyid": signer,
                "sig_hex": sign_bytes(private_key, canonical_bytes(signed)),
            }
        ],
    }


def meta_reference(version, payload):
    return {
        "version": version,
        "length": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def build_online(source_path, root_path, key_dir, output_dir, trust_projection=None):
    source = json.loads(source_path.read_text(encoding="utf-8"))
    root = json.loads(root_path.read_text(encoding="utf-8"))
    verify_root(root)
    root_signed = root["signed"]
    if source["versions"]["root"] != root_signed["version"]:
        raise SystemExit("Source root version does not match the assembled root.")
    online_keys = {}
    for name in ONLINE_KEY_NAMES:
        path = key_dir / (name + ".pem")
        if not path.is_file():
            raise SystemExit("Missing online signing key: %s" % path)
        if public_key_hex(path) != root_signed["keys"][name]["public_key_hex"]:
            raise SystemExit("Online private key does not match root role: %s" % name)
        online_keys[name] = path
    versions = source["versions"]
    expiry = source["expires_unix"]
    signing_environment = source.get("signing_environment", "review_candidate")
    targets = envelope(
        {
            "_type": "targets", "spec_version": SPEC_VERSION, "version": versions["targets"],
            "expires_unix": expiry["targets"], "signing_environment": signing_environment,
            "targets": source["targets"],
        },
        "targets", online_keys["targets"],
    )
    targets_bytes = encoded(targets)
    snapshot = envelope(
        {
            "_type": "snapshot", "spec_version": SPEC_VERSION, "version": versions["snapshot"],
            "expires_unix": expiry["snapshot"],
            "meta": {"targets.json": meta_reference(versions["targets"], targets_bytes)},
        },
        "snapshot", online_keys["snapshot"],
    )
    snapshot_bytes = encoded(snapshot)
    timestamp = envelope(
        {
            "_type": "timestamp", "spec_version": SPEC_VERSION, "version": versions["timestamp"],
            "expires_unix": expiry["timestamp"],
            "meta": {"snapshot.json": meta_reference(versions["snapshot"], snapshot_bytes)},
        },
        "timestamp", online_keys["timestamp"],
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
                    "target_name": name, "runtime_build_id": custom["runtime_build_id"],
                    "content_manifest_sha256": custom["content_manifest_sha256"],
                    "archive_sha256": target["sha256"], "runtime_family": custom["runtime_family"],
                    "runtime_interface": custom["runtime_interface"], "origin": custom["origin"],
                    "maturity": custom["maturity"], "support_tier": custom["support_tier"],
                    "compatibility_status": custom["compatibility_status"],
                    "provenance_strength": custom["provenance_strength"], "publisher": custom["publisher"],
                    "validation_assertions": custom["validation_assertions"],
                    "revoked": bool(custom.get("revoked", False)),
                    "revocation_reason": custom.get("revocation_reason"),
                }
            )
        projection = {
            "catalog_version": "infergrade_runtime_trust_catalog_v1",
            "targets_metadata_version": versions["targets"],
            "targets_metadata_sha256": hashlib.sha256(targets_bytes).hexdigest(),
            "root_key_ids": root_signed["roles"]["root"]["keyids"],
            "signing_environment": signing_environment,
            "targets": projected_targets,
        }
        trust_projection.parent.mkdir(parents=True, exist_ok=True)
        trust_projection.write_bytes(encoded(projection))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init-key", help="create one private key and public descriptor")
    init.add_argument("--key-name", required=True, choices=KEY_NAMES)
    init.add_argument("--private-key", required=True, type=Path)
    init.add_argument("--public-key", required=True, type=Path)
    prepare = subparsers.add_parser("prepare-root", help="create a public-only unsigned root payload")
    prepare.add_argument("--source", required=True, type=Path)
    prepare.add_argument("--public-key", required=True, action="append", type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    sign = subparsers.add_parser("sign-root", help="create one detached root signature")
    sign.add_argument("--payload", required=True, type=Path)
    sign.add_argument("--key-name", required=True, choices=ROOT_KEY_NAMES)
    sign.add_argument("--private-key", required=True, type=Path)
    sign.add_argument("--output", required=True, type=Path)
    assemble = subparsers.add_parser("assemble-root", help="verify and assemble the 2-of-3 root")
    assemble.add_argument("--payload", required=True, type=Path)
    assemble.add_argument("--signature", required=True, action="append", type=Path)
    assemble.add_argument("--output", required=True, type=Path)
    online = subparsers.add_parser(
        "build-online", help="sign routine metadata without root private keys"
    )
    online.add_argument("--source", required=True, type=Path)
    online.add_argument("--root", required=True, type=Path)
    online.add_argument("--key-dir", required=True, type=Path)
    online.add_argument("--output-dir", required=True, type=Path)
    online.add_argument("--trust-projection", type=Path)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    if args.command == "init-key":
        private_key = require_external_path(repo_root, args.private_key)
        create_key(args.key_name, private_key, args.public_key.resolve())
    elif args.command == "prepare-root":
        prepare_root(args.source, args.public_key, args.output)
    elif args.command == "sign-root":
        sign_root(
            args.payload,
            args.key_name,
            require_external_path(repo_root, args.private_key),
            args.output,
        )
    elif args.command == "assemble-root":
        assemble_root(args.payload, args.signature, args.output)
    elif args.command == "build-online":
        build_online(
            args.source, args.root, require_external_path(repo_root, args.key_dir),
            args.output_dir, args.trust_projection,
        )


if __name__ == "__main__":
    main()
