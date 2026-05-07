# llama.cpp Runtime Compatibility

InferGrade Runner treats `llama.cpp` as an explicit runtime dependency for real GGUF runs. This guide makes that dependency more visible before a user spends time on a run that cannot load.

## Runtime Selection

For container execution, Runner uses the configured runtime image, defaulting to `infergrade-llama-cpp:local` for local development. The result bundle records the container image, container runtime, and pinned runtime reference when available.

For native execution, Runner resolves binaries in this order:

- CLI flag or Desktop form value, such as `--runtime-path /path/to/llama-cli`
- selected runtime manifest written by `infergrade-runner runtime select-existing --runtime-path /path/to/llama-cli`
- run-config runtime field, such as `--llama-cpp-cli-path` or `runtime.llama_cpp_cli_path`
- environment variables: `INFERGRADE_LLAMA_CPP_CLI`, `INFERGRADE_LLAMA_CPP_SERVER`, `INFERGRADE_LLAMA_CPP_PERPLEXITY`
- system `PATH` defaults: `llama-cli`, `llama-server`, `llama-perplexity` as development and advanced-user fallbacks

Custom native paths are explicit user runtime choices. The selector requires a runnable `llama.cpp` binary before recording it, but it does not imply that InferGrade has endorsed that build or supplied it as a managed runtime.

## Compatibility Preflight

Runner checks known model/runtime incompatibilities before deployment and capability phases. It uses ontology hints when present and can read `general.architecture` from local GGUF metadata when practical. Known unsupported architectures fail early with an actionable message instead of producing misleading partial benchmark output.

This compatibility check does not install or upgrade `llama.cpp`. Managed installation remains explicit and inspectable; signed/checksummed runtime downloads remain planned.
