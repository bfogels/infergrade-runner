# Native First-Run Strategy

InferGrade Runner v0.2.0 should prove a normal Desktop user can run a first useful local benchmark without Docker, Python, Rust, a repo checkout, PATH edits, or a terminal.

## Decision

Use a Rust-owned native first-run engine path for v0.2.0. Keep Python runner-core as the transition bridge for existing advanced and legacy benchmark execution until each path has a tested Rust replacement or a packaged sidecar bridge that does not require user-installed Python.

The current Rust slice is intentionally small:

- validate a local model path
- accept `--runtime auto`, an explicit runtime path, or a selected `llama.cpp` runtime manifest
- execute through the built-in `llama.cpp` native runtime adapter
- return typed load, TTFT, decode speed, token count, and memory metrics
- label results as `native_first_run`
- write local artifacts and Hub-compatible bundle previews
- upload through a paired Hub runner token when a Hub handoff run is supplied

This gives Desktop and CLI a shared contract without pretending the broader installer-and-go loop is complete. Runtime downloads are still explicit/planned, so a fresh Mac needs a selected existing runtime until managed artifacts are implemented.

## Evidence Boundary

Native first-run evidence is useful decision evidence, not reference/gold evidence. It should remain distinct from:

- sample/demo evidence
- advanced sandboxed/code-execution benchmark evidence
- stronger reference or decision-grade evidence

The first-run upload path must not claim decision-grade or reference/gold trust. Uploaded native-first-run evidence stays `experimental`, `informational_only`, owner-visible, and labeled as needing confirmation until stronger gates exist.

## Runtime Boundary

The engine owns typed inputs, validation, metrics, and result shape. Runtime adapters own process-specific details:

- command path
- arguments
- stdout/stderr parsing
- runtime-specific failure messages
- platform compatibility checks

For tests, the engine uses a fake runtime adapter. Later PRs can add a real llama.cpp adapter behind the same trait.

## Follow-On PRs

1. Add a managed runtime manifest/download path with checksum, signature, compatibility, and rollback metadata.
2. Add package/fresh-machine Desktop UI smoke for the complete Hub handoff flow.
3. Expand native first-run metrics only where they can be measured honestly and portably.
4. Keep stronger decision/reference suites separate from native-first-run smoke evidence.

## Non-Goals

- no runtime downloads
- no silent install or upgrade
- no Docker requirement for this native lane
- no removal of Python runner-core or Docker/container benchmark paths
