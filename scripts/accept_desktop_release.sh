#!/usr/bin/env bash
set -euo pipefail

PUBLIC_DMG_URL="https://github.com/bfogels/infergrade-runner/releases/latest/download/InferGrade.Runner.macOS-arm64.dmg"
DMG_SOURCE="$PUBLIC_DMG_URL"
REPORT_DIR=""
LAUNCH_SECONDS=8
CAPTURE_SCREEN=0
INTERACTIVE=0

usage() {
  cat >&2 <<'USAGE'
Usage: scripts/accept_desktop_release.sh [options]

Download or open the signed public macOS installer, verify its trust chain,
launch it with isolated app/config/runtime/keychain state, exercise the packaged
Runner self-test and readiness checks, and write a secret-free acceptance report.

Options:
  --dmg PATH_OR_URL      Installer to test (default: latest public GitHub DMG)
  --report-dir PATH      Durable report directory (default: timestamped temp path)
  --launch-seconds N     Seconds to observe the clean-profile app (default: 8)
  --interactive          Keep the isolated app open until Enter is pressed
  --capture-screen       Capture the current display after launch (may include private UI)
  -h, --help             Show this help

This automated smoke proves installer trust, packaged-core invocation, clean
profile isolation, and launch survival. It does not claim pairing, a real model
run, upload, or signed-out Result-page acceptance; record those in the manual
acceptance checklist after interacting with the launched app.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dmg)
      shift
      DMG_SOURCE="${1:-}"
      [ -n "$DMG_SOURCE" ] || { echo "--dmg requires a path or URL" >&2; exit 2; }
      ;;
    --report-dir)
      shift
      REPORT_DIR="${1:-}"
      [ -n "$REPORT_DIR" ] || { echo "--report-dir requires a path" >&2; exit 2; }
      ;;
    --launch-seconds)
      shift
      LAUNCH_SECONDS="${1:-}"
      [[ "$LAUNCH_SECONDS" =~ ^[1-9][0-9]*$ ]] || { echo "--launch-seconds requires a positive integer" >&2; exit 2; }
      ;;
    --capture-screen)
      CAPTURE_SCREEN=1
      ;;
    --interactive)
      INTERACTIVE=1
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

[ "$(uname -s)" = "Darwin" ] || { echo "Desktop release acceptance requires macOS." >&2; exit 1; }

started_epoch="$(date +%s)"
started_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
workspace="$(mktemp -d "${TMPDIR:-/tmp}/infergrade-desktop-acceptance.XXXXXX")"
if [ -z "$REPORT_DIR" ]; then
  REPORT_DIR="${TMPDIR:-/tmp}/infergrade-desktop-acceptance-report-$(date -u '+%Y%m%dT%H%M%SZ')"
fi
mkdir -p "$REPORT_DIR"
report_dir_absolute="$(cd "$REPORT_DIR" && pwd)"
isolated_home="$workspace/home"
isolated_tmp="$workspace/tmp"
isolated_config="$workspace/config"
isolated_cache="$workspace/runtime-cache"
isolated_applications="$workspace/Applications"
mkdir -p "$isolated_home" "$isolated_tmp" "$isolated_config" "$isolated_cache" "$isolated_applications"
keyring_service="com.infergrade.runner.acceptance.$(uuidgen | tr '[:upper:]' '[:lower:]')"
mount_point=""
app_pid=""

cleanup() {
  if [ -n "$app_pid" ] && kill -0 "$app_pid" >/dev/null 2>&1; then
    kill "$app_pid" >/dev/null 2>&1 || true
    wait "$app_pid" >/dev/null 2>&1 || true
  fi
  security delete-generic-password -s "$keyring_service" -a hub-runner-token >/dev/null 2>&1 || true
  if [ -n "$mount_point" ]; then
    hdiutil detach "$mount_point" >/dev/null 2>&1 || hdiutil detach -force "$mount_point" >/dev/null 2>&1 || true
  fi
  rm -rf "$workspace"
}
trap cleanup EXIT

