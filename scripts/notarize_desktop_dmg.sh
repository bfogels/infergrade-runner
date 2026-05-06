#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DMG_DIR="$ROOT_DIR/target/release/bundle/dmg"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "macOS DMG notarization must run on macOS." >&2
  exit 1
fi

shopt -s nullglob
dmgs=("$DMG_DIR"/*.dmg)
shopt -u nullglob

if [ "${#dmgs[@]}" -ne 1 ]; then
  echo "Expected exactly one macOS DMG in $DMG_DIR, found ${#dmgs[@]}." >&2
  exit 1
fi

dmg="${dmgs[0]}"

echo "Submitting DMG for notarization: $dmg"
if [ -n "${APPLE_API_KEY_PATH:-}" ]; then
  if [ -z "${APPLE_API_KEY:-}" ] || [ -z "${APPLE_API_ISSUER:-}" ]; then
    echo "APPLE_API_KEY_PATH requires APPLE_API_KEY and APPLE_API_ISSUER for notarytool." >&2
    exit 1
  fi
  xcrun notarytool submit "$dmg" \
    --key "$APPLE_API_KEY_PATH" \
    --key-id "$APPLE_API_KEY" \
    --issuer "$APPLE_API_ISSUER" \
    --wait
else
  if [ -z "${APPLE_ID:-}" ] || [ -z "${APPLE_PASSWORD:-}" ] || [ -z "${APPLE_TEAM_ID:-}" ]; then
    echo "APPLE_ID, APPLE_PASSWORD, and APPLE_TEAM_ID are required when APPLE_API_KEY_PATH is not set." >&2
    exit 1
  fi
  xcrun notarytool submit "$dmg" \
    --apple-id "$APPLE_ID" \
    --password "$APPLE_PASSWORD" \
    --team-id "$APPLE_TEAM_ID" \
    --wait
fi

echo "Stapling notarization ticket to DMG: $dmg"
xcrun stapler staple "$dmg"
