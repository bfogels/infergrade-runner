#!/usr/bin/env bash
# Build the managed Linux CUDA package against Ubuntu 22.04's ABI.
set -euo pipefail
source_commit=d81235049384534c167caea52b85a694f6103d14
source_sha256=6b58785f0a82898f4c3442417ff962e2d4b231b1bee5d033902ad90b27901e14
output_dir="${1:?Pass an output directory}"
mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd)"
build_dir="$(mktemp -d)"
trap 'rm -rf "$build_dir"' EXIT
curl --fail --location --retry 3 --output "$build_dir/source.tar.gz" \
  "https://github.com/ggml-org/llama.cpp/archive/$source_commit.tar.gz"
printf '%s  %s\n' "$source_sha256" "$build_dir/source.tar.gz" | sha256sum --check
mkdir "$build_dir/source"
tar -xzf "$build_dir/source.tar.gz" --strip-components=1 -C "$build_dir/source"
cmake -S "$build_dir/source" -B "$build_dir/build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DGGML_NATIVE=OFF \
  -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON -DCMAKE_INSTALL_RPATH='$ORIGIN' \
  -DCMAKE_CUDA_ARCHITECTURES='75;80;86;89;90' -DLLAMA_BUILD_TESTS=OFF
cmake --build "$build_dir/build" --parallel 2 --target llama-cli llama-completion llama-server llama-perplexity
package="$build_dir/llama-b11429-ubuntu22-cuda"
mkdir "$package"
cp -a "$build_dir/build/bin/." "$package/"
for library in libcublas.so.12 libcublasLt.so.12 libcudart.so.12; do
  cp -L "/usr/local/cuda/lib64/$library" "$package/$library"
done
cp "$build_dir/source/LICENSE" "$package/LICENSE.llama.cpp"
cp /usr/local/cuda/EULA.txt "$package/EULA.cuda.txt"
# Embed origin and scope, without claiming a GPU canary on hosted CPU CI.
python3 - "$package/build-origin.json" "$source_commit" "$source_sha256" <<'PY'
import json, sys
json.dump({"upstream_commit": sys.argv[2], "source_archive_sha256": sys.argv[3],
           "platform": "ubuntu22.04-x86_64", "cuda": "12.8.1",
           "minimum_glibc": "2.35", "cuda_architectures": [75,80,86,89,90],
           "gpu_execution_verified": False}, open(sys.argv[1], "w"), indent=2)
PY
for binary in llama-cli llama-completion llama-server llama-perplexity; do
  LD_LIBRARY_PATH="$package${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$package/$binary" --version
  ldd "$package/$binary" | tee "$output_dir/$binary-ldd.txt"
  if ldd "$package/$binary" | grep -q 'not found'; then exit 1; fi
done
tar -czf "$output_dir/llama-b11429-bin-ubuntu22-cuda-12.8-x64.tar.gz" -C "$build_dir" "$(basename "$package")"
(cd "$output_dir" && sha256sum llama-b11429-bin-ubuntu22-cuda-12.8-x64.tar.gz > SHA256SUMS)
