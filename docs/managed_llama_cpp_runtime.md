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
infergrade-runner runtime status
```

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

Run the manifest install command only after inspection:

```bash
infergrade install-runtime --runtime llama.cpp --execute
```

## Safety Rules

- No install or upgrade happens unless `--execute` is passed.
- Managed selections are stored under `~/.cache/infergrade/runtimes/llama.cpp/selected_runtime.json`.
- Explicit CLI paths and `INFERGRADE_LLAMA_CPP_*` environment variables override managed selection.
- Doctor reports whether native binaries came from `custom_path`, `environment_path`, `managed_runtime`, or `system_path`.
- The v0.2.2 Rust manifest includes a macOS Apple Silicon `llama.cpp` GitHub release asset with a pinned SHA-256 digest, expected binaries, compatibility notes, and rollback metadata.
- Runtime downloads remain disabled until checksum verification, extraction, rollback, and signature policy are reviewed. The upstream GitHub release asset digest is useful, but it is not an independent signature.
- The existing selected-runtime path remains the stable runtime path until the managed download/install path is reviewed and validated.
- Broader platform manifests should be added only after clean-machine validation.
