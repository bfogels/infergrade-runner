#!/usr/bin/env python3
"""Developer ID sign every Mach-O file in the bundled macOS Python runtime."""

import argparse
import subprocess
import sys
from pathlib import Path

from prepare_desktop_python_runtime import refresh_runtime_receipt


TRANSFORM = "macos_developer_id_signing_v1"


def discover_macho_files(runtime: Path, runner=subprocess.run):
    """Return unique regular Mach-O files, deepest paths first."""
    discovered = []
    seen_files = set()
    for path in sorted(runtime.rglob("*"), key=lambda item: (-len(item.parts), str(item))):
        if path.is_symlink() or not path.is_file():
            continue
        identity = (path.stat().st_dev, path.stat().st_ino)
        if identity in seen_files:
            continue
        inspected = runner(
            ["/usr/bin/file", "-b", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if inspected.returncode != 0:
            raise ValueError("could not inspect bundled runtime file: %s" % path)
        if "Mach-O" not in inspected.stdout:
            continue
        seen_files.add(identity)
        discovered.append(path)
    return discovered


def sign_runtime(runtime: Path, identity: str, keychain: Path = None, runner=subprocess.run):
    """Sign and verify all embedded code, then reseal the runtime receipt."""
    runtime = runtime.resolve()
    if not runtime.is_dir():
        raise ValueError("bundled macOS Python runtime does not exist: %s" % runtime)
    if not identity or identity == "-":
        raise ValueError("a Developer ID signing identity is required")

    macho_files = discover_macho_files(runtime, runner=runner)
    if not macho_files:
        raise ValueError("bundled macOS Python runtime contains no Mach-O files")

    for path in macho_files:
        command = [
            "/usr/bin/codesign",
            "--force",
            "--options",
            "runtime",
            "--timestamp",
        ]
        if keychain is not None:
            command.extend(["--keychain", str(keychain)])
        command.extend(["--sign", identity, str(path)])
        runner(
            command,
            check=True,
        )

    refresh_runtime_receipt(runtime, TRANSFORM)

    for path in macho_files:
        runner(
            ["/usr/bin/codesign", "--verify", "--strict", "--verbose=2", str(path)],
            check=True,
        )
    return macho_files


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--keychain")
    args = parser.parse_args(argv)
    if sys.platform != "darwin":
        parser.error("macOS embedded-runtime signing must run on macOS")
    try:
        signed = sign_runtime(
            Path(args.runtime),
            args.identity,
            keychain=Path(args.keychain) if args.keychain else None,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))
    print("desktop_python_runtime_signing=developer_id")
    print("desktop_python_runtime_signed_macho_files=%d" % len(signed))
    print("desktop_python_runtime_packaging_transform=%s" % TRANSFORM)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
