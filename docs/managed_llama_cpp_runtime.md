# Managed llama.cpp Runtime

The managed-runtime lane provides a controlled managed-runtime path for users who want a known-good `llama.cpp` path without silent machine changes.

## Commands

Inspect the Runner-owned manifest:

```bash
infergrade install-runtime --runtime llama.cpp --list
```

The Rust CLI also exposes the shared engine manifest and status:

```bash
infergrade-runner runtime list
infergrade-runner runtime channels
infergrade-runner runtime status
infergrade-runner runtime install
```

Reviewed runtime candidates can also be delivered through the signed catalog
without a Runner release. Catalog metadata uses separate root, timestamp,
snapshot, and targets roles with Ed25519 thresholds, expiry, monotonic versions,
exact metadata and archive length/digests, publisher namespaces, and revocation.
The install command names the exact consented build; it will not accept blanket
consent or silently change the active selection:

```bash
infergrade-runner runtime catalog-verify \
  --catalog-dir <metadata-dir> --pinned-root <root.json> --cache-dir <cache-dir>
infergrade-runner runtime catalog-install \
  --catalog-dir <metadata-dir> --pinned-root <root.json> --cache-dir <cache-dir> \
  --target <target-name> --consent-build <runtime-build-sha256>
```

Metadata refresh activates one complete verified generation atomically. An
unexpired last-known-good generation remains usable during network failure;
expired metadata cannot authorize a new install. Already-installed immutable
builds and active per-run locks continue offline. Exact rollback re-selects a
previously archived build without rewriting any active run lock:

```bash
infergrade-runner runtime rollback --runtime-build-id <sha256>
```

`runtime/catalog/signed/` is currently a review-candidate root. Its private
keys live outside the repository. Before production distribution, the root keys
must be rotated or formally backed up with an offline recovery ceremony and the
timestamp role must have an automated refresh owner.

Preview the install plan:

```bash
infergrade install-runtime --runtime llama.cpp
```

Select existing binaries as the managed runtime:

```bash
infergrade install-runtime --runtime llama.cpp --select-existing \
  --llama-cpp-cli-path /opt/homebrew/bin/llama-cli \
  --llama-cpp-server-path /opt/homebrew/bin/llama-server
```

For the Windows CUDA preview runtime, selection records the CUDA binary set and
preview support tier, and it requires `llama-cli.exe`, `llama-server.exe`, and
`llama-perplexity.exe` from the same selected runtime directory or explicit
paths. InferGrade still does not download CUDA binaries until a pinned checksum
exists and the candidate review gate passes. The current candidate metadata can
record release URLs and release-asset SHA-256 digests while archive inspection,
license/runtime-DLL distribution review, Windows/NVIDIA smoke, Hub upload,
Result review, and support export remain pending.

The legacy Python/runner-core command keeps an execute gate:

```bash
infergrade install-runtime --runtime llama.cpp --execute
```

The Rust CLI command is itself the explicit user action:

```bash
infergrade-runner runtime install
```

## Safety Rules

- No legacy install or upgrade happens unless `--execute` is passed.
- No Rust managed install happens unless `infergrade-runner runtime install` is run explicitly.
- Runtime channel changes and updates are manual. The shared engine exposes `infergrade_stable`, `reviewed_candidate`, `previous_release`, `upstream_release`, `local_binary`, and `experimental` channel policy so Desktop and CLI can render the same safety model.
- Upstream discovery is automated but promotion is not. The daily runtime-intake workflow reports new llama.cpp candidates and pin age without silently changing a user's selected runtime.
- Managed runtime packages are immutable and content-addressed under
  `~/.cache/infergrade/runtimes/llama.cpp/builds/<runtime_build_id>/`. Installing
  different bytes under the same release label creates another build instead
  of replacing the existing package.
- `selected_runtime.json` is only the user's preferred/default runtime. A real
  native runner-core benchmark resolves that preference into a private
  per-attempt lock before backend execution; changing the preference cannot
  change a resumed run. The separate Rust CLI native-first-run preview remains
  experimental and declares `runtime_receipt_not_recorded` until it adopts the
  same binding.
- Per-attempt locks live outside uploaded bundles under
  `~/.cache/infergrade/runtimes/llama.cpp/locks/`. Results contain a path-free
  receipt with the exact build id, executable-role digests, execution-tree
  digest, origin, maturity, and provenance strength. The full managed-package
  manifest is stored once in `artifacts/receipts/runtime_receipt.json` and sent
  once as the bounded `runtime_receipt_artifact` Hub upload field.
- Build identity is a qualified content identity: it covers the normalized
  bytes plus platform, runtime interface, and declared content scope. Executable
  role assertions and support policy are recorded alongside it but do not enter
  the digest. Advanced selected binaries use synthetic receipt names so private
  executable basenames are not published.
- A managed provenance claim is accepted only when the selection points to the
  expected content-addressed build, identity-only build manifest, and matching
  immutable source assertion. Source assertions are keyed separately so the
  same execution bytes may be promoted, aliased, or obtained through another
  reviewed archive without changing or conflicting with build identity. The
  receipt carries the source-assertion id, managed runtime id, and verified
  source archive digest. Legacy or malformed selections are downgraded to a
  selected-binary local fingerprint.
- Runner verifies every locked file before backend execution and again after
  the run. Mutation or a missing lock fails the attempt; it never triggers a
  silent runtime substitution. Resume verifies the saved lock and marks the
  same attempt active again before backend execution.
- Clearing a selected runtime removes only the mutable preference. It never
  deletes immutable managed bytes. Cross-process leases, crashed-run recovery,
  inventory, and safe pruning remain a separate lifecycle feature; until that
  protocol exists, retention is deliberately conservative.
- Explicit CLI paths and `INFERGRADE_LLAMA_CPP_*` environment variables override managed selection.
- Doctor reports whether native binaries came from `custom_path`, `environment_path`, `managed_runtime`, or `system_path`.
- The Rust manifest includes macOS Apple Silicon `llama.cpp` GitHub release assets with pinned SHA-256 digests, expected binaries, compatibility notes, and rollback metadata. b9050 remains InferGrade Stable; signed-catalog b10069 is a reviewed candidate with exact MiniCPM5 and Gemma 4 qualification only.
- Rust managed runtime install is explicit: it downloads only after a user command/action, verifies SHA-256, extracts into the InferGrade runtime cache, checks expected binaries, runs a version smoke, and writes the selected runtime record.
- The upstream GitHub release asset digest is useful, but it is not an independent signature. Do not describe the runtime as independently signed until a signature lane exists.
- A signed InferGrade catalog authenticates InferGrade's target assertion; it
  does not transform an upstream checksum-only archive into an upstream-signed
  artifact. Build identity, compatibility evidence, origin, maturity,
  provenance strength, and support policy remain separate facts.
- Existing local binaries remain an advanced path. Their exact selected binary
  set is fingerprinted and locked, but it carries `local_fingerprint_only`
  provenance rather than a managed-package or signature claim.
- Broader platform manifests should be added only after clean-machine validation.
