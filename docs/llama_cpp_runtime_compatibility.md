# llama.cpp Runtime Compatibility

InferGrade Runner treats `llama.cpp` as an explicit runtime dependency for real GGUF runs. This guide makes that dependency more visible before a user spends time on a run that cannot load.

## Runtime Selection

For container execution, Runner uses the configured runtime image, defaulting to the canonical `ghcr.io/bfogels/infergrade-llama-cpp:<runner-version>` release image. Source developers can still select `infergrade-llama-cpp:local` explicitly. The result bundle records the container image, container runtime, and pinned runtime reference when available.

For native execution, Runner resolves binaries in this order:

- CLI flag or Desktop form value, such as `--runtime-path /path/to/llama-cli`
- selected runtime manifest written by `infergrade-runner runtime select-existing --runtime-path /path/to/llama-cli`
- run-config runtime field, such as `--llama-cpp-cli-path` or `runtime.llama_cpp_cli_path`
- environment variables: `INFERGRADE_LLAMA_CPP_CLI`, `INFERGRADE_LLAMA_CPP_SERVER`, `INFERGRADE_LLAMA_CPP_PERPLEXITY`
- system `PATH` defaults: `llama-cli`, `llama-server`, `llama-perplexity` as development and advanced-user fallbacks

Custom native paths are explicit user runtime choices. The selector requires a runnable `llama.cpp` binary before recording it, but it does not imply that InferGrade has endorsed that build or supplied it as a managed runtime.

## Compatibility Preflight

Runner records the selected runtime before deployment and capability phases. It uses ontology hints when present and can read `general.architecture` from local GGUF metadata when practical. Architecture support is established by the pinned-runtime canary matrix rather than a second hard-coded denylist that can become stale; a real load failure preserves the exact runtime version and error instead of being reclassified as compatible.

This compatibility check does not install or upgrade `llama.cpp`. Managed installation remains explicit and inspectable; signed/checksummed runtime downloads remain planned.

## Upstream Intake and Freshness

InferGrade tracks every shipped or preview llama.cpp pin in
`runtime/llama_cpp_release_policy.json`. CI fails if those recorded pins drift
from the Docker, Python, or Rust source that actually selects them.

A daily read-only workflow checks the official llama.cpp latest-release API and
uploads an advisory intake report. “Latest” is intentionally not a stable
channel: llama.cpp can publish several builds in one day, and a build that loads
a model can still regress chat templates, thinking controls, recurrent cache
behavior, memory parsing, or performance.

The safe flow is:

1. discover and coalesce new upstream releases into one candidate;
2. pin the candidate source or release-asset digest;
3. exercise a legacy control plus recent Qwen and Gemma architecture canaries;
4. verify direct-answer, thinking, multi-turn cache, telemetry, bundle, and
   regression gates;
5. promote the runtime manifest only after review, preserving the previous
   runtime for rollback.

Runtime promotion does not inherently require a Runner or contract release.
Those releases are required only when Runner code, packaging, or schemas change.
This keeps upstream runtime churn separate from InferGrade product semver.

The current macOS managed runtime and Linux CPU container are pinned to b9994
commit `14d3ba45f`. An exact Google Gemma 4 E4B QAT Q4_0 artifact passed native
Metal and container load/direct-answer canaries; the full native Runner bundle
`qb_20260714_055652_9eb6de27` also validated. That proves this artifact and
protocol on the tested M1 Pro lane, not every Gemma 4 size, quant, backend, or
hardware class. The previous b9050 macOS runtime remains available for rollback.

An explicit native runtime or custom container image remains the escape hatch
for architectures newer than InferGrade's stable pin: Runner permits the real
load attempt, records the selected runtime version, and preserves the exact
failure if the candidate is still incompatible. Qwen3.6 direct-answer checks are restricted to the native
llama-server chat path, which passes `enable_thinking=false`; Runner refuses to
substitute the older `/no_think` prompt directive because Qwen3.6 does not
support that soft switch.

Candidate servers run with llama.cpp log verbosity 4. Recent upstream builds
hide model-buffer and KV-buffer allocation lines at the default verbosity;
InferGrade requests the bounded higher level so an upgrade cannot silently turn
measured memory evidence back into unknown memory.
