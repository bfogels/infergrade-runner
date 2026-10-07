# Observed llama.cpp placement artifacts

Runner preserves a bounded `llama_cpp_placement_artifact_v1` JSON receipt for
each completion, perplexity, preflight or capability/deployment server invocation
that reaches allocation observation. Receipts live under
`artifacts/runtime-placement/<invocation_id>.json` in the run output directory.
Capability predictions and deployment iteration artifacts contain the same
receipt. A reused capability server shares one invocation ID; a context-growth
restart receives a new one. Receipts may contain unknown evidence, including
when a runtime does not emit supported markers. A server that fails before
readiness may have no receipt.

The receipt keeps requested placement separate from runtime log observations:

- Effective argv `--fit`, device, main-GPU index, split-mode, tensor-split, GPU-layer and context
  options are requests. A missing fit option is unknown; the runtime or
  environment may have its own default. The selected accelerator API is intent.
- Observed context and per-sequence context come from runtime markers, with null
  for missing or contradictory evidence. Requested context is never substituted.
- Offloaded/total layers classify reported layer placement as partial, all,
  zero or unknown. All layers offloaded does not establish zero CPU/RAM use,
  GPU-only compute, dedicated VRAM residency or full-GPU benchmark qualification.
- Devices count as observed weight recipients only when their model-buffer
  allocations are positive. Device enumeration, `using device`, zero-sized
  buffers and KV-only allocations do not establish weight placement. Mapped
  Metal buffers remain unified-memory evidence, not discrete VRAM claims.
- Buffer sizes are runtime allocations, not measured RSS, working set or VRAM.
  CPU mapped buffers remain visible even when all reported layers are offloaded.

No raw command, prompt, response, credential, arbitrary device name or full
path is retained in these receipts. CLI evidence is read from stderr, not
generated stdout. Buffer/device observations are bounded and explicitly mark
truncation. Conflicting layer counts remain unknown. These are runtime marker
observations, not independent attestation of physical residency.

Automatic fitting preserves explicit backend settings. A “Use both GPUs”
request or an explicit two-device/split setting is therefore intent: both GPUs
are observed weight recipients only if positive model allocations appear for
  both. Missing evidence stays unknown. Hardware acceptance on Ubuntu/NVIDIA,
  including single versus dual GPU fitting, is deferred until actual receipts.

Runtime device labels are not physical GPU UUIDs; environment visibility can
remap ordinals. A main-GPU option does not establish single-GPU execution.
Failed startup or case exceptions may leave no prediction-to-receipt binding;
absence must remain unqualified rather than borrowing another invocation.

This first slice changes local artifacts only and keeps exported contract
`0.3.40`. Uploaded compact item timing samples do not yet carry placement
references. Hub must not treat these artifacts as uploaded comparison
qualification. A subsequent additive contract needs to bind each uploaded
timing observation to its actual placement receipt; different observed contexts
and device allocations must remain separate in speed comparisons. The receipt
fingerprint identifies bounded placement evidence, not the complete model,
hardware, generation policy or comparison setup.
