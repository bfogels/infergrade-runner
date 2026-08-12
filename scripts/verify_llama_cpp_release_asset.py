#!/usr/bin/env python3
"""Verify one official llama.cpp release archive and emit a candidate receipt.

This check establishes archive identity, bounded safe extraction, the expected
tool inventory, and (when requested on the matching host) a version smoke. It
does not promote the release or claim model compatibility.
"""

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import ssl
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from typing import Any, Dict, Iterable, List, Optional, Tuple


MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
MAX_MEMBERS = 1000
PLATFORMS = {
    "macos-arm64": {
        "asset": "llama-{tag}-bin-macos-arm64.tar.gz",
        "executables": ["llama-cli", "llama-completion", "llama-server", "llama-perplexity"],
    },
    "ubuntu-x64": {
        "asset": "llama-{tag}-bin-ubuntu-x64.tar.gz",
        "executables": ["llama-cli", "llama-completion", "llama-server", "llama-perplexity"],
    },
    "windows-cpu-x64": {
        "asset": "llama-{tag}-bin-win-cpu-x64.zip",
        "executables": [
            "llama-cli.exe",
            "llama-completion.exe",
            "llama-server.exe",
            "llama-perplexity.exe",
        ],
    },
}


def load_json(path: pathlib.Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def release_asset(release: Dict[str, Any], platform: str) -> Tuple[str, Dict[str, Any], List[str]]:
    if platform not in PLATFORMS:
        raise ValueError(f"unsupported platform: {platform}")
    tag = str(release.get("tag_name") or "").strip()
    if not tag.startswith("b") or not tag[1:].isdigit():
        raise ValueError("release tag must use llama.cpp's bNNNN format")
    spec = PLATFORMS[platform]
    expected_name = str(spec["asset"]).format(tag=tag)
    matches = [item for item in release.get("assets", []) if item.get("name") == expected_name]
    if len(matches) != 1:
        raise ValueError(f"release must contain exactly one {expected_name} asset")
    asset = matches[0]
    digest = str(asset.get("digest") or "")
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise ValueError(f"{expected_name}: GitHub SHA-256 digest is missing or invalid")
    size = int(asset.get("size") or 0)
    if size <= 0 or size > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"{expected_name}: asset size {size} is outside the download bound")
    url = str(asset.get("browser_download_url") or "")
    if not url.startswith("https://github.com/ggml-org/llama.cpp/releases/download/"):
        raise ValueError(f"{expected_name}: unexpected download URL")
    return expected_name, asset, list(spec["executables"])


def _download_asset_once(url: str, destination: pathlib.Path, expected_size: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "InferGrade-Runtime-Intake/1"})
    configured_ca = os.environ.get("SSL_CERT_FILE")
    ca_candidates = [configured_ca, "/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"]
    ca_file = next((item for item in ca_candidates if item and pathlib.Path(item).is_file()), None)
    context = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
    digest = hashlib.sha256()
    observed = 0
    with urllib.request.urlopen(request, timeout=60, context=context) as response, destination.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            observed += len(chunk)
            if observed > MAX_DOWNLOAD_BYTES:
                raise ValueError("download exceeded the configured byte bound")
            digest.update(chunk)
            handle.write(chunk)
    if observed != expected_size:
        raise ValueError(f"download size mismatch: expected {expected_size}, observed {observed}")
    return digest.hexdigest()


def _retryable_download_error(error: BaseException) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code in {408, 429} or 500 <= error.code <= 599
    return isinstance(error, (ConnectionError, TimeoutError, urllib.error.URLError))


def download_asset(url: str, destination: pathlib.Path, expected_size: int) -> str:
    attempts = 3
    for attempt in range(1, attempts + 1):
        try:
            return _download_asset_once(url, destination, expected_size)
        except (ConnectionError, TimeoutError, urllib.error.URLError) as exc:
            destination.unlink(missing_ok=True)
            if attempt == attempts or not _retryable_download_error(exc):
                raise
            time.sleep(attempt)
    raise AssertionError("unreachable")


def _safe_member_path(destination: pathlib.Path, name: str) -> pathlib.Path:
    normalized = name.replace("\\", "/")
    relative = pathlib.PurePosixPath(normalized)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe archive member: {name}")
    target = (destination / pathlib.Path(*relative.parts)).resolve()
    if destination.resolve() not in (target, *target.parents):
        raise ValueError(f"archive member escapes extraction root: {name}")
    return target


def _validate_symlink_target(destination: pathlib.Path, member_name: str, link_name: str) -> None:
    if pathlib.PurePosixPath(link_name.replace("\\", "/")).is_absolute():
        raise ValueError(f"unsafe archive link: {member_name} -> {link_name}")
    member_path = _safe_member_path(destination, member_name)
    link_target = (member_path.parent / pathlib.Path(*pathlib.PurePosixPath(link_name).parts)).resolve()
    if destination.resolve() not in (link_target, *link_target.parents):
        raise ValueError(f"unsafe archive link: {member_name} -> {link_name}")


