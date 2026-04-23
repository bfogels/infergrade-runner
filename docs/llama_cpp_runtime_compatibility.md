# llama.cpp Runtime Compatibility

InferGrade Runner treats `llama.cpp` as an explicit runtime dependency for real GGUF runs. Sprint 56 makes that dependency more visible before a user spends time on a run that cannot load.

## Runtime Selection

For container execution, Runner uses the configured runtime image, defaulting to `infergrade-llama-cpp:local` for local development. The result bundle records the container image, container runtime, and pinned runtime reference when available.

For native execution, Runner resolves binaries in this order:

- CLI flag or run-config runtime field, such as `--llama-cpp-cli-path` or `runtime.llama_cpp_cli_path`
- environment variables: `INFERGRADE_LLAMA_CPP_CLI`, `INFERGRADE_LLAMA_CPP_SERVER`, `INFERGRADE_LLAMA_CPP_PERPLEXITY`
- system `PATH` defaults: `llama-cli`, `llama-server`, `llama-perplexity`

Custom native paths are advanced-user runtime choices. Doctor reports them as `custom_path`; it does not imply that InferGrade has verified or endorsed that build.

## Compatibility Preflight

Runner checks known model/runtime incompatibilities before deployment and capability phases. It uses ontology hints when present and can read `general.architecture` from local GGUF metadata when practical. Known unsupported architectures fail early with an actionable message instead of producing misleading partial benchmark output.

This sprint does not install or upgrade `llama.cpp`. Managed installation is intentionally reserved for Sprint 57 so upgrades remain explicit and inspectable.
