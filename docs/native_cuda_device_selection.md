# Explicit native CUDA device selections

Existing backend flags can select `--device CUDA0`, `--device CUDA1`, or a
comma-separated device list such as `--device CUDA0,CUDA1`. For native llama.cpp,
this is CUDA intent even for a custom binary with an unknown accelerator
selector. Conflicting selections, duplicate/mixed device names and a CPU
selector with CUDA device intent fail before execution.

A selected-device invocation must report positive model buffer allocations on
exactly those runtime device identities and coherent positive layer offload.
Merely announcing a device, a zero allocation, another device, a missing member
of a split selection or contradictory layer counts fails closed. The existing
runtime placement artifact retains requested device/split arguments and observed
allocations; requested policy remains distinct from observed placement.

CUDA indices are runtime enumeration identities, potentially affected by the
process environment. This check does not establish physical PCI/UUID identity,
VRAM usage, layer distribution ratios, tensor-split enforcement, zero CPU memory
use or hardware qualification. The desktop/Hub selector and stable hardware
binding are separate work. Existing calls without explicit device selections
retain the established positive CUDA/offload guard.
