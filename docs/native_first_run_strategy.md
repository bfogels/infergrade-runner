# Native First-Run Strategy

InferGrade Runner v0.2.0 should prove a normal Desktop user can run a first useful local benchmark without Docker, Python, Rust, a repo checkout, PATH edits, or a terminal.

## Decision

Use a Rust-owned native first-run engine path for v0.2.0. Keep Python runner-core as the transition bridge for existing advanced and legacy benchmark execution until each path has a tested Rust replacement or a packaged sidecar bridge that does not require user-installed Python.

The first Rust slice is intentionally small:

- validate a local model path
- accept a runtime hint such as `llama.cpp-metal`
- execute through an injectable native runtime adapter
- return typed load, TTFT, decode speed, token count, and memory metrics
- label results as `native_first_run`
- do not upload yet

This gives Desktop and CLI a shared contract without pretending the installer-and-go loop is complete.

## Evidence Boundary

Native first-run evidence is useful decision evidence, not reference/gold evidence. It should remain distinct from:

- sample/demo evidence
- advanced sandboxed/code-execution benchmark evidence
- stronger reference or decision-grade evidence

The first slice must not claim v0.2.0 readiness and must not imply upload support exists.

## Runtime Boundary

The engine owns typed inputs, validation, metrics, and result shape. Runtime adapters own process-specific details:

- command path
- arguments
- stdout/stderr parsing
- runtime-specific failure messages
- platform compatibility checks

For tests, the engine uses a fake runtime adapter. Later PRs can add a real llama.cpp adapter behind the same trait.

## Follow-On PRs

1. Add a Rust CLI `first-run --model <path> --runtime auto --no-upload` command that uses this engine contract with a fake or dry-run adapter first.
2. Add a real local llama.cpp runtime adapter for Apple Silicon Metal.
3. Add JSONL progress events that Desktop and CLI can render differently.
4. Add local result artifact writing.
5. Add Hub-compatible upload only after bundle shape and evidence labels are reviewed.

## Non-Goals

- no v0.2.0 label
- no runtime downloads
- no silent install or upgrade
- no Docker requirement for this native lane
- no removal of Python runner-core or Docker/container benchmark paths
