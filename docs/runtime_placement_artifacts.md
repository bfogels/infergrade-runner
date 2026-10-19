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

The initial local-artifact slice kept exported contract `0.3.40`; those uploads
do not carry placement references and remain unbound for comparison
qualification. The additive upload binding below associates each timing
observation with its actual invocation. Different observed contexts and device
allocations must remain separate in speed comparisons. The receipt
fingerprint identifies bounded placement evidence, not the complete model,
hardware, generation policy or comparison setup.

## Contract 0.3.41 upload binding

Capability task-performance payloads now carry a bounded, deduplicated table of
these same invocation receipts (`runtime_placement_receipts`, maximum 128).
Each item observation references its actual `placement_invocation_id` and
`placement_fingerprint`; missing or invalid receipts leave both null. The
receipt uses the exact local `llama_cpp_placement_artifact_v1` shape, including
requested versus observed fields. It contains no raw argv, logs or paths.

Before upload, strict schema validation and recomputation of the existing
placement fingerprint reject unexpected fields and mutated content. Reused
invocation IDs with conflicting receipts are removed. Receipt-table truncation
or validation conflicts set `runtime_placement_receipts_complete=false`.
Surface rollups preserve per-item references and deduplicate the same invocation
across artifacts; they never substitute another invocation's context. Complete
means the receipt table was not truncated or conflicted; it does not mean every
item has known placement. Consumers must resolve each qualifying item reference,
check its fingerprint and observed fields, and keep different contexts and
placement fingerprints in separate speed cohorts.

This digest establishes content binding, not independent hardware attestation.
Existing unknown/context/conflict/layer/mapped-Metal caveats remain in force.
Old .40 uploads remain unbound. Hub's pin and qualification remain a separate
integration step; source export does not deliver a new desktop release.

## Native memory recovery

Native llama-server runs use the normal automatic fitter first. A real, unscored
8-token generation follows health readiness before capability scoring. Each new
capability context/server also probes the first workload prompt and its actual
chat-template/generation-policy path. This proves compute readiness, not scorer
acceptance or that every later workload will fit. Probes never enter task timing
or deployment measurements; normal warmup and measured iterations remain intact.

On specific allocation/OOM evidence, Runner stops the failed server and retries
with automatic fitting plus `--no-mmap`. One further attempt can increase
`--fit-target` to 4096 MiB. Capability probes retain their context; supported
runtimes receive a matching `--fit-ctx` floor, and recovery rejects missing or
changed observed context. Requested device selection, model, quant, generation
policy and token budgets stay unchanged. Explicit placement/mmap/fit-margin
settings block automatic overrides. The ladder has at most three configurations
and never silently falls back from required CUDA to CPU-only execution.

A generic HTTP 500, timeout, unsupported graph or malformed completion is not
OOM evidence. For serving processes, only diagnostics appended by the failing
request can trigger recovery; old fitting diagnostics cannot reclassify a later
unrelated failure. Exhausted recovery is a terminal infrastructure error rather
than hundreds of failed scored cases.

Deployment iterations launch separate servers, so both a memory recovery and a
change in successful observed placement restart the whole profile, including
warmups. Prior attempts are excluded from timing aggregates and retained as
`discarded_memory_attempts`. Placement churn has two restarts before failing
closed. Failure progress explicitly says `failed iteration`, not `completed`.

Local path-free receipts in `artifacts/runtime-memory/<invocation_id>.json`
bind effective memory controls, requested context, recovery step, status and
confirmed OOM to the existing placement invocation. They contain no raw prompts,
logs, credentials or model paths. Positive CPU_REPACK model buffers are preserved
as CPU allocations in the existing strict placement shape. Buffer evidence
still does not establish physical residency or zero system-RAM use.

The existing extensible result contract carries effective fallback controls in
`configuration.native_memory_policy`, and bounded successful observations in
`provenance.native_memory_observations`. Effective settings change configuration
and runtime-binding identity; cumulative observation history does not. Requested
`configuration.backend_flags` stay intact. Progress and the report show
**Memory fallback** with a possible performance impact. This uses existing
contract extension points; it does not change the strict placement schema or
require an incompatible receipt shape.

Hardware validation (never uploads or publishes):

```sh
PYTHONPATH=python/runner-core/src python3 scripts/validate_native_memory_recovery.py \
  --real-run --model <model-id> --model-path <local.gguf> \
  --server-path <locked-llama-server> --output-dir <new-output-directory> \
  --expect fast # or fallback for an oversized model
```

The default validates preflight plus two warmups and five measurements of the
actual interactive profile. Its receipt distinguishes local deployment evidence
from capability scoring, upload, publication and cross-platform acceptance.

When late recovery changes a binding, each result embeds its effective ontology.
The shared `artifacts/ontology.json` represents the first result. Bundle summaries
list `benchmark_subject_ids`; their singular subject is null for multiple
bindings. Learned memory controls also follow native completion/perplexity tools
only when those executables advertise the required flags. They never silently
revert to the configuration that already failed.

Use `--probe-only` for a bounded unscored generation check on a machine under
memory pressure. A successful probe is not a complete deployment benchmark.
