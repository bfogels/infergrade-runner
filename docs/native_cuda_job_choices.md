# Per-job native GPU choice

Contract 0.3.43 adds closed `infergrade.cuda_job_choices.v1` offers and a job
binding fragment. It preserves the machine-local preference and old job path.
An omitted override means Runner default, including an unset runtime default;
it never means preferred single or all. Choosing a device set for one benchmark
does not rewrite the machine preference.

Offers contain an opaque inventory revision, preferred-single and all-device
revision references, and UUID-free device descriptors. Choices enumerate each
single card, all cards, and any configured subset. Configured order stays first;
remaining cards follow inventory order. Descriptor identities include ordered
private UUID/model/exact-MiB snapshots. Revision digests are intent bindings, not
hardware attestation. Installed VRAM and card sums do not establish free memory,
fit, successful load or observed splitting.

The exported schema enforces exact descriptor count and array length for 1–16
devices. Runner validates its own projected offers against it. Consumers must
also check unique revision identities and reference membership; those semantic
relationships are not enforced by JSON Schema.

Heartbeat discovery is a single bounded background probe with a monotonic
60-second TTL and 30-second retry/refresh interval. Heartbeats do not wait for
it. Failed or expired inventory offers no choices and a fixed warning; this
cannot erase the saved preference or interrupt active work. Preference snapshots
are read when projecting offers, never captured by the discovery thread, so a
late inventory result cannot overwrite a newer preference. Queueing must review
current owned-machine offers and consent, then copy only a reported descriptor.

An explicit job choice requires all three fields: `native_device_policy_revision`
(the reviewed saved-preference revision, explicitly null when unset),
`native_device_inventory_revision`, and `native_device_choice` (the complete
reported descriptor). Partial fields, stale/default changes, unknown choices,
extra descriptor fields, changed models/capacities and missing devices fail
closed. Explicit choices require real native CUDA llama.cpp execution.

Runner fresh-probes physical inventory before execution; it never admits an
explicit choice from the heartbeat cache. One probe validates and freezes the
selected UUIDs, model and exact capacity, preserving private child visibility
and positive observed-placement requirements from contract 0.3.42. It checks
that the saved preference did not change during the probe. Later changes affect
future jobs only. Public run configs and metadata never contain physical UUIDs.

At this foundation stage, Hub must import the new contract and implement owned
planning/queue controls before per-benchmark choices are enabled. This document
is not a physical NVIDIA, native desktop-package or production acceptance receipt.
