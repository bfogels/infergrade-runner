# Machine-local GPU choice

`infergrade gpu-choice status --json` lists real NVIDIA inventory and the saved
native device preference. Select one or several full UUIDs from that inventory:

```
infergrade gpu-choice select --cuda-device GPU-<full UUID> --json
infergrade gpu-choice reset --json
```

Repeat `--cuda-device` to split across selected cards in that exact order. The
preference stores model and per-card capacity alongside each local UUID; those
values must still match real inventory before execution. Missing devices,
changed hardware, incompatible raw device flags and simulation fail closed.
The existing physical-mask implementation maps selected cards into CUDA0..N-1
and requires positive allocation proof. A requested split is not proof of
observed allocation or aggregate memory fit.

Private local benchmarks use the saved preference unless explicit CLI UUIDs
were supplied. An execution freezes its device selection; changing the next
preference never changes an active model's child environment. Container/cloud,
other-backend and explicitly CPU/Metal requests keep their existing behavior.
Reset preserves the runtime's existing default; it does not imply one GPU.

Hub jobs on this native lane must bind `native_device_policy_revision` to the
reported preference revision. Missing, changed or cleared consent fails before
local doctor/model execution and asks the user to review and queue again. A
revision on a different execution lane is invalid. Hub planning consumes this
protocol and binds review consent to the descriptor; successful queue retries
retain their original immutable job even after the preference changes.

The `infergrade.cuda_device_policy.v1` descriptor contains a 64-hex revision,
the existing physical selection fingerprint, selected count and ordered
model/capacity summaries. Its revision includes local UUIDs and capacities in
the digest, but heartbeat metadata never contains raw UUIDs, PCI IDs or paths.
The private file `cuda-device-policy.json` is closed, bounded to 16 KiB,
read without following links or blocking on special files, and atomically
replaced under a process lock. POSIX files are owner-only and configuration
directories must reject writes by other users. Windows inherits the config
folder/user-profile ACL; mode checks are not an ACL qualification receipt.
Malformed preferences produce a fixed heartbeat warning and block affected
native work. They do not interrupt active jobs or disable other execution lanes.

The policy reuses contract 0.3.42's immutable native request and placement proof;
it does not change canonical scoring, export physical IDs in public run configs,
or qualify untested NVIDIA hardware. Physical GPU, desktop GUI and end-to-end
Hub consent acceptance are separate gates from synthetic protocol tests.

Desktop Settings provides per-device choices, a Both control for two cards, and
an explicit selected-device checklist for larger inventories. Use runtime
default clears the saved preference. Controls wait for durable confirmation,
retain the last confirmed choice on failure and provide Refresh/reset recovery.
The bounded local helper keeps hardware UUIDs on the machine; it does not make
Hub requests. Its work/exit fence remains held until process termination is
acknowledged after a timeout or failure.

Local status distinguishes `available` inventory from `selection_ready` saved
hardware. A missing device or changed model/exact capacity leaves the preference
visible but unready; no device fallback is allowed. Installed VRAM does not prove
free memory or fit. Changing this machine preference requires another Hub plan
review; a separate per-job Both override is not implemented by these controls.
