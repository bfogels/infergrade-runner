#!/usr/bin/env bash
# Build a managed Linux llama.cpp package against an older C/C++ runtime ABI.
#
# INFERGRADE_RUNTIME_ABI selects the target (default: ubuntu22):
#   ubuntu22  glibc 2.35, libstdc++ GLIBCXX_3.4.30 (Ubuntu 22.04 build host)
#   glibc228  glibc 2.28, libstdc++ GLIBCXX_3.4.25 (Rocky Linux 8 + gcc-toolset;
#             runs on Ubuntu 20.04+, Debian 10+, RHEL/Rocky 8+, Amazon Linux 2023)
# The build fails if any packaged binary needs a newer symbol than the target.
set -euo pipefail
source_commit=d81235049384534c167caea52b85a694f6103d14
source_sha256=6b58785f0a82898f4c3442417ff962e2d4b231b1bee5d033902ad90b27901e14
cccl_commit=5fb1013e3c6f72877a2ebd30f54fe5158d64eec4
cccl_sha256=a87760bed120043b2cb58ee0482e13bb246cf77ec14b49542fb8688842bd91b5
eula_url=https://docs.nvidia.com/cuda/archive/12.8.1/eula/index.html
eula_sha256=6722d4c310a2ec9ad869ede3371a648fe2cfc2baaf8e1ece2c35e1dccc05752c
output_dir="${1:?Pass an output directory}"
abi="${INFERGRADE_RUNTIME_ABI:-ubuntu22}"
case "$abi" in
  ubuntu22) max_glibc=2.35; max_glibcxx=30; abi_platform=ubuntu22.04-x86_64 ;;
  glibc228) max_glibc=2.28; max_glibcxx=25; abi_platform=glibc2.28-x86_64 ;;
  *) echo "Unknown INFERGRADE_RUNTIME_ABI: $abi" >&2; exit 1 ;;
esac
jobs="${INFERGRADE_BUILD_JOBS:-2}"
accelerator="${2:-cuda}"
if [ "$accelerator" != cuda ] && [ "$accelerator" != cpu ]; then echo 'Expected cuda or cpu.' >&2; exit 1; fi
cuda_enabled=OFF
backend_loading=OFF
if [ "$accelerator" = cuda ]; then cuda_enabled=ON; backend_loading=ON; fi
mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd)"
build_dir="$(mktemp -d)"
cleanup() {
  status=$?
  if [ "$status" -ne 0 ] && [ -d "$build_dir/build/bin" ]; then
    tar -czf "$output_dir/unverified-build-recovery.tar.gz" -C "$build_dir/build" bin || true
    echo 'Unverified build outputs retained for diagnosis; failed builds are not release candidates.' >&2
  fi
  rm -rf "$build_dir"
}
trap cleanup EXIT
# Fail fast on everything packaging needs, before hours of compilation.
for tool in readelf ldd sha256sum tar gzip python3 curl; do
  command -v "$tool" >/dev/null || { echo "Packaging prerequisite missing: $tool" >&2; exit 1; }
