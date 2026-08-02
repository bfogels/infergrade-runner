#!/usr/bin/env python3
"""Reseal the bundled Python receipt and rebuild a post-linuxdeploy AppImage."""

import argparse
import os
import subprocess
from pathlib import Path

from prepare_desktop_python_runtime import refresh_runtime_receipt


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE_DIR = ROOT / "target" / "release" / "bundle" / "appimage"
DEFAULT_PLUGIN = Path.home() / ".cache" / "tauri" / "linuxdeploy-plugin-appimage.AppImage"
TRANSFORM = "linuxdeploy_appimage_v1"


def _exactly_one(paths, description):
    matches = sorted(paths)
    if len(matches) != 1:
        raise ValueError("expected exactly one %s, found %s" % (description, len(matches)))
    return matches[0]


def finalize_appimage(bundle_dir, plugin=DEFAULT_PLUGIN, runner=subprocess.run):
    bundle_dir = Path(bundle_dir)
    app_dir = _exactly_one((path for path in bundle_dir.glob("*.AppDir") if path.is_dir()), "AppDir")
    appimage = _exactly_one(
        (path for path in bundle_dir.glob("*.AppImage") if path.is_file()),
        "AppImage",
    )
    plugin = Path(plugin)
    if not plugin.is_file():
        raise ValueError("linuxdeploy AppImage plugin is missing: %s" % plugin)

    runtime = app_dir / "usr" / "lib" / "InferGrade Runner" / "python-runtime"
    refresh_runtime_receipt(runtime, TRANSFORM)

    resealed = appimage.with_name(appimage.stem + ".resealed.AppImage")
    resealed.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "APPIMAGE_EXTRACT_AND_RUN": "1",
            "LDAI_OUTPUT": str(resealed),
            "LDAI_VERBOSE": "1",
        }
    )
    try:
        runner(
            [str(plugin), "--appimage-extract-and-run", "--appdir", str(app_dir)],
            check=True,
            env=environment,
        )
        if not resealed.is_file() or resealed.stat().st_size == 0:
            raise ValueError("AppImage reseal did not create a non-empty package")
        os.replace(resealed, appimage)
    finally:
        resealed.unlink(missing_ok=True)

    print("desktop_linux_appimage=%s" % appimage)
    print("desktop_linux_appimage_status=resealed")
    print("desktop_linux_appimage_transform=%s" % TRANSFORM)
    return appimage


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE_DIR))
    parser.add_argument("--plugin", default=str(DEFAULT_PLUGIN))
    args = parser.parse_args(argv)
    try:
        finalize_appimage(Path(args.bundle_dir), Path(args.plugin))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
