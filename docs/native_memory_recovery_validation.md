# Native memory recovery validation — 2026-10-19

Local implementation validation on an Apple M1 Pro with 16 GiB unified memory,
using the user's existing managed llama.cpp b9050 package and local GGUF files.
No result was uploaded, published or counted as capability evidence. These tests
do not establish Windows/NVIDIA or Linux hardware acceptance.

| Check | Result | Evidence boundary |
| --- | --- | --- |
| TinyLlama 1.1B Q4_K_M, normal placement | Passed preflight and 2 warmups + 5 measured interactive iterations, mmap retained | Local deployment only |
| Released Runner 0.3.71 adapter baseline | 145.91 median decode tokens/sec | Same runtime/model/profile, separate local run |
| Changed adapter, warm repeat | 146.79 median decode tokens/sec | Small sequential comparison, not a general speed guarantee |
| Changed adapter, earlier cold check | 122.85 median decode tokens/sec | Preserve this variability; do not substitute the warm repeat for all conditions |
| LFM2.5-24B-A2B Q4_K_M | Original OOM detected automatically; no-mmap recovery generated successfully | Unscored compute readiness; full benchmark not accepted |
| Full seven-iteration LFM profile | Incomplete/failed validation | Stopped after about six minutes of severe paging, still in first warmup; cleanup also exceeded the existing two-second kill-wait limit. Process subsequently confirmed gone |

The Mac reported about 10 GiB of occupied swap during the interrupted 24B run.
CPU offload can relieve the Metal working-set limit while still being impractical
under total system-memory pressure. The recovery warning intentionally promises
neither GPU-only execution nor fast generation.

Receipts are retained locally under:

- `~/.cache/infergrade/dogfood/native-memory-recovery-20261019-fast/validation.json`
- `~/.cache/infergrade/dogfood/native-memory-recovery-20261019-fast-baseline/validation.json`
- `~/.cache/infergrade/dogfood/native-memory-recovery-20261019-fast-repeat/validation.json`
- `~/.cache/infergrade/dogfood/native-memory-recovery-20261019-fallback/validation.json`

Recovery attempts also retain path-free memory receipts linked to their placement
invocations in each run's `artifacts/runtime-memory/` directory. The interrupted
long run remains failed; no timing aggregate is inferred from it.

The implementation now preserves failed-attempt evidence before cleanup, makes
unconfirmed termination explicit, and starts no recovery server until cleanup
succeeds. Regression coverage includes OOM-only classification, stale-log
rejection, bounded attempts, explicit settings, context preservation, propagation
out of scoring, stable identity, late effective ontology binding, and complete
measurement-group restart on fallback or successful placement changes.

The separate `native-memory-recovery-20261019-fallback-probe/validation.json`
subsequently passed with automatic OOM → no-mmap recovery, requested 4096-token
context intact, positive generation, and confirmed process cleanup. It took
302.131 seconds under the current system-memory pressure. This is deliberately
recorded as **unscored 8-token generation readiness only**, with no deployment
timing, capability score, upload or publication claim. The earlier interrupted
full-profile failure remains preserved alongside it.

Placement receipts now exclude fitter trial allocations before the final tensor
load; comparisons use the actual serving allocation. Raw parser conflicts without
that explicit serving-load boundary remain unknown. Focused coverage verifies
that differing fit trials cannot split identical serving placements or obscure
a real difference.

Final validation: `scripts/test_all.sh` passed all **1,379 Python tests** plus the
benchmark-tier audit from a clean worktree. The focused recovery suite passed
18 tests, placement 14, adapter 82, CUDA guards 20, and orchestration 26.
Independent review found no remaining blockers after the bounded recovery,
placement-group, identity, ontology and sibling-capability fixes. No Rust or
frontend source changed; platform-specific hardware acceptance remains separate.
