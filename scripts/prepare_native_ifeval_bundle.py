#!/usr/bin/env python3
"""Build an offline IFEval evaluator from reviewed sources and hash-locked assets.

This is a packaging operation. Benchmark execution never downloads dependencies.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile

from prepare_desktop_python_runtime import prepare_runtime, _target_triple

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'runtime/native_ifeval_bundle.json'
RECEIPT = 'infergrade-native-ifeval-receipt.json'
TARGET_TAGS = {
    'aarch64-apple-darwin': 'macosx_11_0_arm64',
    'x86_64-pc-windows-msvc': 'win_amd64',
    'x86_64-unknown-linux-gnu': 'manylinux2014_x86_64',
}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def safe_relative(name):
    path = PurePosixPath(name)
    if not name or '\\' in name or path.is_absolute() or '..' in path.parts or ':' in name:
        raise ValueError('unsafe evaluator archive path')
    return path


def fetch(asset, cache):
    expected = asset['sha256']
    path = cache / expected
    if path.is_file() and digest(path) == expected and (
        'size_bytes' not in asset or path.stat().st_size == asset['size_bytes']
    ):
        return path
    url = asset['url']
    if not url.startswith('https://'):
        raise ValueError('evaluator asset must use HTTPS')
    partial = cache / (expected + '.partial')
    try:
        subprocess.run(['curl', '--disable', '--fail', '--silent', '--show-error',
                        '--location', '--proto', '=https', '--proto-redir', '=https',
                        '--connect-timeout', '20', '--max-time', '180',
                        '--output', str(partial), url], check=True, capture_output=True)
        if partial.stat().st_size > 20 * 1024 * 1024 or digest(partial) != expected:
            raise ValueError('evaluator asset failed reviewed SHA-256 or size bound')
        if 'size_bytes' in asset and partial.stat().st_size != asset['size_bytes']:
            raise ValueError('evaluator asset failed reviewed size')
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)
    return path


def extract_wheel(archive, destination):
    with zipfile.ZipFile(archive) as wheel:
        members = wheel.infolist()
        if len(members) > 10000 or sum(m.file_size for m in members) > 100 * 1024 * 1024:
            raise ValueError('evaluator wheel exceeds extraction bounds')
        for member in members:
            path = safe_relative(member.filename)
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError('evaluator wheel contains a symlink')
            if member.is_dir():
                continue
            if any(part.endswith('.data') for part in path.parts):
                raise ValueError('unsupported evaluator wheel data layout')
            target = destination.joinpath(*path.parts)
            if target.exists():
                raise ValueError('evaluator wheels overlap')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(wheel.read(member))


def extract_langdetect(archive, destination):
    with tarfile.open(archive, 'r:gz') as source:
        members = source.getmembers()
        if len(members) > 10000 or sum(m.size for m in members) > 20 * 1024 * 1024:
            raise ValueError('language detector exceeds extraction bounds')
        for member in members:
            path = safe_relative(member.name)
            if not path.parts or path.parts[0] != 'langdetect-1.0.9':
                raise ValueError('unexpected language detector source root')
            if not member.isfile() and not member.isdir():
                raise ValueError('language detector contains a link or special file')
            if not member.isfile() or len(path.parts) < 2:
                continue
            # This release has a py2 wheel. Copy its reviewed pure-Python sdist;
            # never run setup.py or install into the builder user environment.
            relative = PurePosixPath(*path.parts[1:])
            if relative.parts[0] not in ('langdetect', 'langdetect.egg-info') and str(relative) not in ('LICENSE', 'NOTICE'):
                continue
            target = destination / (str(relative) if relative.parts[0] in ('langdetect', 'langdetect.egg-info') else 'langdetect-notices/' + str(relative))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.extractfile(member).read())


def select_asset(package, target):
    files = package['files']
    if any(item['filename'].startswith('langdetect-') for item in files):
        return next(item for item in files if item['filename'].endswith('.tar.gz'))
    tag = TARGET_TAGS[target]
    matches = [item for item in files if 'none-any.whl' in item['filename'] or tag in item['filename']]
    if len(matches) != 1:
        raise ValueError('no unique reviewed evaluator package for target')
    return matches[0]


def transform_binary_kind(path, relative):
    """Classify only original reviewed executable/shared-library bytes."""
    relative = PurePosixPath(relative)
    if relative.suffix.lower() in ('.py', '.pyc', '.json', '.jsonl', '.txt', '.pickle', '.tab', '.pem'):
        return None
    eligible_name = (relative.suffix.lower() in ('.exe', '.dll', '.pyd', '.so', '.dylib')
                     or re.fullmatch(r'.+\.so(?:\.[0-9]+)+', relative.name) is not None) or (
        relative.parts[:2] == ('python-runtime', 'bin') and relative.name.startswith('python'))
    if not eligible_name:
        return None
    with Path(path).open('rb') as stream:
        magic = stream.read(4)
    if magic == b'\x7fELF':
        return 'elf'
    if magic in (b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe'):
        return 'macho'
    if magic[:2] == b'MZ':
        return 'pe'
    return None


def prepare(output, target, cache):
    if target not in TARGET_TAGS:
        raise ValueError('native IFEval target is not reviewed')
    if output.exists():
        raise ValueError('output already exists; choose a new staging directory')
    raw = MANIFEST.read_bytes()
    manifest = json.loads(raw)
    cache.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ifeval-package-', dir=output.parent) as temporary:
        bundle = Path(temporary) / 'bundle'
        bundle.mkdir()
        prepare_runtime(ROOT / 'runtime/desktop_python_runtime.json', target,
                        bundle / 'python-runtime', cache / 'python')
        # Headless release extraction rejects links. Materialize reviewed
        # internal runtime links as regular files/directories before sealing.
        flattened = bundle / 'python-runtime-flat'
        shutil.copytree(bundle / 'python-runtime', flattened, symlinks=False)
        shutil.rmtree(bundle / 'python-runtime')
        os.replace(flattened, bundle / 'python-runtime')
        dependencies = bundle / 'dependencies'
        dependencies.mkdir()
        for name, package in manifest['packages'].items():
            if name == 'colorama' and target != 'x86_64-pc-windows-msvc':
                continue
            asset = select_asset(package, target)
            archive = fetch(asset, cache)
            if name == 'langdetect':
                extract_langdetect(archive, dependencies)
            else:
                extract_wheel(archive, dependencies)
        for name, expected in manifest['source_files'].items():
            relative = safe_relative(name)
            source = ROOT.joinpath(*relative.parts)
            if digest(source) != expected:
                raise ValueError('vendored evaluator source differs from reviewed manifest')
            target_path = bundle / ('source/' + (str(relative)[12:] if str(relative).startswith('third_party/') else str(relative)))
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target_path)
        dataset = fetch(manifest['dataset'], cache)
        dataset_path = bundle / 'source/instruction_following_eval/data/input_data.jsonl'
        dataset_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dataset, dataset_path)
        for asset in manifest['nltk_archives']:
            archive = fetch(asset, cache)
            with zipfile.ZipFile(archive) as tokens:
                for name, expected in manifest['nltk_resources'].items():
                    member_name = name[len('tokenizers/'):]
                    if member_name not in tokens.namelist():
                        continue
                    if tokens.getinfo(member_name).file_size > 8 * 1024 * 1024:
                        raise ValueError('tokenizer resource exceeds decompression bound')
                    data = tokens.read(member_name)
                    if hashlib.sha256(data).hexdigest() != expected:
                        raise ValueError('tokenizer differs from reviewed English resource')
                    destination = bundle / 'nltk_data' / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(data)
        for name in manifest['nltk_resources']:
            if not (bundle / 'nltk_data' / name).is_file():
                raise ValueError('required English tokenizer resource is missing')
        # The loader is part of the receipt too. Native execution supplies no
        # user site-packages, PYTHONPATH, credential environment or downloader.
        shutil.copyfile(ROOT / 'runtime/native_ifeval_bootstrap.py', bundle / 'bootstrap.py')
        shutil.copyfile(MANIFEST, bundle / 'manifest.json')
        files = {}
        links = {}
        transformable = {}
        for path in sorted(bundle.rglob('*')):
            name = path.relative_to(bundle).as_posix()
            if path.is_symlink():
                resolved = path.resolve()
                resolved.relative_to(bundle.resolve())
                links[name] = os.readlink(path)
            elif path.is_file():
                files[name] = digest(path)
                kind = transform_binary_kind(path, name)
                if kind:
                    transformable[name] = kind
        runtime = json.loads((bundle / 'python-runtime/infergrade-python-runtime-receipt.json').read_text())
        receipt = {'schema_version': 'infergrade.native_ifeval_receipt.v1',
                   'protocol_id': manifest['protocol_id'], 'container_parity': manifest['container_parity'],
                   'target': target, 'python_version': manifest['python_version'],
                   'manifest_sha256': hashlib.sha256(raw).hexdigest(),
                   'executable': 'python-runtime/' + runtime['executable'],
                   'files': files, 'links': links, 'transformable_binaries': transformable}
        (bundle / RECEIPT).write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
        if output.exists():
            raise ValueError('output already exists; choose a new staging directory')
        os.replace(bundle, output)
    return output


def write_trusted_identity(bundle, output):
    """Emit into the trusted Runner code tree during package construction.

    The installed bundle cannot supply or override this digest at execution.
    Release signing transforms must reseal before emitting this code anchor.
    """
    receipt = Path(bundle) / RECEIPT
    identity = json.loads(receipt.read_text())
    value = {'target': identity['target'], 'manifest_sha256': identity['manifest_sha256'],
             'receipt_sha256': digest(receipt)}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('# Generated by the trusted release packager.\nIDENTITY = ' + repr(value) + '\n')


def prepare_package_bundle(output, target, cache, identity_output):
    """Always rebuild from reviewed archives; never bless a self-rehashed cache."""
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='native-ifeval-stage-', dir=output.parent) as temporary:
        prepared = Path(temporary) / 'prepared'
        prepare(prepared, target, cache)
        previous = Path(temporary) / 'previous'
        if output.exists():
            os.replace(output, previous)
        try:
            os.replace(prepared, output)
            write_trusted_identity(output, identity_output)
        except BaseException:
            if output.exists():
                shutil.rmtree(output)
            if previous.exists():
                os.replace(previous, output)
            raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--target', default=None)
    parser.add_argument('--replace', action='store_true', help='Atomic trusted package rebuild; requires identity output.')
    parser.add_argument('--identity-output', help='Trusted Runner code-tree identity module; for packaging only.')
    parser.add_argument('--cache-dir', default='~/.cache/infergrade/native-ifeval-build')
    args = parser.parse_args()
    if args.replace:
        if not args.identity_output:
            parser.error('--replace requires --identity-output')
        prepare_package_bundle(Path(args.output), args.target or _target_triple(), Path(args.cache_dir).expanduser(), Path(args.identity_output))
    else:
        prepare(Path(args.output).resolve(), args.target or _target_triple(), Path(args.cache_dir).expanduser())
    if args.identity_output and not args.replace:
        write_trusted_identity(Path(args.output).resolve(), Path(args.identity_output))
    print('native_ifeval_bundle_status=prepared')


if __name__ == '__main__':
    main()
