#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAURI_DIR="$ROOT_DIR/apps/desktop-runner/src-tauri"
DMG_DIR="$TAURI_DIR/target/release/bundle/dmg"
MACOS_BUNDLE_DIR="$TAURI_DIR/target/release/bundle/macos"

if [ "$(uname -s)" != "Darwin" ]; then
  echo "macOS release verification must run on macOS." >&2
  exit 1
fi

shopt -s nullglob
apps=("$MACOS_BUNDLE_DIR"/*.app)
dmgs=("$DMG_DIR"/*.dmg)
shopt -u nullglob

if [ "${#apps[@]}" -ne 1 ]; then
  echo "Expected exactly one macOS app bundle in $MACOS_BUNDLE_DIR, found ${#apps[@]}." >&2
  exit 1
fi

if [ "${#dmgs[@]}" -ne 1 ]; then
  echo "Expected exactly one macOS DMG in $DMG_DIR, found ${#dmgs[@]}." >&2
  exit 1
fi

app="${apps[0]}"
dmg="${dmgs[0]}"

echo "Verifying app code signature: $app"
codesign --verify --deep --strict --verbose=2 "$app"
codesign --display --verbose=4 "$app"

echo "Assessing app with Gatekeeper: $app"
spctl --assess --type execute --verbose=4 "$app"

echo "Validating app notarization ticket: $app"
xcrun stapler validate "$app"

echo "Assessing DMG with Gatekeeper: $dmg"
spctl --assess --type open --context context:primary-signature --verbose=4 "$dmg"

echo "Validating DMG notarization ticket: $dmg"
xcrun stapler validate "$dmg"

echo "macOS desktop release artifacts passed signing, notarization, and Gatekeeper verification."