done
libgomp=""
if [ "$abi" = glibc228 ]; then
  libgomp="$(gcc -print-file-name=libgomp.so.1)"
  case "$libgomp" in /*) ;; *) libgomp=/usr/lib64/libgomp.so.1 ;; esac
  test -f "$libgomp" || { echo "libgomp.so.1 not found for the portable package" >&2; exit 1; }
fi
curl --fail --location --retry 3 --connect-timeout 15 --max-time 600 --output "$build_dir/source.tar.gz" \
  "https://github.com/ggml-org/llama.cpp/archive/$source_commit.tar.gz"
printf '%s  %s\n' "$source_sha256" "$build_dir/source.tar.gz" | sha256sum --check
mkdir "$build_dir/source"
tar -xzf "$build_dir/source.tar.gz" --strip-components=1 -C "$build_dir/source"
cmake_extra=()
if [ "$accelerator" = cuda ]; then
  # Match upstream's CUDA 12.8 release headers without a mutable Git checkout.
  curl --fail --location --retry 3 --connect-timeout 15 --max-time 600 --output "$build_dir/cccl.tar.gz" \
    "https://github.com/NVIDIA/cccl/archive/$cccl_commit.tar.gz"
  printf '%s  %s\n' "$cccl_sha256" "$build_dir/cccl.tar.gz" | sha256sum --check
  mkdir "$build_dir/cccl"
  tar -xzf "$build_dir/cccl.tar.gz" --strip-components=1 -C "$build_dir/cccl"
  # Check and stage packaging prerequisites before the expensive compilation.
  mkdir "$build_dir/redistributables"
  for library in libcublas.so.12 libcublasLt.so.12 libcudart.so.12; do
    cp -L "/usr/local/cuda/lib64/$library" "$build_dir/redistributables/$library"
  done
  curl --fail --location --retry 3 --connect-timeout 15 --max-time 600 --output "$build_dir/redistributables/EULA.cuda.html" "$eula_url"
  printf '%s  %s\n' "$eula_sha256" "$build_dir/redistributables/EULA.cuda.html" | sha256sum --check
  cp "$build_dir/cccl/LICENSE" "$build_dir/redistributables/LICENSE.cccl"
  # NCCL ships in NVIDIA's devel images but not on user machines; ggml enables
  # it by default whenever found. Upstream release builds link without it.
  cmake_extra=(-DGGML_CUDA_CCCL_VERSION=v3.4.3 "-DFETCHCONTENT_SOURCE_DIR_CCCL=$build_dir/cccl" -DGGML_CUDA_NCCL=OFF)
  if command -v ccache >/dev/null; then
    cmake_extra+=(-DCMAKE_CUDA_COMPILER_LAUNCHER=ccache)
  fi
fi
cmake -S "$build_dir/source" -B "$build_dir/build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA="$cuda_enabled" -DGGML_NATIVE=OFF -DGGML_BACKEND_DL="$backend_loading" \
  -DLLAMA_BUILD_NUMBER=11429 -DLLAMA_BUILD_COMMIT="$source_commit" \
  -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON -DCMAKE_INSTALL_RPATH='$ORIGIN' \
  -DLLAMA_BUILD_TESTS=OFF "${cmake_extra[@]}" 2>&1 | tee "$output_dir/cmake-configure.txt"
cmake --build "$build_dir/build" --parallel "$jobs" --target llama-cli llama-completion llama-server llama-perplexity
package="$build_dir/llama-b11429-$abi-$accelerator"
archive_name="llama-b11429-bin-$abi-$accelerator-x64.tar.gz"
mkdir "$package"
cp -a "$build_dir/build/bin/." "$package/"
if [ "$accelerator" = cuda ]; then
  cp -a "$build_dir/redistributables/." "$package/"
fi
cp "$build_dir/source/LICENSE" "$package/LICENSE.llama.cpp"
if [ "$abi" = glibc228 ]; then
  # Minimal servers and containers often lack libgomp; ship the build host's
  # (glibc 2.28 compatible) copy beside the binaries, found via $ORIGIN.
  cp -L "$libgomp" "$package/libgomp.so.1"
fi
# Embed origin and scope, without claiming a GPU canary on hosted CPU CI.
python3 - "$package/build-origin.json" "$source_commit" "$source_sha256" "$accelerator" "$output_dir/cmake-configure.txt" "$cccl_commit" "$cccl_sha256" "$abi_platform" "$max_glibc" "$eula_url" "$eula_sha256" <<'PY'
import json, sys, subprocess, re
configure = open(sys.argv[5]).read()
match = re.search(r"Using CMAKE_CUDA_ARCHITECTURES=([^ ]+) CMAKE_CUDA_ARCHITECTURES_NATIVE=", configure)
targets = match.group(1).split(";") if match and sys.argv[4] == "cuda" else []
if sys.argv[4] == "cuda" and not targets:
    raise SystemExit("Could not record resolved upstream CUDA architecture targets")
json.dump({"upstream_commit": sys.argv[2], "source_archive_sha256": sys.argv[3],
           "platform": sys.argv[8], "cuda": "12.8.1" if sys.argv[4] == "cuda" else None,
           "compiler": subprocess.check_output(["gcc", "--version"], text=True),
           "minimum_glibc": sys.argv[9], "cuda_architectures": [int(re.match(r"[0-9]+", target).group(0)) for target in targets],
           "backend_loading": "dynamic" if sys.argv[4] == "cuda" else "linked",
           "cuda_architecture_targets": targets, "cuda_architecture_policy": "upstream_default",
           "cmake": subprocess.check_output(["cmake", "--version"], text=True),
           "cccl_version": "v3.4.3" if sys.argv[4] == "cuda" else None,
           "cccl_commit": sys.argv[6] if sys.argv[4] == "cuda" else None,
           "cccl_source_sha256": sys.argv[7] if sys.argv[4] == "cuda" else None,
           "cuda_eula_url": sys.argv[10] if sys.argv[4] == "cuda" else None,
           "cuda_eula_sha256": sys.argv[11] if sys.argv[4] == "cuda" else None,
           "gpu_execution_verified": False}, open(sys.argv[1], "w"), indent=2)
PY
for binary in llama-cli llama-completion llama-server llama-perplexity; do
  env -u LD_LIBRARY_PATH "$package/$binary" --version
  ldd "$package/$binary" | tee "$output_dir/$binary-ldd.txt"
  if ldd "$package/$binary" | grep -q 'not found'; then exit 1; fi
done
# Enforce the ABI promise: no packaged ELF may need newer glibc/libstdc++ symbols.
# Bundled NVIDIA libraries (cuBLAS, cudart) are vendor-built and checked separately.
python3 - "$package" "$max_glibc" "$max_glibcxx" "$output_dir/abi-ceiling.txt" <<'PY'
import pathlib, re, sys
root, max_glibc, max_glibcxx, report = pathlib.Path(sys.argv[1]), tuple(map(int, sys.argv[2].split("."))), int(sys.argv[3]), sys.argv[4]
vendor = ("libcublas", "libcublasLt", "libcudart")
lines, failures = [], []
for path in sorted(p for p in root.iterdir() if p.is_file() and not p.is_symlink()):
    data = path.read_bytes()
    if not data.startswith(b"\x7fELF"):
        continue
    glibc = [tuple(map(int, m.split(b"."))) for m in re.findall(rb"GLIBC_(2\.[0-9]+(?:\.[0-9]+)?)", data)]
    glibcxx = [int(m) for m in re.findall(rb"GLIBCXX_3\.4\.([0-9]+)", data)]
    top_c, top_cxx = max(glibc, default=None), max(glibcxx, default=None)
    lines.append("%s glibc=%s glibcxx=3.4.%s" % (path.name, ".".join(map(str, top_c)) if top_c else "-", top_cxx if top_cxx is not None else "-"))
    if path.name.startswith(vendor):
        continue
    if top_c and top_c > max_glibc:
        failures.append("%s needs GLIBC_%s" % (path.name, ".".join(map(str, top_c))))
    if top_cxx is not None and top_cxx > max_glibcxx:
        failures.append("%s needs GLIBCXX_3.4.%s" % (path.name, top_cxx))
open(report, "w").write("\n".join(lines) + "\n")
if failures:
    raise SystemExit("ABI ceiling exceeded: " + "; ".join(failures))
print("ABI ceiling holds: glibc <= %s, GLIBCXX_3.4.%s" % (sys.argv[2], max_glibcxx))
PY
# Host-specific libraries would break portability (e.g. Rocky 8 ships OpenSSL 1.1,
# Ubuntu 22+ ships 3.x). Only the C/C++ runtime, OpenMP, GPU drivers and files
# inside the package may be loaded from the host.
for elf in "$package"/*; do
  [ -f "$elf" ] && [ ! -L "$elf" ] || continue
  head -c 4 "$elf" | grep -q 'ELF' || continue
  readelf -d "$elf" | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' | while read -r needed; do
    case "$needed" in
      libc.so.*|libm.so.*|libdl.so.*|libpthread.so.*|librt.so.*|ld-linux*|libgcc_s.so.*|libstdc++.so.*|libgomp.so.*|libcuda.so.1|libvulkan.so.1) ;;
      # Every Ubuntu 22.04+ host ships OpenSSL 3; only the portable build must avoid it.
      libssl.so.3|libcrypto.so.3) [ "$abi" = ubuntu22 ] || { echo "$(basename "$elf") links host library $needed, which is not portable" >&2; exit 1; } ;;
      *) [ -e "$package/$needed" ] || { echo "$(basename "$elf") links host library $needed, which is not portable" >&2; exit 1; } ;;
    esac
  done
done
tar -czf "$output_dir/$archive_name" -C "$build_dir" "$(basename "$package")"
(cd "$output_dir" && sha256sum "$archive_name" > SHA256SUMS)

# Prove the archive is relocatable without the original build tree or loader overrides.
relocated="$build_dir/relocated"
mkdir "$relocated"
tar -xzf "$output_dir/$archive_name" -C "$relocated"
rm -rf "$build_dir/build" "$package"
for binary in llama-cli llama-completion llama-server llama-perplexity; do
  env -u LD_LIBRARY_PATH "$relocated/llama-b11429-$abi-$accelerator/$binary" --version
  env -u LD_LIBRARY_PATH ldd "$relocated/llama-b11429-$abi-$accelerator/$binary" > "$output_dir/$binary-relocated-ldd.txt"
  if grep -q 'not found' "$output_dir/$binary-relocated-ldd.txt"; then exit 1; fi
done

if [ "$accelerator" = cuda ]; then
  # The NVIDIA driver remains host-owned. CPU CI has no libcuda.so.1, while
  # dynamic backend loading keeps the executable usable for version/CPU checks.
  backend="$relocated/llama-b11429-$abi-cuda/libggml-cuda.so"
  test -f "$backend"
  env -u LD_LIBRARY_PATH ldd "$backend" > "$output_dir/cuda-backend-relocated-ldd.txt"
  if grep 'not found' "$output_dir/cuda-backend-relocated-ldd.txt" | grep -v 'libcuda.so.1'; then exit 1; fi
  env -u LD_LIBRARY_PATH readelf -d "$backend" > "$output_dir/cuda-backend-dynamic.txt"
  grep -F '$ORIGIN' "$output_dir/cuda-backend-dynamic.txt"
fi
