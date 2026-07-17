# InferGrade Runner 0.3.36

Runner 0.3.36 makes the desktop handoff and update surfaces truthful and recoverable.

## Desktop Runner

- A Hub assignment received while listening is paused now presents one adjacent `Start listening` recovery action.
- Assignment clocks begin when work is claimed, reset between runs, and stop on terminal states.
- Completed handoffs are cleared without removing the final completion card, so finished work cannot reappear after restart.
- Internal run IDs and cache-address prefixes no longer dominate model-facing labels.
- Update status starts unknown and changes to `Current release` only after a successful signed-update check.
- Local platform detection now resolves to a readable hardware class instead of lingering on `checking`.
- Cold Tauri and platform package builds prepare the sidecar through a cross-platform Node hook.
- Bundled Python launches no longer write bytecode into the signed app, preserving its Developer ID seal after use.
- Vite moves to 6.4.3 to resolve the current Windows dev-server path advisories.

## Release integrity

- Desktop publication now performs an unauthenticated manifest and ranged-archive check with bounded retries.
- The gate intentionally fails while artifacts are hosted only in the private source repository. This release does not claim a working public updater until a public signed/notarized artifact origin is configured and verified.

Runner contract remains `0.3.22`; this release does not change bundle schemas, pairing-token behavior, or evidence semantics.
