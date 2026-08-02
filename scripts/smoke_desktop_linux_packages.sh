#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "usage: $0 <deb> <appimage> <expected-version>" >&2
  exit 2
fi

deb_path="$(realpath "$1")"
appimage_path="$(realpath "$2")"
expected_version="$3"

for artifact in "$deb_path" "$appimage_path"; do
  if [ ! -f "$artifact" ]; then
    echo "Desktop package does not exist: $artifact" >&2
    exit 1
  fi
done

package_name="$(dpkg-deb --field "$deb_path" Package)"
package_version="$(dpkg-deb --field "$deb_path" Version)"
if [ "$package_version" != "$expected_version" ]; then
  echo "Debian package version $package_version does not match $expected_version." >&2
  exit 1
fi

work_dir="$(mktemp -d)"
cleanup() {
  if [ -n "${desktop_pid:-}" ]; then
    kill "$desktop_pid" >/dev/null 2>&1 || true
    wait "$desktop_pid" >/dev/null 2>&1 || true
  fi
  sudo dpkg --purge "$package_name" >/dev/null 2>&1 || true
  rm -rf "$work_dir"
}
trap cleanup EXIT

dpkg-deb --extract "$deb_path" "$work_dir/deb"
deb_executable="$(find "$work_dir/deb" -type f -perm -u+x -name 'infergrade_desktop_runner' -print -quit)"
deb_sidecar="$(find "$work_dir/deb" -type f -perm -u+x -name 'infergrade-sidecar*' -print -quit)"
deb_runner_core="$(find "$work_dir/deb" -type d -path '*/runner-core/src/infergrade' -print -quit)"
if [ -z "$deb_executable" ] || [ -z "$deb_sidecar" ] || [ -z "$deb_runner_core" ]; then
  echo "Debian package is missing the desktop executable or sidecar." >&2
  exit 1
fi

sudo apt-get install -y "$deb_path"
installed_executable="$(command -v infergrade_desktop_runner || true)"
if [ -z "$installed_executable" ]; then
  installed_executable="$(find /usr/bin /usr/lib /opt -type f -name 'infergrade_desktop_runner' -print -quit 2>/dev/null || true)"
fi

installed_sidecar="$(find /usr/bin /usr/lib /opt -type f -perm -u+x -name 'infergrade-sidecar*' -print -quit 2>/dev/null || true)"
if [ -z "$installed_sidecar" ]; then
  echo "Installed Debian package did not expose the packaged sidecar." >&2
  exit 1
fi
"$installed_sidecar" desktop-self-test > "$work_dir/deb-sidecar-self-test.json"
python3 - "$work_dir/deb-sidecar-self-test.json" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload.get("invocation") != "ok":
    raise SystemExit("Installed Linux sidecar self-test did not report invocation=ok")
PY
if [ -z "$installed_executable" ]; then
  echo "Installed Debian package did not expose the desktop executable." >&2
  exit 1
fi

dbus-run-session -- xvfb-run -a "$installed_executable" > "$work_dir/deb-launch.log" 2>&1 &
desktop_pid=$!
sleep 8
if ! kill -0 "$desktop_pid" >/dev/null 2>&1; then
  wait "$desktop_pid" || true
  echo "Installed Debian desktop app exited during launch smoke." >&2
  cat "$work_dir/deb-launch.log" >&2
  exit 1
fi
kill "$desktop_pid" >/dev/null 2>&1 || true
wait "$desktop_pid" >/dev/null 2>&1 || true
desktop_pid=""
sudo dpkg --purge "$package_name" >/dev/null

chmod +x "$appimage_path"
mkdir -p "$work_dir/appimage"
(
  cd "$work_dir/appimage"
  "$appimage_path" --appimage-extract >/dev/null
)
appimage_sidecar="$(find "$work_dir/appimage/squashfs-root" -type f -perm -u+x -name 'infergrade-sidecar*' -print -quit)"
if [ -z "$appimage_sidecar" ]; then
  echo "AppImage is missing the packaged sidecar." >&2
  exit 1
fi
"$appimage_sidecar" desktop-self-test > "$work_dir/appimage-sidecar-self-test.json"

APPIMAGE_EXTRACT_AND_RUN=1 dbus-run-session -- xvfb-run -a "$appimage_path" > "$work_dir/appimage-launch.log" 2>&1 &
desktop_pid=$!
sleep 8
if ! kill -0 "$desktop_pid" >/dev/null 2>&1; then
  wait "$desktop_pid" || true
  echo "AppImage exited during launch smoke." >&2
  cat "$work_dir/appimage-launch.log" >&2
  exit 1
fi
kill "$desktop_pid" >/dev/null 2>&1 || true
wait "$desktop_pid" >/dev/null 2>&1 || true
desktop_pid=""

echo "desktop_linux_package_smoke=pass"
echo "desktop_linux_deb_package=$package_name"
echo "desktop_linux_package_version=$package_version"
echo "desktop_linux_gpu_execution=not_tested"
