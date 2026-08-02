#!/usr/bin/env python3
"""Materialize the pinned, self-contained Python runtime used by Desktop Runner."""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import warnings
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "runtime" / "desktop_python_runtime.json"
DEFAULT_OUTPUT = ROOT / "apps" / "desktop-runner" / "src-tauri" / "desktop-python"
RECEIPT_NAME = "infergrade-python-runtime-receipt.json"


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _target_triple():
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin" and machine in {"arm64", "aarch64"}:
        return "aarch64-apple-darwin"
    if system == "windows" and machine in {"amd64", "x86_64"}:
        return "x86_64-pc-windows-msvc"
    if system == "linux" and machine in {"amd64", "x86_64"}:
        return "x86_64-unknown-linux-gnu"
    raise ValueError("no reviewed Desktop Python runtime is available for %s/%s" % (system, machine))


def _load_manifest(path):
    raw = Path(path).read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("schema_version") != "infergrade.desktop_python_runtime.v1":
        raise ValueError("unsupported Desktop Python runtime manifest")
    return payload, hashlib.sha256(raw).hexdigest()


def _safe_member(member):
    if "\\" in member.name:
        raise ValueError("runtime archive member uses a non-POSIX path: %s" % member.name)
    path = PurePosixPath(member.name)
    if path.is_absolute() or not path.parts or path.parts[0] != "python" or ".." in path.parts:
        raise ValueError("unsafe runtime archive member: %s" % member.name)
    if member.ischr() or member.isblk() or member.isfifo():
        raise ValueError("unsupported special runtime archive member: %s" % member.name)
    if member.issym():
        if "\\" in member.linkname:
            raise ValueError("runtime archive link uses a non-POSIX path: %s" % member.name)
        link = PurePosixPath(member.linkname)
        if link.is_absolute():
            raise ValueError("unsafe absolute runtime archive link: %s" % member.name)
        resolved = path.parent.joinpath(link)
        parts = []
        for part in resolved.parts:
            if part in {"", "."}:
                continue
            if part == "..":
                if not parts:
                    raise ValueError("runtime archive link escapes its root: %s" % member.name)
                parts.pop()
            else:
                parts.append(part)
        if not parts or parts[0] != "python":
            raise ValueError("runtime archive link escapes its root: %s" % member.name)
    if member.islnk():
        if "\\" in member.linkname:
            raise ValueError("runtime archive link uses a non-POSIX path: %s" % member.name)
        link = PurePosixPath(member.linkname)
        if link.is_absolute() or not link.parts or link.parts[0] != "python" or ".." in link.parts:
            raise ValueError("runtime archive hard link escapes its root: %s" % member.name)


def _extract_archive(archive, destination):
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        if not members:
            raise ValueError("Desktop Python runtime archive is empty")
        for member in members:
            _safe_member(member)
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Python 3.14 will, by default, filter extracted tar archives")
            bundle.extractall(destination, members=members)


def _download(url, output, expected_size):
    request = Request(url, headers={"User-Agent": "infergrade-runner-runtime-preparer/1"})
    partial = Path(str(output) + ".partial")
    partial.unlink(missing_ok=True)
    written = 0
    try:
        with urlopen(request, timeout=60) as response, partial.open("wb") as handle:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                written += len(chunk)
                if written > expected_size:
                    raise ValueError("Desktop Python runtime download exceeded its reviewed size")
                handle.write(chunk)
        if written != expected_size:
            raise ValueError("Desktop Python runtime size %s does not match reviewed size %s" % (written, expected_size))
        os.replace(partial, output)
    finally:
        partial.unlink(missing_ok=True)


def _runtime_is_current(output, target, archive_sha, manifest_sha, executable, prune_paths=()):
    receipt_path = output / RECEIPT_NAME
    if not receipt_path.is_file():
        return False
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    identity_matches = (
        receipt.get("schema_version") == "infergrade.desktop_python_runtime_receipt.v1"
        and receipt.get("target") == target
        and receipt.get("archive_sha256") == archive_sha
        and receipt.get("manifest_sha256") == manifest_sha
        and receipt.get("executable") == executable
        and receipt.get("pruned_paths", []) == list(prune_paths)
    )
    if not identity_matches:
        return False
    for path_field, digest_field in (
        ("executable", "executable_sha256"),
        ("ca_bundle", "ca_bundle_sha256"),
        ("license_path", "license_sha256"),
    ):
        raw_path = receipt.get(path_field)
        expected_digest = receipt.get(digest_field)
        if not isinstance(raw_path, str) or not isinstance(expected_digest, str):
            return False
        relative = PurePosixPath(raw_path)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            return False
        path = output.joinpath(*relative.parts)
        if not path.is_file() or _sha256(path) != expected_digest:
            return False
    return True