dmg_path="$DMG_SOURCE"
if [[ "$DMG_SOURCE" =~ ^https:// ]]; then
  dmg_path="$workspace/InferGrade.Runner.macOS-arm64.dmg"
  curl --fail --location --silent --show-error "$DMG_SOURCE" --output "$dmg_path"
fi
[ -f "$dmg_path" ] || { echo "DMG not found: $dmg_path" >&2; exit 1; }
dmg_path="$(cd "$(dirname "$dmg_path")" && pwd)/$(basename "$dmg_path")"
dmg_size_bytes="$(wc -c < "$dmg_path" | tr -d ' ')"
dmg_sha256="$(shasum -a 256 "$dmg_path" | awk '{print $1}')"
if [[ "$DMG_SOURCE" =~ ^https:// ]]; then
  report_dmg_source="$(python3 - "$DMG_SOURCE" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit

parts = urlsplit(sys.argv[1])
print(urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")))
PY
)"
else
  report_dmg_source="local:$(basename "$DMG_SOURCE")"
fi

trust_log="$report_dir_absolute/trust.log"
{
  spctl --assess --type open --context context:primary-signature --verbose=4 "$dmg_path"
  xcrun stapler validate "$dmg_path"
} >"$trust_log" 2>&1

attach_output="$(hdiutil attach "$dmg_path" -nobrowse -readonly)"
mount_point="$(printf '%s\n' "$attach_output" | sed -n 's#^/dev/.*[[:space:]]\(/Volumes/.*\)$#\1#p' | tail -1)"
[ -n "$mount_point" ] && [ -d "$mount_point" ] || { echo "Could not determine DMG mount point." >&2; exit 1; }

source_app_path="$mount_point/InferGrade Runner.app"
app_path="$isolated_applications/InferGrade Runner.app"
[ -d "$source_app_path" ] || { echo "InferGrade Runner.app not found in $mount_point" >&2; exit 1; }
ditto "$source_app_path" "$app_path"
sidecar_path="$app_path/Contents/MacOS/infergrade-sidecar"
runner_path="$app_path/Contents/MacOS/infergrade_desktop_runner"
[ -d "$app_path" ] || { echo "InferGrade Runner.app could not be copied into the isolated install root." >&2; exit 1; }
[ -x "$sidecar_path" ] || { echo "Packaged sidecar is unavailable." >&2; exit 1; }
[ -x "$runner_path" ] || { echo "Packaged desktop runner is unavailable." >&2; exit 1; }

{
  codesign --verify --deep --strict --verbose=2 "$app_path"
  spctl --assess --type execute --verbose=4 "$app_path"
  xcrun stapler validate "$app_path"
} >>"$trust_log" 2>&1

clean_env=(
  env -i
  HOME="$isolated_home"
  TMPDIR="$isolated_tmp"
  PATH="/usr/bin:/bin:/usr/sbin:/sbin"
  INFERGRADE_CONFIG_DIR="$isolated_config"
  INFERGRADE_RUNTIME_CACHE_DIR="$isolated_cache"
  INFERGRADE_ACCEPTANCE_KEYRING_SERVICE="$keyring_service"
)

"${clean_env[@]}" "$sidecar_path" --version >"$report_dir_absolute/sidecar-version.txt"
"${clean_env[@]}" "$sidecar_path" desktop-self-test >"$report_dir_absolute/desktop-self-test.json"
"${clean_env[@]}" "$sidecar_path" desktop-readiness >"$report_dir_absolute/desktop-readiness.json"
python3 -m json.tool "$report_dir_absolute/desktop-self-test.json" >/dev/null
python3 -m json.tool "$report_dir_absolute/desktop-readiness.json" >/dev/null

deterministic_request="$workspace/packaged-deterministic-run.json"
deterministic_bundle="$workspace/packaged-deterministic-bundle"
IG_ACCEPT_DETERMINISTIC_BUNDLE="$deterministic_bundle" python3 - "$deterministic_request" <<'PY'
import json
import os
import sys
from pathlib import Path

request_path = Path(sys.argv[1])
request_path.write_text(
    json.dumps(
        {
            "spec_version": "0.1-draft",
            "run": {
                "model": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
                "backend": "llama.cpp",
                "tier": "canary",
                "use_case": "general_assistant",
                "execution_mode": "local_native",
                "capability_suite_ids": ["chat_instruction_following"],
                "benchmark_group_ids": ["deployment_chat"],
                "benchmark_check_ids": ["interactive_chat_v1"],
                "simulate": True,
                "output_dir": os.environ["IG_ACCEPT_DETERMINISTIC_BUNDLE"],
            },
            "artifacts": {
                "quantized_weights": {
                    "uri": (
                        "hf://TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/"
                        "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf"
                    ),
                    "filename": "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
                }
            },
            "metadata": {
                "notes": "Synthetic packaged-engine acceptance only; not benchmark evidence.",
            },
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
PY
"${clean_env[@]}" "$sidecar_path" --all run --request-file "$deterministic_request" \
  >"$report_dir_absolute/packaged-deterministic-run.log"
"${clean_env[@]}" "$sidecar_path" --all validate-bundle "$deterministic_bundle" \
  >"$report_dir_absolute/packaged-deterministic-validation.json"
python3 - "$deterministic_bundle" "$report_dir_absolute/packaged-deterministic-receipt.json" <<'PY'
import json
import sys
from pathlib import Path

bundle_path, receipt_path = map(Path, sys.argv[1:])
manifest = json.loads((bundle_path / "manifest.json").read_text(encoding="utf-8"))
summary = json.loads((bundle_path / "summary.json").read_text(encoding="utf-8"))
validation = json.loads((bundle_path / "validation.json").read_text(encoding="utf-8"))
result_path = bundle_path / "results" / "interactive_chat_v1.json"
if not result_path.is_file():
    raise SystemExit("Packaged deterministic run did not write interactive_chat_v1.json")
if validation.get("valid") is not True:
    raise SystemExit("Packaged deterministic run did not produce a valid bundle")
receipt = {
    "schema_version": "infergrade.packaged_deterministic_acceptance.v1",
    "synthetic": True,
    "claim_boundary": "Packaged-engine smoke only; not model, runtime, upload, or capability evidence.",
    "bundle_spec_version": manifest.get("bundle_spec_version"),
    "result_spec_version": manifest.get("result_spec_version"),
    "runner_version": (manifest.get("runner") or {}).get("version"),
    "model_family": summary.get("model_family"),
    "benchmark_check_ids": summary.get("benchmark_check_ids"),
    "result_count": summary.get("result_count"),
    "validation": {
        "valid": validation.get("valid"),
        "verification_level": validation.get("verification_level"),
    },
}
receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

"${clean_env[@]}" "$runner_path" >"$report_dir_absolute/app.log" 2>&1 &
app_pid="$!"
if [ "$INTERACTIVE" -eq 1 ]; then
  echo "The isolated Runner is open. Complete the acceptance flow, then press Enter here."
  read -r _
else
  sleep "$LAUNCH_SECONDS"
fi
if ! kill -0 "$app_pid" >/dev/null 2>&1; then
  echo "Packaged desktop runner exited during clean-profile launch." >&2
  sed -n '1,160p' "$report_dir_absolute/app.log" >&2 || true
  exit 1
fi
if [ "$CAPTURE_SCREEN" -eq 1 ]; then
  screencapture -x "$report_dir_absolute/desktop.png"
fi

ended_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
duration_seconds="$(($(date +%s) - started_epoch))"
version="$(defaults read "$app_path/Contents/Info" CFBundleShortVersionString)"
export IG_ACCEPT_STARTED_AT="$started_at" IG_ACCEPT_ENDED_AT="$ended_at"
export IG_ACCEPT_DURATION="$duration_seconds" IG_ACCEPT_VERSION="$version"
export IG_ACCEPT_DMG_SIZE="$dmg_size_bytes" IG_ACCEPT_DMG_SHA="$dmg_sha256"
export IG_ACCEPT_DMG_SOURCE="$report_dmg_source" IG_ACCEPT_SCREENSHOT="$CAPTURE_SCREEN"
python3 - "$report_dir_absolute/report.json" "$report_dir_absolute/report.md" <<'PY'
import json
import os
import sys
from pathlib import Path

json_path, markdown_path = map(Path, sys.argv[1:])
payload = {
    "schema_version": "infergrade.desktop_release_acceptance.v1",
    "status": "automated_checks_passed",
    "started_at": os.environ["IG_ACCEPT_STARTED_AT"],
    "ended_at": os.environ["IG_ACCEPT_ENDED_AT"],
    "duration_seconds": int(os.environ["IG_ACCEPT_DURATION"]),
    "runner_version": os.environ["IG_ACCEPT_VERSION"],
    "dmg": {
        "source": os.environ["IG_ACCEPT_DMG_SOURCE"],
        "size_bytes": int(os.environ["IG_ACCEPT_DMG_SIZE"]),
        "sha256": os.environ["IG_ACCEPT_DMG_SHA"],
    },
    "checks": {
        "dmg_gatekeeper": "passed",
        "dmg_notarization": "passed",
        "app_codesign": "passed",
        "app_gatekeeper": "passed",
        "app_notarization": "passed",
        "isolated_install_copy": "passed",
        "isolated_profile": "passed",
        "packaged_self_test": "passed",
        "packaged_readiness": "passed",
        "packaged_deterministic_bundle": "passed",
        "launch_survival": "passed",
    },
    "screenshot_captured": os.environ["IG_ACCEPT_SCREENSHOT"] == "1",
    "manual_acceptance_remaining": [
        "pairing",
        "recommendation handoff",
        "runtime resolution",
        "real benchmark",
        "upload",
        "signed-out Result page",
    ],
}
json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
checks = "\n".join(f"- {name}: {status}" for name, status in payload["checks"].items())
remaining = "\n".join(f"- {item}" for item in payload["manual_acceptance_remaining"])
markdown_path.write_text(
    "# InferGrade Desktop release acceptance\n\n"
    f"Version: {payload['runner_version']}  \n"
    f"Status: {payload['status']}  \n"
    f"Duration: {payload['duration_seconds']} seconds  \n"
    f"DMG SHA-256: `{payload['dmg']['sha256']}`\n\n"
    "## Automated checks\n\n"
    f"{checks}\n\n"
    "## Manual acceptance remaining\n\n"
    f"{remaining}\n",
    encoding="utf-8",
)
PY

echo "desktop_release_acceptance=pass"
echo "desktop_release_version=$version"
echo "desktop_release_report=$report_dir_absolute/report.md"
echo "desktop_release_manual_flow=remaining"