def _validate_inventory(items: Iterable[Tuple[str, int]]) -> List[str]:
    members = list(items)
    if len(members) > MAX_MEMBERS:
        raise ValueError(f"archive contains more than {MAX_MEMBERS} members")
    expanded = sum(max(0, size) for _, size in members)
    if expanded > MAX_EXPANDED_BYTES:
        raise ValueError("archive expands beyond the configured byte bound")
    return [name for name, _ in members]


def extract_archive(archive: pathlib.Path, destination: pathlib.Path) -> List[str]:
    destination.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            members = _validate_inventory((item.filename, item.file_size) for item in infos)
            for item in infos:
                mode = item.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError(f"archive links are not allowed: {item.filename}")
                _safe_member_path(destination, item.filename)
            bundle.extractall(destination)
            return members
    with tarfile.open(archive, mode="r:gz") as bundle:
        infos = bundle.getmembers()
        members = _validate_inventory((item.name, item.size) for item in infos)
        for item in infos:
            if item.islnk() or item.isdev():
                raise ValueError(f"archive hard links and devices are not allowed: {item.name}")
            if item.issym():
                _validate_symlink_target(destination, item.name, item.linkname)
            target = _safe_member_path(destination, item.name)
            if item.issym():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(item.linkname)
                continue
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not item.isfile():
                raise ValueError(f"unsupported archive member type: {item.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(item)
            if source is None:
                raise ValueError(f"archive member could not be read: {item.name}")
            with source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)
            target.chmod(item.mode & 0o777)
        return members


def locate_required(destination: pathlib.Path, names: Iterable[str]) -> Dict[str, pathlib.Path]:
    located: Dict[str, pathlib.Path] = {}
    for name in names:
        matches = [item for item in destination.rglob(name) if item.is_file()]
        if len(matches) != 1:
            raise ValueError(f"archive must contain exactly one {name}; found {len(matches)}")
        located[name] = matches[0]
    return located


def run_version_smoke(binary: pathlib.Path) -> Dict[str, Any]:
    if os.name != "nt":
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    completed = subprocess.run(
        [str(binary), "--version"],
        cwd=binary.parent,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    if completed.returncode != 0:
        raise ValueError(f"llama-cli --version failed with exit {completed.returncode}: {output[:500]}")
    if not output:
        raise ValueError("llama-cli --version returned no version text")
    return {"status": "passed", "exit_code": completed.returncode, "output": output[:1000]}


def verify(
    release: Dict[str, Any],
    platform: str,
    output: pathlib.Path,
    run_smoke: bool,
    retained_runtime_dir: Optional[pathlib.Path] = None,
) -> Dict[str, Any]:
    asset_name, asset, required = release_asset(release, platform)
    with tempfile.TemporaryDirectory(prefix="infergrade-llama-candidate-") as tmp:
        scratch = pathlib.Path(tmp)
        archive = scratch / asset_name
        observed_digest = download_asset(str(asset["browser_download_url"]), archive, int(asset["size"]))
        expected_digest = str(asset["digest"])[len("sha256:") :]
        if observed_digest != expected_digest:
            raise ValueError("downloaded archive digest does not match GitHub release metadata")
        extracted = scratch / "extracted"
        members = extract_archive(archive, extracted)
        located = locate_required(extracted, required)
        smoke = run_version_smoke(located[required[0]]) if run_smoke else {"status": "not_run"}
        if retained_runtime_dir:
            if retained_runtime_dir.exists():
                raise ValueError("retained runtime directory already exists")
            retained_runtime_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(extracted, retained_runtime_dir)
    receipt = {
        "receipt_version": 1,
        "candidate_only": True,
        "claim_boundary": "Archive identity, safe extraction, expected tools, and optional version execution only; no model compatibility or InferGrade support promotion is implied.",
        "upstream": {
            "repository": "ggml-org/llama.cpp",
            "release": release["tag_name"],
            "published_at": release.get("published_at"),
            "url": release.get("html_url"),
        },
        "platform": platform,
        "artifact": {
            "name": asset_name,
            "size_bytes": int(asset["size"]),
            "github_asset_sha256": expected_digest,
            "downloaded_sha256": observed_digest,
            "member_count": len(members),
            "required_members": required,
            "required_member_paths": {name: str(path.relative_to(extracted)) for name, path in located.items()},
        },
        "version_smoke": smoke,
        "runtime_materialized_for_canary": retained_runtime_dir is not None,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-json", type=pathlib.Path, required=True)
    parser.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--run-version-smoke", action="store_true")
    parser.add_argument(
        "--retain-runtime-dir",
        type=pathlib.Path,
        help="Retain the verified extracted runtime for a same-job model canary.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    try:
        receipt = verify(
            load_json(args.release_json),
            args.platform,
            args.output,
            args.run_version_smoke,
            retained_runtime_dir=args.retain_runtime_dir,
        )
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
        print(f"llama.cpp candidate verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
