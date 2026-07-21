# Signed Runtime Catalog Operations

Status: review-candidate metadata. The checked-in generation proves the
mechanism and pins llama.cpp b10069; it is not production-signed yet.

The assembled public production trust anchor is preserved at
`runtime/catalog/roots/production-v1.json`. It is not active merely because it
is tracked: `runtime/catalog/signed/` remains the atomic active generation
until all four production role files replace it together.

## Security model

- Runner embeds the initial root and verifies root, timestamp, snapshot, and
  targets roles with Ed25519 threshold signatures.
- Root is 2-of-3. Timestamp, snapshot, and targets use distinct online keys.
- Metadata has explicit size ceilings, monotonic versions, expiries, and exact
  length/SHA-256 references. Target archives also have exact length/SHA-256.
- Publisher namespaces and allowed origins are root policy. A specialized
  publisher cannot replace an InferGrade target or claim an unauthorized
  origin.
- One target records build identity, receipt-manifest identity, distribution
  origin, distribution maturity, provenance strength, compatibility assertions,
  and support policy as separate fields.
- Catalog signing authenticates InferGrade's assertion. It is not evidence that
  upstream independently signed a checksum-only archive.

## Promotion

1. Prove the exact archive and full immutable build on supported hardware.
2. Record model-specific compatibility assertions with exact artifact digests
   and evidence bundle ids. Keep the corresponding bounded qualification record
   under `runtime/qualification/`. Do not create generic runtime-equivalence
   cohorts.
3. Edit `runtime/catalog/catalog-source.json`. Bump targets, snapshot, and
   timestamp versions; never rewrite an existing version.
4. Build metadata with `scripts/build_runtime_catalog.py build-online`, keeping
   all private keys outside the repository. Generate
   `schemas/runtime_trust_catalog.json` in the same command. Routine builds use
   only the timestamp, snapshot, and targets keys; root private keys must not be
   mounted or otherwise available.
5. Verify the role chain and install in a clean cache. Exercise tamper, expiry,
   rollback, wrong-platform, oversized-target, consent, and rollback tests.
6. Publish all four role files as one reviewed generation. Hub serves the exact
   imported files with ETags; partial publication is not a valid release.

## Offline and rollback behavior

Runner activates a complete verified generation atomically. Network failure may
use an unexpired last-known-good generation. Expired metadata cannot authorize
a new download, while installed immutable builds and existing run locks remain
usable offline. A catalog target names an exact installed rollback build. A
failed post-install identity check restores that selection; active run locks are
never rewritten.

## Revocation

Set `revoked: true`, add a bounded reason, and publish higher targets, snapshot,
and timestamp versions. Revocation blocks new installs, new run locks, and Hub
catalog trust matching. It does not delete bytes or mutate an already-active
attempt. Recovery is an explicit selection of a different reviewed build.

## Root rotation and compromise

A new root must be signed to the embedded root threshold and its own new
threshold, with exactly the next version. This deliberately bounded client
accepts the rotation only after both checks. A later root generation requires a
Runner release carrying the next trust anchor; the current implementation does
not skip or reconstruct intermediate roots. A compromised online role is replaced through a new root and new role
metadata. Root compromise requires a Runner release with a new trust anchor and
an explicit incident note; metadata alone cannot safely repair a lost root.

## Production key ceremony

The production root replaces the unreleased review root at version 1. It does
not preserve the review keys in the public trust chain.

1. Create `root-1` on the encrypted primary offline device, `root-2` in a
   separate encrypted secure-file vault, and `root-3` in a separate
   end-to-end-encrypted password vault. Never place two root private keys on
   the same mounted filesystem.
2. Create timestamp, snapshot, and targets keys in protected operational
   custody. Export only their public descriptors to the ceremony workspace.
3. Run `init-key` once per key. A private key path must be outside the repo;
   the command refuses overwrites and writes mode 0600 private material.
4. Run `prepare-root` with all five public descriptors. Review and hash the
   resulting public-only payload.
5. Run `sign-root` once in each root custody location. Each command verifies
   that its private key matches the named public key and produces a detached
   signature bound to the payload SHA-256.
6. Run `assemble-root` with detached signatures from at least two custodians.
   The initial production root carries all three signatures. The command
   verifies Ed25519 signatures and the fixed 2-of-3 threshold before writing
   `root.json`.
7. Unmount offline custody. Run `build-online` with the assembled root and only
   the three operational keys. Verify the complete role chain before release.

Example command shapes are available from
`python3 scripts/build_runtime_catalog.py <command> --help`. Do not paste
private-key contents into a shell argument, log, issue, CI output, or chat.

### Custody and recovery

- `root-1`: encrypted removable media, normally unmounted.
- `root-2`: a distinct encrypted recovery device or secure-file vault under a
  separate account. It must not be a second folder on the `root-1` device.
- `root-3`: a distinct end-to-end-encrypted password vault under a separate
  account. Store its compact PKCS#8 DER encoding as a private password item,
  never as a shared-family credential.
- timestamp: protected automation secret; the only role eligible for routine
  unattended refresh.
- snapshot and targets: protected release-environment secrets requiring manual
  approval. A catalog content change uses these roles, but not root.
- Loss of one root key leaves the 2-of-3 threshold available. Rotate the lost
  key with the two surviving custodians. Loss of two root keys requires a
  Runner release with a new trust anchor; one surviving key cannot authorize a
  replacement.
- Suspected online-role compromise freezes publication and rotates that role by
  a new root. Suspected root compromise requires a Runner trust-anchor release
  and incident disclosure.

## Production gate

Before serving this catalog to released Runners:

- replace the review-candidate root with production root version 1 under two
  separate offline custody locations;
- assign an automated timestamp refresh and expiry monitor;
- record the public catalog base URL and atomic upload owner;
- run the release acceptance matrix from the architecture decision;
- import the resulting exact trust projection into Hub and verify a real Result
  shows one compact “InferGrade-pinned runtime” indicator.

The current b10069 candidate is qualified by two local, unpublished,
standard-depth bundles: exact MiniCPM5-1B Q4_K_M and Gemma 4 E4B Q4_0
artifacts on Apple M1 Pro Metal. The machine-readable record is
`runtime/qualification/llama-cpp-b10069-macos-arm64.json`; it deliberately
does not claim family-wide or cross-platform compatibility.
