#!/usr/bin/env bash
# Build the managed Linux CUDA package against Ubuntu 22.04's ABI.
set -euo pipefail
source_commit=d81235049384534c167caea52b85a694f6103d14
source_sha256=6b58785f0a82898f4c3442417ff962e2d4b231b1bee5d033902ad90b27901e14
cccl_commit=5fb1013e3c6f72877a2ebd30f54fe5158d64eec4
cccl_sha256=a87760bed120043b2cb58ee0482e13bb246cf77ec14b49542fb8688842bd91b5
output_dir="${1:?Pass an output directory}"
accelerator="${2:-cuda}"
if [ "$accelerator" != cuda ] && [ "$accelerator" != cpu ]; then echo 'Expected cuda or cpu.' >&2; exit 1; fi
cuda_enabled=OFF
backend_loading=OFF
if [ "$accelerator" = cuda ]; then cuda_enabled=ON; backend_loading=ON; fi
mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd)"
build_dir="$(mktemp -d)"
trap 'rm -rf "$build_dir"' EXIT
curl --fail --location --retry 3 --output "$build_dir/source.tar.gz" \
  "https://github.com/ggml-org/llama.cpp/archive/$source_commit.tar.gz"
printf '%s  %s\n' "$source_sha256" "$build_dir/source.tar.gz" | sha256sum --check
mkdir "$build_dir/source"
tar -xzf "$build_dir/source.tar.gz" --strip-components=1 -C "$build_dir/source"
cmake_extra=()
if [ "$accelerator" = cuda ]; then
  # Match upstream's CUDA 12.8 release headers without a mutable Git checkout.
  curl --fail --location --retry 3 --output "$build_dir/cccl.tar.gz" \
    "https://github.com/NVIDIA/cccl/archive/$cccl_commit.tar.gz"
  printf '%s  %s\n' "$cccl_sha256" "$build_dir/cccl.tar.gz" | sha256sum --check
  mkdir "$build_dir/cccl"
  tar -xzf "$build_dir/cccl.tar.gz" --strip-components=1 -C "$build_dir/cccl"
  cmake_extra=(-DGGML_CUDA_CCCL_VERSION=v3.4.3 "-DFETCHCONTENT_SOURCE_DIR_CCCL=$build_dir/cccl")
fi
cmake -S "$build_dir/source" -B "$build_dir/build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA="$cuda_enabled" -DGGML_NATIVE=OFF -DGGML_BACKEND_DL="$backend_loading" \
  -DLLAMA_BUILD_NUMBER=11429 -DLLAMA_BUILD_COMMIT="$source_commit" \
  -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON -DCMAKE_INSTALL_RPATH='$ORIGIN' \
  -DLLAMA_BUILD_TESTS=OFF "${cmake_extra[@]}" 2>&1 | tee "$output_dir/cmake-configure.txt"
cmake --build "$build_dir/build" --parallel 2 --target llama-cli llama-completion llama-server llama-perplexity
package="$build_dir/llama-b11429-ubuntu22-$accelerator"
archive_name="llama-b11429-bin-ubuntu22-$accelerator-x64.tar.gz"
mkdir "$package"
cp -a "$build_dir/build/bin/." "$package/"
if [ "$accelerator" = cuda ]; then
for library in libcublas.so.12 libcublasLt.so.12 libcudart.so.12; do
  cp -L "/usr/local/cuda/lib64/$library" "$package/$library"
done
cp /usr/local/cuda/EULA.txt "$package/EULA.cuda.txt"
cp "$build_dir/cccl/LICENSE" "$package/LICENSE.cccl"
fi
cp "$build_dir/source/LICENSE" "$package/LICENSE.llama.cpp"
# Embed origin and scope, without claiming a GPU canary on hosted CPU CI.
python3 - "$package/build-origin.json" "$source_commit" "$source_sha256" "$accelerator" "$output_dir/cmake-configure.txt" "$cccl_commit" "$cccl_sha256" <<'PY'
import json, sys, subprocess, re
configure = open(sys.argv[5]).read()
match = re.search(r"Using CMAKE_CUDA_ARCHITECTURES=([^ ]+) CMAKE_CUDA_ARCHITECTURES_NATIVE=", configure)
targets = match.group(1).split(";") if match and sys.argv[4] == "cuda" else []
if sys.argv[4] == "cuda" and not targets:
    raise SystemExit("Could not record resolved upstream CUDA architecture targets")
json.dump({"upstream_commit": sys.argv[2], "source_archive_sha256": sys.argv[3],
           "platform": "ubuntu22.04-x86_64", "cuda": "12.8.1" if sys.argv[4] == "cuda" else None,
           "compiler": subprocess.check_output(["gcc", "--version"], text=True),
           "minimum_glibc": "2.35", "cuda_architectures": [int(re.match(r"[0-9]+", target).group(0)) for target in targets],
           "backend_loading": "dynamic" if sys.argv[4] == "cuda" else "linked",
           "cuda_architecture_targets": targets, "cuda_architecture_policy": "upstream_default",
           "cmake": subprocess.check_output(["cmake", "--version"], text=True),
           "cccl_version": "v3.4.3" if sys.argv[4] == "cuda" else None,
           "cccl_commit": sys.argv[6] if sys.argv[4] == "cuda" else None,
           "cccl_source_sha256": sys.argv[7] if sys.argv[4] == "cuda" else None,
           "gpu_execution_verified": False}, open(sys.argv[1], "w"), indent=2)
PY
for binary in llama-cli llama-completion llama-server llama-perplexity; do
  env -u LD_LIBRARY_PATH "$package/$binary" --version
  ldd "$package/$binary" | tee "$output_dir/$binary-ldd.txt"
  if ldd "$package/$binary" | grep -q 'not found'; then exit 1; fi
done
tar -czf "$output_dir/$archive_name" -C "$build_dir" "$(basename "$package")"
(cd "$output_dir" && sha256sum "$archive_name" > SHA256SUMS)

# Prove the archive is relocatable without the original build tree or loader overrides.
relocated="$build_dir/relocated"
mkdir "$relocated"
tar -xzf "$output_dir/$archive_name" -C "$relocated"
rm -rf "$build_dir/build" "$package"
for binary in llama-cli llama-completion llama-server llama-perplexity; do
  env -u LD_LIBRARY_PATH "$relocated/llama-b11429-ubuntu22-$accelerator/$binary" --version
  env -u LD_LIBRARY_PATH ldd "$relocated/llama-b11429-ubuntu22-$accelerator/$binary" > "$output_dir/$binary-relocated-ldd.txt"
  if grep -q 'not found' "$output_dir/$binary-relocated-ldd.txt"; then exit 1; fi
done

if [ "$accelerator" = cuda ]; then
  # The NVIDIA driver remains host-owned. CPU CI has no libcuda.so.1, while
  # dynamic backend loading keeps the executable usable for version/CPU checks.
  backend="$relocated/llama-b11429-ubuntu22-cuda/libggml-cuda.so"
  test -f "$backend"
  env -u LD_LIBRARY_PATH ldd "$backend" > "$output_dir/cuda-backend-relocated-ldd.txt"
  if grep 'not found' "$output_dir/cuda-backend-relocated-ldd.txt" | grep -v 'libcuda.so.1'; then exit 1; fi
  env -u LD_LIBRARY_PATH readelf -d "$backend" > "$output_dir/cuda-backend-dynamic.txt"
  grep -F '$ORIGIN' "$output_dir/cuda-backend-dynamic.txt"
fi
