# Managed llama.cpp Runtime

Sprint 57 adds a controlled managed-runtime lane for users who want a known-good `llama.cpp` path without silent machine changes.

## Commands

Inspect the Runner-owned manifest:

```bash
infergrade install-runtime --runtime llama.cpp --list
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
- The initial known-good managed runtime is the Homebrew `llama.cpp` formula for Apple Silicon; broader platform manifests should be added only after dogfooding.
