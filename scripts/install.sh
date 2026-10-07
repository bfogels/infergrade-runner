#!/usr/bin/env bash
# Install a complete per-user headless Runner; no compiler, Git checkout or Docker.
set -Eeuo pipefail
trap 'printf "\nInferGrade setup did not finish. The error above explains the failed step.\n" >&2' ERR
if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != x86_64 ]; then
  echo 'This headless installer currently supports Linux x86_64. Use the Desktop installer on other platforms.' >&2
  exit 1
fi
if ! command -v apt-get >/dev/null 2>&1; then
  echo 'This installer currently supports Debian/Ubuntu. Other distributions need a packaged dependency route.' >&2
  exit 1
fi
# Dependencies are distribution packages; leave NVIDIA drivers under OS ownership.
packages=(python3 python3-venv ca-certificates curl libgomp1 libstdc++6)
missing=()
for package in "${packages[@]}"; do
  if ! dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q '^install ok installed$'; then
    missing+=("$package")
  fi
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo 'Installing required system packages (administrator permission may be requested).'
  privilege=()
  if [ "$(id -u)" != 0 ]; then
    command -v sudo >/dev/null || { echo 'System packages are missing and sudo is unavailable.' >&2; exit 1; }
    privilege=(sudo)
  fi
  "${privilege[@]}" apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 update
  "${privilege[@]}" apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 install -y --no-install-recommends "${missing[@]}"
fi
install_root="${INFERGRADE_INSTALL_DIR:-$HOME/.local/share/infergrade}"
command_root="${INFERGRADE_BIN_DIR:-$HOME/.local/bin}"
mkdir -p "$install_root/releases" "$command_root"
work_dir="$(mktemp -d "$install_root/.install-XXXXXX")"
trap 'rm -rf "$work_dir"' EXIT
fetch() { curl --fail --silent --show-error --location --retry 3 --connect-timeout 15 --max-time 600 "$1" -o "$2"; }
version="${INFERGRADE_VERSION:-}"
if [ -z "$version" ]; then
  fetch https://api.github.com/repos/bfogels/infergrade-runner/releases/latest "$work_dir/release.json"
  version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tag_name"].lstrip("v"))' "$work_dir/release.json")"
fi
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then echo 'Invalid Runner release version.' >&2; exit 1; fi
asset="infergrade-runner-$version-linux-x86_64.tar.gz"
release_url="https://github.com/bfogels/infergrade-runner/releases/download/v$version"
echo "Installing InferGrade $version."
fetch "$release_url/SHA256SUMS" "$work_dir/SHA256SUMS"
fetch "$release_url/$asset" "$work_dir/$asset"
python3 - "$work_dir" "$asset" <<'PY'
import hashlib, pathlib, sys, tarfile
root, name = pathlib.Path(sys.argv[1]), sys.argv[2]
checks = {}
for line in (root / 'SHA256SUMS').read_text().splitlines():
    digest, filename = line.split(None, 1)
    checks[filename.lstrip('*')] = digest
if checks.get(name) != hashlib.sha256((root / name).read_bytes()).hexdigest():
    raise SystemExit('Runner archive checksum did not match its release.')
with tarfile.open(root / name) as archive:
    destination = root / 'bundle'
    destination.mkdir()
    for member in archive.getmembers():
        path = (destination / member.name).resolve()
        if destination.resolve() not in path.parents or member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
            raise SystemExit('Unsafe path or link in Runner release archive.')
    archive.extractall(destination)
PY
# The checksum names the immutable installation, so reruns can reuse it safely.
digest="$(sha256sum "$work_dir/$asset" | cut -d ' ' -f 1)"
release_root="$install_root/releases/$version-$digest"
if [ ! -d "$release_root" ]; then mv "$work_dir/bundle" "$release_root"; fi
python3 -m venv --without-pip "$release_root/venv"
python3 - "$release_root" <<'PY'
import pathlib, shlex, sys
root = pathlib.Path(sys.argv[1])
launcher = '#!/bin/sh\n'
launcher += 'export INFERGRADE_RUNNER_ROOT=' + shlex.quote(str(root / 'runner')) + '\n'
launcher += 'export PYTHONPATH=' + shlex.quote(str(root / 'runner/python/runner-core/src')) + '\n'
launcher += 'export PATH=' + shlex.quote(str(root / 'bin')) + ':"$PATH"\n'
launcher += 'exec ' + shlex.quote(str(root / 'venv/bin/python')) + ' -m infergrade.cli "$@"\n'
(root / 'bin/infergrade').write_text(launcher)
(root / 'bin/infergrade').chmod(0o755)
PY
# Runtime setup is part of installation and must succeed before exposing commands.
INFERGRADE_RUNNER_ROOT="$release_root/runner" \
PYTHONPATH="$release_root/runner/python/runner-core/src" \
PATH="$release_root/bin:$PATH" \
"$release_root/venv/bin/python" -c \
  'from infergrade.runtimes import prepare_native_listener_runtime; prepare_native_listener_runtime(emit_progress=print)'
python3 - "$release_root" "$command_root" <<'PY'
import os, pathlib, sys
root, commands = map(pathlib.Path, sys.argv[1:])
for name in ('infergrade', 'infergrade-runner'):
    temporary = commands / ('.' + name + '-install')
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(root / 'bin' / name)
    os.replace(temporary, commands / name)
PY
printf '\nInferGrade is installed and its native runtime is ready.\nPair and listen with:\n  %q pair --start\n' "$command_root/infergrade"
