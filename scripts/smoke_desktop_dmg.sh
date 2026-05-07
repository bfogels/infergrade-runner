#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DMG_PATH=""
LAUNCH_APP=1
KEEP_MOUNT=0

usage() {
  cat >&2 <<'USAGE'
Usage: scripts/smoke_desktop_dmg.sh [--dmg path] [--no-launch] [--keep-mounted]

Mount a local InferGrade Runner macOS DMG, verify the app signature, run the
packaged sidecar under a clean PATH, optionally launch the app briefly, and
print artifact evidence for release notes.

This is a local smoke for ad-hoc or protected release candidates. It does not
replace Developer ID signing, notarization, Gatekeeper, or clean-machine UI
first-run upload proof.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dmg)
      shift
      DMG_PATH="${1:-}"
      if [ -z "$DMG_PATH" ]; then
        echo "--dmg requires a path" >&2
        exit 2
      fi
      ;;
    --no-launch)
      LAUNCH_APP=0
      ;;
    --keep-mounted)
      KEEP_MOUNT=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
  shift
done

if [ "$(uname -s)" != "Darwin" ]; then
  echo "Desktop DMG smoke must run on macOS." >&2
  exit 1
fi

if [ -z "$DMG_PATH" ]; then
  shopt -s nullglob
  dmgs=("$ROOT_DIR"/target/release/bundle/dmg/*.dmg)
  shopt -u nullglob
  if [ "${#dmgs[@]}" -ne 1 ]; then
    echo "Expected exactly one DMG under target/release/bundle/dmg; found ${#dmgs[@]}. Use --dmg." >&2
    exit 1
  fi
  DMG_PATH="${dmgs[0]}"
fi

if [ ! -f "$DMG_PATH" ]; then
  echo "DMG not found: $DMG_PATH" >&2
  exit 1
fi

size_bytes="$(wc -c < "$DMG_PATH" | tr -d ' ')"
sha256="$(shasum -a 256 "$DMG_PATH" | awk '{print $1}')"
mount_point=""
app_pid=""

detach_mount() {
  if [ -n "$app_pid" ] && kill -0 "$app_pid" >/dev/null 2>&1; then
    kill "$app_pid" >/dev/null 2>&1 || true
    wait "$app_pid" >/dev/null 2>&1 || true
    app_pid=""
    sleep 1
  fi
  if [ -n "$mount_point" ] && [ "$KEEP_MOUNT" -eq 0 ]; then
    hdiutil detach "$mount_point" >/dev/null 2>&1 || hdiutil detach -force "$mount_point" >/dev/null 2>&1 || true
  fi
}
trap detach_mount EXIT

attach_output="$(hdiutil attach "$DMG_PATH" -nobrowse -readonly)"
echo "$attach_output"
mount_point="$(printf '%s\n' "$attach_output" | sed -n 's#^/dev/.*[[:space:]]\(/Volumes/.*\)$#\1#p' | tail -1)"
if [ -z "$mount_point" ] || [ ! -d "$mount_point" ]; then
  echo "Could not determine DMG mount point." >&2
  exit 1
fi

app_path="$mount_point/InferGrade Runner.app"
sidecar_path="$app_path/Contents/MacOS/infergrade-sidecar"
runner_path="$app_path/Contents/MacOS/infergrade_desktop_runner"

if [ ! -d "$app_path" ]; then
  echo "InferGrade Runner.app not found in $mount_point" >&2
  exit 1
fi
if [ ! -x "$sidecar_path" ]; then
  echo "Packaged sidecar not executable: $sidecar_path" >&2
  exit 1
fi
if [ ! -x "$runner_path" ]; then
  echo "Packaged desktop runner not executable: $runner_path" >&2
  exit 1
fi

codesign --verify --deep --strict --verbose=2 "$app_path"
sidecar_version="$(env -i HOME="$HOME" PATH='/usr/bin:/bin' "$sidecar_path" --version | tr -d '\r')"

launched="false"
if [ "$LAUNCH_APP" -eq 1 ]; then
  "$runner_path" >/tmp/infergrade-desktop-dmg-smoke.log 2>&1 &
  app_pid="$!"
  sleep 5
  if ! kill -0 "$app_pid" >/dev/null 2>&1; then
    echo "Packaged desktop runner exited during launch smoke." >&2
    sed -n '1,120p' /tmp/infergrade-desktop-dmg-smoke.log >&2 || true
    exit 1
  fi
  launched="true"
fi

cat <<REPORT
desktop_dmg_smoke=pass
desktop_dmg_artifact=$DMG_PATH
desktop_dmg_size_bytes=$size_bytes
desktop_dmg_sha256=$sha256
desktop_dmg_mount=$mount_point
desktop_dmg_codesign=pass
desktop_dmg_sidecar_version=$sidecar_version
desktop_dmg_launch_observed=$launched
desktop_dmg_clean_path=/usr/bin:/bin
desktop_dmg_notarization=not_checked_by_local_smoke
REPORT
