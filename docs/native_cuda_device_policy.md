# Native CUDA physical device policy

Contract 0.3.42 adds optional `overrides.cuda_device_uuids` to run requests.
The CLI equivalent is repeated `--cuda-device GPU-<full UUID>` for native
llama.cpp runs and `benchmark-local`. No selection preserves existing behavior.
The example UUIDs in the exported request are schema examples, not real hardware.

Runner rejects non-list, abbreviated, duplicate, missing, MIG or non-CUDA
selections and conflicting raw device/main-GPU/split flags. Simulation cannot
verify this policy. Before creating a benchmark bundle, Runner freezes a bounded
`nvidia-smi` inventory and resolves every selected UUID. Inventory probes have a
five-second deadline and a 64 KiB result limit. Errors never substitute another
card. UUID order is preserved across serialization and resume request hashes.

Each native execution child receives its own `CUDA_VISIBLE_DEVICES` UUID mask
and `CUDA_DEVICE_ORDER=PCI_BUS_ID`; the parent process environment is unchanged.
CUDA remaps visible ordinals, so choosing physical card 7 alone requests `CUDA0`.
Two selected cards request `CUDA0,CUDA1`, layer split, main GPU 0 and tensor split
weights proportional to their reported MiB capacities. These weights are intent,
not proof that the runtime allocated that ratio. Automatic fitting remains active
unless explicit backend settings disable it. Every selected ordinal must have
positive model-buffer evidence and coherent positive offloaded layers. Missing,
zero, additional or conflicting allocation evidence fails execution.

`configuration.cuda_device_layout` contains a closed logical layout (policy,
device count, split mode, tensor split weights). Configuration identity includes
this layout while excluding physical UUIDs. Equivalent single-card layouts can
share a configuration identity; hardware identity still captures the selected
model/capacity. Placement receipts additionally bind the frozen policy through
`native_device_policy_fingerprint`. Both bindings are content digests, not
independent physical hardware attestation. Raw UUIDs remain in the private
request and child environment; they do not appear in normalized hardware,
configuration layout or placement receipts.

Hardware capture reports selected card count, model and capacities, preserving
host CPU/RAM/OS facts and regenerating hardware identity. Memory monitoring
filters NVIDIA readings to selected UUIDs; a missing or invalid reading is
unknown. Baseline delta remains an aggregate estimate including other processes
on those cards. It is not a per-process VRAM measurement or a full-GPU fit proof.

This foundation does not save a desktop machine preference or snapshot Hub jobs.
Hub must consume the new contract before accepting its receipt field. Desktop
selection, Hub ownership/planning/consent and real physical NVIDIA receipts are
separate delivery gates. No platform qualification or desktop release is implied.

NVIDIA documents UUID visibility masks and ordinal remapping in its
[CUDA environment variable reference](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/environment-variables.html).
Its [nvidia-smi reference](https://docs.nvidia.com/deploy/nvidia-smi/index.html)
recommends UUIDs or PCI bus IDs when consistency across reboots matters.
