# Codex v0.2.0 Post-Release Review

Date: 2026-05-06

## Release State

Runner v0.2.0 landed on `main` in PR #144 at merge commit `33e7a44b9a081abd088e1ea269e253d583649307`.

The release is a meaningful installer-and-go milestone, but with a deliberately scoped claim: macOS Apple Silicon native first-run works with an explicitly selected existing `llama.cpp` runtime and a local GGUF model. Managed runtime downloads, public notarized distribution, Windows/Linux installer readiness, and full clean-machine Desktop UI upload smoke are not claimed complete.

## Promise Review

- Install/open/pair flow: largely in place. Desktop pairing, reset, status, and token-safe profile handling exist. Full clean-machine pairing smoke remains a v0.2.1 priority.
- Native first-run benchmark: implemented through shared `runner-engine` and validated with a real Apple Silicon Metal `llama.cpp` smoke.
- Runtime selection/provisioning: selected existing runtime is implemented and validates runnable llama.cpp binaries. Managed download/provisioning is not implemented.
- No Docker requirement: satisfied for native first-run. Docker/Podman remain optional advanced sandbox providers.
- No user Python/Rust/global CLI/repo checkout for native first-run: package-sidecar smoke supports this for the packaged app path, but full clean-machine Desktop UI proof remains incomplete.
- Hub upload: implemented through runner-session claim, bundle upload, and completion. Validated through local Hub API/read-model smoke using the Rust CLI path; Desktop uses the same engine helpers.
- Hub evidence display: owner-visible native-first-run evidence was validated through API/read-model smoke. Browser visual validation remains a follow-up.
- Artifact/report quality: local result and bundle preview artifacts are useful and honestly labeled. Runtime provenance remains selected-existing rather than managed/verified.
- Error recovery: good token redaction and upload-failure separation landed; clean-machine Keychain and UI recovery should still be tested after package install.
- Docs/release notes honesty: release docs avoid overclaiming managed downloads, notarization, Windows/Linux, or decision-grade evidence.
- macOS package proof: local ad-hoc DMG builds, mounts, code-signs, launches, and carries the sidecar under clean PATH. Public Developer ID signing/notarization proof is still pending.

## Correctness And Maintainability

The migration is pointed in the right direction: Desktop and CLI now call shared `runner-engine` paths for native first-run, runtime selection, Hub claim/upload request construction, and token-redacted previews. The remaining largest maintainability risks are:

- CLI upload flag naming still says `--run-token` even though the credential is a paired runner token.
- Desktop first-run upload and CLI upload share engine request helpers, but no single scripted Desktop UI upload smoke exists yet.
- Python runner-core remains large and necessary for legacy/container paths, so package boundaries can still confuse contributors.
- Version sync drift was discovered during release and fixed, but future release trains should keep root workspace crates in the sync/check scripts.

## Security And Privacy Review

Good:

- Normal Hub handoff is token-free.
- Desktop stores durable tokens through OS-backed paths and does not serialize tokens into browser-visible profile state.
- Runner request previews and error messages redact bearer tokens and token-like values.
- Native command stdout/stderr previews are bounded and prompt-echo leakage is guarded.

Risks:

- CLI users can still pass paired runner tokens on the command line for upload smokes; that is useful for headless/debug but should be relabeled and eventually replaced by profile-token loading for normal CLI upload.
- Public package distribution still needs protected Developer ID/notarization proof.
- Runtime provenance for selected existing binaries is user-confirmed, not supply-chain verified.

## Supply Chain And Runtime Safety

- Runtime downloads are intentionally disabled until manifests have HTTPS, checksum, signature, expected-binary, compatibility, and rollback metadata.
- Selected existing runtime validation now rejects arbitrary files and requires a runnable llama.cpp binary.
- Local package build uses ad-hoc signing only; this is acceptable for local smoke, not public distribution.

## Open Source Readiness

The v0.2.0 release is more honest and easier to explain than prior previews. Before wider open-source/public-user distribution, the project still needs:

- notarized macOS artifact proof,
- cleaner public install docs,
- a support/debug checklist for Desktop first-run failures,
- and explicit preview labels for Windows/Linux packages.

## Failure Modes And Supportability

Top support risks:

1. User has no selected `llama.cpp` runtime and expects the app to download one.
2. User selects an incompatible or old `llama.cpp` binary.
3. Keychain access is denied or stale token state exists.
4. Hub run handoff arrives before Desktop is paired.
5. Upload fails after local benchmark succeeds.
6. Docker warnings distract from the native-first-run path.

## v0.2.0 Verdict

v0.2.0 is acceptable as a scoped milestone, not as the full final installer-and-go dream. The next release should be v0.2.1 stabilization, not a broader feature release, focused on proof, wording, and recovery around the actual native-first-run loop.
