# Desktop Runner Rust Engine Workplan

This is a temporary working plan for the Rust migration while the desktop app still bridges to Python runner-core for benchmark execution.

## Branch Policy

Work primarily on `develop` while the migration is incomplete. Do not promote to `main` for every small slice. Promote to `main` only when a batch is coherent enough to justify the release CI pipeline.

## Current Boundary

- Hub owns model choice, run planning, evidence, recommendations, and result surfaces.
- Desktop Rust owns pairing, reset, token/profile state, runtime planning, readiness, and recovery.
- Python runner-core remains the execution bridge until Rust replacements have tests and bundle compatibility.
- Docker remains an optional advanced sandbox path, not a first-run gate.

## Near-Term Slices

1. Rust-owned paired-runner status.
   - Read `runner_profile.json` without exposing the token.
   - Combine profile presence and OS token presence into one status payload.
   - Use this status in the desktop UI instead of token-only checks.

2. Rust-owned listener plan and process status.
   - Resolve API URL, runner id, preferred execution mode, and token source in Rust.
   - Keep actual process launch on the current bridge until log streaming is ported.

3. Rust-owned listener lifecycle.
   - Start/stop the existing runner-core execution bridge from Rust.
   - Emit status/log events to the Tauri UI.
   - Keep Python execution as the child process.

4. Rust worker polling shell.
   - Move Hub polling, claim, heartbeat, and no-job backoff into Rust.
   - Delegate claimed execution to Python runner-core.

5. Native first-run execution.
   - Add a Docker-free benchmark path for load time, TTFT, tokens/sec, short generation, and sanity checks.
   - Keep evidence labels distinct from reference/gold evidence.

6. Runtime manager implementation.
   - Add verified runtime manifest download/select/rollback after signed artifacts exist.
   - Never install or upgrade major runtimes silently.

## Safety Rules

- No raw runner token in logs, command arguments, or browser-visible status.
- Hosted API URLs must use HTTPS; local HTTP is loopback-only.
- Preserve the Python profile file shape until Python runner-core no longer consumes it.
- Keep every slice independently reviewable.
