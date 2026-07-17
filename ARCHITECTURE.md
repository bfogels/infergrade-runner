# Architecture

InferGrade Runner is the open-source execution plane of InferGrade. It resolves
quantized model artifacts, executes benchmarks on the best realistic local path
for the hardware, and emits normalized, provenance-carrying result bundles. The
hosted InferGrade Hub consumes those bundles; the boundary between the two is
documented in [docs/runner_vs_hub.md](docs/runner_vs_hub.md).

Two decisions shape everything else:

1. **The Runner is the schema authority.** All run-config, run-request, result,
   and catalog contracts live in [`schemas/`](schemas/) and are exported as
   versioned contract bundles. The Hub pins a released contract bundle; it
   never consumes live Runner source. See
   [docs/contract_ownership.md](docs/contract_ownership.md).
2. **Local execution is primary, and each platform gets its best real path.**
   Apple Silicon runs `llama.cpp` natively so Metal is actually exercised;
   Linux prefers containerized CUDA/ROCm; CPU-only paths are labeled as such.
   Docker is optional for the first local benchmark and required only for
   sandboxed capability lanes.

## Components

```
schemas/            contract authority: run config, run request, result record,
                    capability catalog, runtime selector, examples, policies
python/runner-core/ Python execution core: CLI, orchestration, adapters,
                    transport, scoring — stdlib-only, no runtime dependencies
crates/runner-engine/  Rust engine library: pairing, token storage, Hub client,
                    worker protocol, benchmark primitives
apps/runner-cli/    Rust CLI (`infergrade-runner`): managed-runtime install,
                    status, and the native first-run lane
apps/desktop-runner/  Tauri desktop app: pairing, readiness, runtime install,
                    run lifecycle UI; ships the Rust sidecar
containers/         runtime and capability benchmark images (llama.cpp,
                    IFEval, EvalPlus, MMLU-Pro)
runtime/            pinned llama.cpp release policy (stable/candidate channels)
third_party/        vendored benchmark assets with license audit trail
scripts/            test, release, contract-export, and verification tooling
```

### Python runner-core

The execution core. Key modules under
`python/runner-core/src/infergrade/`:

- `cli.py` — all CLI entrypoints (`pair`, `start`, `run-job`, `doctor`,
  `install-runtime`, `export-support`, …)
- `runner.py` — run orchestration from request to finalized bundle
- `worker.py` — long-lived listener that claims Hub-queued jobs
- `adapters/llama_cpp.py` — primary backend adapter; `adapters/base.py`
  defines the interface
- `benchmark_catalog.py` — capability ontology (suites → groups → checks)
- `capabilities.py` — capability execution and score computation
- `transport.py` — all HTTP communication with the Hub (pairing, claiming,
  upload); refuses cleartext non-local Hub URLs
- `doctor.py` — preflight environment checks
- `artifacts.py` — model artifact resolution (Hugging Face, HTTP, local)

Execution modes: `local_native` (Apple Silicon + Metal), `local_container`
(Docker), `cloud_worker`.

### Rust workspace

The desktop product direction is an installer-and-go native app. The Rust
workspace carries that: `runner-engine` owns pairing, credential storage, and
the worker protocol; `runner-cli` exposes the managed-runtime and native
first-run lanes; the Tauri `desktop-runner` wraps both with a UI and packages
the sidecar. Python runner-core remains the execution bridge for benchmark
logic that has not moved yet. The migration plan and its guard-rails live in
[docs/desktop_runner_rust_migration.md](docs/desktop_runner_rust_migration.md)
and
[docs/desktop_runner_rust_engine_workplan.md](docs/desktop_runner_rust_engine_workplan.md).

### Contract flow

```
schemas/  ──export──▶  contract bundle (versioned)  ──pin──▶  Hub
                       release bundle + container images
```

`scripts/export_contract_bundle.py` and `scripts/build_release_bundle.sh`
produce the versioned artifacts. The `publish-contract-bundle` workflow exports
the contract bundle for `v*` tags or manual dispatch. The `release-bundle`
workflow rebuilds the complete release bundle for matching `v*` tags or manual
dispatch; ordinary `main` promotions do not create release artifacts.
`schemas/contract_manifest.json` declares the contract version and its supporting
docs.

## Principles

- **Honest about failure.** Partial evidence and failed runs are recorded and
  reported as-is; a failure report states the failing stage instead of
  pretending the run produced comparable evidence.
- **Explicit consent for machine changes.** The Runner never silently installs
  or upgrades runtimes; managed installs are checksum-verified and
  user-initiated.
- **Claim boundaries travel with the data.** Every result bundle carries the
  benchmark scope, evidence lane, and protocol identity needed to say exactly
  what a number does and does not prove.