def _prune_runtime(runtime, prune_paths):
    pruned = []
    for raw_path in prune_paths:
        relative = PurePosixPath(raw_path)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise ValueError("unsafe Desktop Python prune path: %s" % raw_path)
        path = runtime.joinpath(*relative.parts)
        if not path.exists() and not path.is_symlink():
            raise ValueError("Desktop Python prune path is missing: %s" % raw_path)
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        else:
            raise ValueError("unsupported Desktop Python prune path: %s" % raw_path)
        pruned.append(raw_path)
    return pruned


def prepare_runtime(manifest_path, target, output, cache_dir, archive_override=None, check_only=False):
    manifest, manifest_sha = _load_manifest(manifest_path)
    try:
        selected = manifest["targets"][target]
    except KeyError as exc:
        raise ValueError("Desktop Python target is not reviewed: %s" % target) from exc
    expected_size = int(selected["size_bytes"])
    expected_sha = str(selected["sha256"])
    executable = str(selected["executable"])
    ca_bundle = str(selected["ca_bundle"])
    license_file = str(selected["license"])
    prune_paths = list(selected.get("prune_paths", []))
    output = Path(output)
    if _runtime_is_current(output, target, expected_sha, manifest_sha, executable, prune_paths):
        print("desktop_python_runtime=%s" % output)
        print("desktop_python_runtime_status=current")
        return output
    if check_only:
        raise ValueError("prepared Desktop Python runtime is missing or stale")

    cache_dir = Path(cache_dir).expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive = Path(archive_override) if archive_override else cache_dir / selected["archive"]
    if not archive.is_file() or archive.stat().st_size != expected_size or _sha256(archive) != expected_sha:
        if archive_override:
            raise ValueError("provided Desktop Python archive does not match reviewed size and SHA-256")
        archive.unlink(missing_ok=True)
        _download(selected["url"], archive, expected_size)
    actual_sha = _sha256(archive)
    if archive.stat().st_size != expected_size or actual_sha != expected_sha:
        raise ValueError("Desktop Python archive failed reviewed size or SHA-256 verification")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="infergrade-desktop-python-", dir=str(output.parent)) as temporary:
        extraction_root = Path(temporary) / "extract"
        extraction_root.mkdir()
        _extract_archive(archive, extraction_root)
        runtime = extraction_root / "python"
        pruned_paths = _prune_runtime(runtime, prune_paths)
        executable_path = runtime / executable
        ca_path = runtime / ca_bundle
        license_path = runtime / license_file
        for required in (executable_path, ca_path, license_path):
            if not required.is_file():
                raise ValueError("Desktop Python runtime is missing required file: %s" % required.relative_to(runtime))
        environment = os.environ.copy()
        environment["PYTHONHOME"] = str(runtime)
        environment["SSL_CERT_FILE"] = str(ca_path)
        version = subprocess.run(
            [str(executable_path), "-I", "-c", "import json, ssl, sys; print(json.dumps({'version': sys.version.split()[0], 'ssl': ssl.OPENSSL_VERSION}))"],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        version_payload = json.loads(version.stdout)
        if version_payload.get("version") != manifest["python_version"]:
            raise ValueError("Desktop Python runtime reported unexpected version")
        receipt = {
            "schema_version": "infergrade.desktop_python_runtime_receipt.v1",
            "distribution": manifest["distribution"],
            "release": manifest["release"],
            "python_version": manifest["python_version"],
            "target": target,
            "archive": selected["archive"],
            "archive_size_bytes": expected_size,
            "archive_sha256": actual_sha,
            "manifest_sha256": manifest_sha,
            "executable": executable,
            "executable_sha256": _sha256(executable_path),
            "ca_bundle": ca_bundle,
            "ca_bundle_sha256": _sha256(ca_path),
            "license_path": license_file,
            "license_sha256": _sha256(license_path),
            "ssl_version": version_payload.get("ssl"),
            "pruned_paths": pruned_paths,
        }
        (runtime / RECEIPT_NAME).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        previous = Path(str(output) + ".previous")
        if previous.exists():
            shutil.rmtree(previous)
        if output.exists():
            os.replace(output, previous)
        try:
            os.replace(runtime, output)
        except Exception:
            if previous.exists() and not output.exists():
                os.replace(previous, output)
            raise
        shutil.rmtree(previous, ignore_errors=True)

    print("desktop_python_runtime=%s" % output)
    print("desktop_python_runtime_status=prepared")
    print("desktop_python_runtime_target=%s" % target)
    print("desktop_python_runtime_sha256=%s" % actual_sha)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--target", default=None)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--cache-dir", default=os.environ.get("INFERGRADE_DESKTOP_PYTHON_CACHE", "~/.cache/infergrade/desktop-python"))
    parser.add_argument("--archive", default=None, help="Use a local archive; intended for verification and tests.")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        prepare_runtime(
            Path(args.manifest),
            args.target or _target_triple(),
            Path(args.output),
            Path(args.cache_dir),
            archive_override=args.archive,
            check_only=args.check,
        )
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
