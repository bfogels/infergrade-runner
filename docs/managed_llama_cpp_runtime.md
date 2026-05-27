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
exists.

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
- Runtime channel changes and updates are manual. The shared engine exposes `infergrade_stable`, `previous_release`, `upstream_release`, `local_binary`, and `experimental` channel policy so Desktop and CLI can render the same safety model.
- Managed selections are stored under `~/.cache/infergrade/runtimes/llama.cpp/selected_runtime.json`.
- Explicit CLI paths and `INFERGRADE_LLAMA_CPP_*` environment variables override managed selection.
- Doctor reports whether native binaries came from `custom_path`, `environment_path`, `managed_runtime`, or `system_path`.
- The v0.2.2 Rust manifest includes a macOS Apple Silicon `llama.cpp` GitHub release asset with a pinned SHA-256 digest, expected binaries, compatibility notes, and rollback metadata.
- Rust managed runtime install is explicit: it downloads only after a user command/action, verifies SHA-256, extracts into the InferGrade runtime cache, checks expected binaries, runs a version smoke, and writes the selected runtime record.
- The upstream GitHub release asset digest is useful, but it is not an independent signature. Do not describe the runtime as independently signed until a signature lane exists.
- The existing selected-runtime path remains available as the advanced/local-binary fallback.
- Broader platform manifests should be added only after clean-machine validation.
