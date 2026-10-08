# Headless install and pair

The target Linux server flow is two commands. The installer supplies the native
Runner CLI, its Python bridge and Runner-owned resources, distribution
prerequisites, and the default managed llama.cpp runtime. Pairing then starts
listening. No manual PATH export, compiler, Git checkout, Docker, separate runtime
install, or re-pairing should be needed for an ordinary native benchmark.

## Delivery status

Use the following download command with a published release that contains
`install.sh`, the headless archive, its checksum, and the compatible runtime
assets. The application release verifies this complete asset set before
publication. Workflow artifacts are not public install packages. An Ubuntu 22 loader smoke is not proof
of NVIDIA execution or a complete Hub loop.

## Install and pair

```bash
curl -fsSL https://github.com/bfogels/infergrade-runner/releases/latest/download/install.sh | bash
~/.local/bin/infergrade pair --start
```

The second command follows Runner's pairing flow and keeps the listener running.
Open the device approval link and approve this device. Hub's Linux guide uses
this device flow first. Pasted-code pairing remains available as a fallback
through `--pair-code-stdin`; older Hubs offer a hidden pairing-code prompt. The absolute per-user path works in the same shell without a PATH change
or login. The installer prints the exact path when a custom install location is
used. Headless installation initially supports Ubuntu 22.04+ and Debian 12+ Linux x86_64; Desktop
remains the install route on other platforms.

The installer may ask for administrator access to install missing distribution
packages. It does not replace GPU drivers. Runtime installation is included in
the user's install action. Existing selected/explicit runtimes are preserved;
starting the listener verifies them rather than silently upgrading or replacing
them. Container mode and simulation do not trigger native runtime downloads.

## Runtime and failure behavior

Ubuntu 22.04 supplies glibc 2.35. The upstream b11429 CUDA archive requires
`GLIBC_2.38`, so it must be rejected before downloading on that host. The
Ubuntu 22 build pins upstream commit `d81235049384534c167caea52b85a694f6103d14`
and its source archive SHA-256, builds CPU/CUDA code against the older ABI, and
records origin plus the limits of its validation. Pin the resulting archive's
hash and size only after artifact verification; do not relabel it as an upstream
binary or claim GPU execution from CPU-host CI.

Runtime activation must follow successful version checks for every required
binary. Failed setup preserves the previous selected runtime and command links.
Version-smoke errors retain the loader's error text. A listener must not register
as listening until native setup succeeds.

The Ubuntu 22 CPU candidate passed real managed installation, tiny GGUF
generation, Python adapter preflight, Rust first-run and exact-build reselection
in [managed runtime CI](https://github.com/bfogels/infergrade-runner/actions/runs/37670990948).
That same run also installed the actual headless package twice and exercised
`pair --start` against a local HTTP contract fixture, reaching listening with
zero blocking diagnostics. This fixture check is separate from hosted Hub
acceptance. Runtime archives live in the
[candidate distribution](https://github.com/bfogels/infergrade-runner/releases/tag/managed-llama-cpp-b11429-ubuntu22-20261007).

The Ubuntu 22 CUDA candidate passed all four version checks and relocated
loader checks in [its build workflow](https://github.com/bfogels/infergrade-runner/actions/runs/37694195635).
[Managed acceptance](https://github.com/bfogels/infergrade-runner/actions/runs/37706060584)
installed the published archive, generated text with explicit CPU execution, and
confirmed that missing NVIDIA devices block listening and CUDA model requests.
This does not prove physical NVIDIA execution. The immutable
[CUDA candidate](https://github.com/bfogels/infergrade-runner/releases/tag/managed-llama-cpp-b11429-ubuntu22-cuda-20261007)
contains its archive checksum and qualification receipt.

The hardware inventory keeps largest-card memory for existing fit consumers and
reports observed per-card capacities and total installed VRAM separately. Total
installed memory is not a promise of one contiguous memory allocation or verified
multi-GPU execution.
