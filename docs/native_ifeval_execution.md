# Packaged native IFEval execution

Local-native IFEval uses `ifeval_native_packaged_v1`; container requests retain the container scorer. No container equivalence or cross-platform pooling is inferred. Other container benchmarks still require Docker. Doctor and direct execution verify the evaluator before downloading or loading the model; missing/stale assets block rather than silently switch scorer.

The verified bundle is independent of host Python packages. A packaging-generated `_native_ifeval_identity.py` in trusted Runner code anchors the complete per-target receipt digest before interpreter/bootstrap execution. Bundle- or job-provided hashes cannot override it. Every inventoried file/link, manifest, source/dataset and English tokenizer pin is checked. An isolated `-I -B` probe verifies Python3.12.13, exact dependency versions/imports,541 fixtures and25/100/541 selection digests. Evaluator subprocesses receive only OS essentials, no credentials or host search paths; Python audit hooks reject networking and child commands. Interruption/timeout terminates and waits for the child. This is pure-text evaluation, not an OS sandbox for executing model code.

Prepare binds scorer-relevant kwargs through a full input-row hash in each task revision. Evaluation verifies the same bundle identity still owns scoring. Protocol fingerprints include receipt/interpreter/scoring-file digests. A dedicated artifact maps exact Google strict and loose outputs, prompt/instruction/response binding and unchanged selected-case denominators. Loose diagnostics do not replace strict scores. Quarantined completed tasks are `not_comparable` with null qualified scores; raw outcomes remain diagnostics.

## Packaging boundary

Desktop preparation and Linux x64 headless packaging rebuild from reviewed archives, materialize internal runtime links and emit the trusted code anchor. Atomic replacement cannot bless a self-rehashed prior bundle. macOS signs embedded evaluator Mach-O files; Windows signs its interpreter; Linux AppImage finalization reseals after linuxdeploy. Explicit platform-matched transforms update runtime/inventory receipts and the code anchor only after the reviewed transform. Source/dataset/tokenizer changes, new/deleted files, unrecorded links or a missing previous trusted anchor fail resealing. Release checksums/signatures cover the final package containing both code anchor and evaluator.

For source validation, explicitly build the evaluator and trusted identity in the isolated checkout, then set `INFERGRADE_NATIVE_IFEVAL_BUNDLE` to that output. This is an operator build path, not a production authentication shortcut. Linux ARM has no reviewed evaluator target and fails closed.

## Current evidence

Mac ARM bundle build, import/version/fixture probe and actual offline prepare/evaluate/artifact creation pass using synthetic responses. A quarantined25-case artifact preserves null qualified scores and25 not-comparable tasks. Fourteen stdlib tests cover custody/self-rehash rejection, inventory/manifest changes, sanitized subprocesses, fixed-error diagnostics, immutable request-scoped routing and packaging reseals. Existing capability107 and doctor19 tests pass. Full suite, final review and cross-platform package checks remain gates at this draft checkpoint.

Actual no-Docker two-machine benchmark, native Mac GUI/OS keyring acceptance and signed/distributed packages remain unproven. No prototype numbers, model performance claim, release tag or platform support promotion is implied.
