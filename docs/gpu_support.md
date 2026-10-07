# GPU and operating-system support

The Runner installs a pinned llama.cpp build for the machine it runs on. It picks the **first build in `runtime/llama_cpp_native_releases.json` that matches the platform and accelerator *and* that this host can load**. Nothing is downloaded when no build fits; the Runner explains why.

## Which accelerator is used

1. `INFERGRADE_ACCELERATOR=cuda|vulkan|metal|cpu`, if set (for example, to opt an integrated GPU into Vulkan, or to benchmark a GPU machine on its CPU).
2. NVIDIA (`nvidia-smi` present) → **CUDA**.
3. Apple Silicon → **Metal**.
4. AMD GPU (any), or a discrete Intel Arc GPU → **Vulkan**. Integrated Intel graphics stay on the CPU, because they are usually slower than the CPU for this workload.
5. Otherwise → **CPU**.

A GPU request never silently becomes a CPU benchmark. If no GPU build fits, or the runtime finds no GPU device after installation, setup stops with the reason and the `INFERGRADE_ACCELERATOR=cpu` opt-in.

## Host compatibility checks

Linux builds declare what they need in `platform`:

| Field | Meaning | Checked against |
|---|---|---|
| `minimum_glibc` | C library version | `getconf GNU_LIBC_VERSION` |
| `minimum_glibcxx` | libstdc++ symbol version, e.g. `3.4.30` | highest `GLIBCXX_3.4.N` in the system `libstdc++.so.6` |
| `requires_vulkan_loader` | Vulkan loader present | `libvulkan.so.1` via `ldconfig -p` or standard paths |

## Current coverage (llama.cpp b11429)

| Platform | Build | Works on |
|---|---|---|
| macOS Apple Silicon | upstream Metal | macOS (Apple Silicon) |
| Windows x86_64 + NVIDIA | upstream CUDA 12.4 | Windows 10/11, current NVIDIA driver |
| Windows x86_64 + AMD / Intel Arc | upstream Vulkan | Windows 10/11 with the vendor graphics driver |
| Linux x86_64 + NVIDIA | upstream CUDA 12.8 (glibc 2.38, GLIBCXX 3.4.32) | Ubuntu 24.04+, Debian 13, Fedora 39+, Arch |
| Linux x86_64 + NVIDIA, older distributions | **portable CUDA build (glibc 2.28)**, built by `portable-linux-runtime.yml`, pinned once published | Ubuntu 20.04+, Debian 10+, RHEL/Rocky/Alma 8+, Amazon Linux 2023 |
| Linux x86_64 + AMD / Intel Arc | upstream Vulkan (glibc 2.34, GLIBCXX 3.4.30) | Ubuntu 22.04+, Debian 12+, Fedora 36+, Arch. Needs `mesa-vulkan-drivers` + `libvulkan1` (or the vendor Vulkan driver). Not RHEL 9. |
| Linux x86_64, CPU | Ubuntu 22 build (glibc 2.35), then upstream | most distributions |
| Linux aarch64, CPU | upstream | — GPU builds (DGX Spark, Jetson) are not managed yet |

NVIDIA's CUDA 12.x runtime needs a driver from the R525 series or newer; the R570+ series is recommended for CUDA 12.8 builds. `infergrade doctor` reports the installed driver.

## Portable builds

`scripts/build_linux_cuda_runtime.sh` builds pinned upstream source for a target ABI (`INFERGRADE_RUNTIME_ABI=ubuntu22` or `glibc228`). The glibc 2.28 build runs in `nvidia/cuda:*-devel-rockylinux8` with `gcc-toolset-12` and fails unless:
- every packaged ELF stays within the ABI ceiling (written to `abi-ceiling.txt`);
- no binary links a host library outside the C/C++ runtime, OpenMP, `libcuda.so.1` and `libvulkan.so.1` (for example, OpenSSL).

`libgomp` ships inside the package. The workflow then loads every binary on Ubuntu 22.04/24.04, Debian 12, Rocky 9 and Amazon Linux 2023 containers.

After a successful run, publish the archive as a release asset and pin its URL, size and SHA-256 in the manifest *ahead of* the upstream Linux CUDA entry, so every Linux NVIDIA host runs the same binary.
