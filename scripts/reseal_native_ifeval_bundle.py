#!/usr/bin/env python3
"""Reseal a trusted build after an explicit reviewed packaging transform."""
import argparse
import ast
import hashlib
import json
from pathlib import Path

from prepare_native_ifeval_bundle import MANIFEST, RECEIPT, digest, transform_binary_kind, write_trusted_identity

TRANSFORMS = {'macos_developer_id_signing_v1', 'windows_authenticode', 'linuxdeploy_appimage_v1'}


def _trusted_identity(path):
    tree = ast.parse(Path(path).read_text())
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Assign):
        raise ValueError('trusted packaging identity has unexpected code')
    assignment = tree.body[0]
    if len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name) or assignment.targets[0].id != 'IDENTITY':
        raise ValueError('trusted packaging identity is invalid')
    return ast.literal_eval(assignment.value)


def reseal(bundle, identity_output, transform):
    if transform not in TRANSFORMS:
        raise ValueError('unreviewed native evaluator packaging transform')
    bundle = Path(bundle).resolve()
    receipt_path = bundle / RECEIPT
    raw = receipt_path.read_bytes()
    old = json.loads(raw)
    trusted = _trusted_identity(identity_output)
    previous_sha = hashlib.sha256(raw).hexdigest()
    if (trusted.get('receipt_sha256') != previous_sha or trusted.get('manifest_sha256') != digest(MANIFEST)
            or trusted.get('target') != old.get('target')):
        raise ValueError('pre-transform inventory lacks a trusted package anchor')
    expected_transform = {'aarch64-apple-darwin':'macos_developer_id_signing_v1', 'x86_64-pc-windows-msvc':'windows_authenticode', 'x86_64-unknown-linux-gnu':'linuxdeploy_appimage_v1'}.get(old.get('target'))
    if expected_transform != transform:
        raise ValueError('packaging transform does not match evaluator platform')
    files = old['files']
    if old.get('links'):
        raise ValueError('release evaluator runtime must materialize internal links')
    if any(p.is_symlink() for p in bundle.rglob('*')):
        raise ValueError('packaging transform introduced an evaluator link')
    actual_paths = {p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
    if actual_paths != set(files) | {RECEIPT}:
        raise ValueError('packaging transform added or removed evaluator files')
    refreshed = {}
    for name, expected in files.items():
        path = bundle / name
        if path.is_symlink():
            raise ValueError('packaging transform introduced an evaluator link')
        sha = digest(path)
        if sha != expected:
            original_kind = (old.get('transformable_binaries') or {}).get(name)
            required_kind = {'macos_developer_id_signing_v1':'macho', 'windows_authenticode':'pe',
                             'linuxdeploy_appimage_v1':'elf'}[transform]
            binary = original_kind == required_kind and transform_binary_kind(path, name) == required_kind
            runtime_receipt = name == 'python-runtime/infergrade-python-runtime-receipt.json'
            if not (runtime_receipt or binary):
                raise ValueError('packaging transform changed non-code evaluator assets: ' + name)
        refreshed[name] = sha
    old['files'] = refreshed
    old['packaging_transform'] = {'id': transform, 'previous_receipt_sha256': previous_sha}
    receipt_path.write_text(json.dumps(old, indent=2, sort_keys=True) + '\n')
    write_trusted_identity(bundle, identity_output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True)
    parser.add_argument('--identity-output', required=True)
    parser.add_argument('--transform', required=True, choices=sorted(TRANSFORMS))
    args = parser.parse_args()
    reseal(Path(args.bundle), Path(args.identity_output), args.transform)
    print('native_ifeval_packaging_status=resealed')


if __name__ == '__main__':
    main()
